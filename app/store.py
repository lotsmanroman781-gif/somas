"""PostgreSQL repositories with explicit owner scoping and atomic business writes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import database
from .catalog import CAP_KEYS, STRATEGIES
from .models import (
    Agent,
    AuditLog,
    Conversation,
    Decision,
    Department,
    Feedback,
    Membership,
    Organization,
    Policy,
    PolicyVersion,
    RateLimit,
    Relationship,
    Run,
    Session,
    User,
)
from .neural import TinyPolicy, manager_policy, worker_policy

init_db = database.init_db
close_db = database.close_db


class PolicyConflict(Exception):
    pass


def stamp():
    return datetime.now(timezone.utc)


def new_id(prefix):
    return prefix + "_" + uuid.uuid4().hex


async def fetch_one(model, *where, session=None):
    async with database.scope(session) as current:
        result = await current.execute(select(model.__table__).where(*where))
        row = result.mappings().first()
        return dict(row) if row else None


async def insert_row(model, values, session=None):
    async with database.scope(session) as current:
        await current.execute(insert(model).values(**values))


async def transaction(callback):
    async with database.scope() as session:
        return await callback(session)


async def require_user(user_id, session=None):
    if not await fetch_one(User, User.id == user_id, session=session):
        raise KeyError("User not found")


async def require_org(user_id, org_id, session=None):
    row = await fetch_one(
        Organization,
        Organization.user_id == user_id,
        Organization.id == org_id,
        session=session,
    )
    if not row:
        raise KeyError("Organization not found")
    return row


async def add_event(user_id, kind, ref_id, payload, session=None):
    await insert_row(
        AuditLog,
        dict(
            id=new_id("event"),
            user_id=user_id,
            created_at=stamp(),
            kind=kind,
            ref_id=ref_id,
            payload=payload,
        ),
        session,
    )


async def events(user_id, limit=30, offset=0):
    async with database.scope() as session:
        rows = (
            await session.execute(
                select(AuditLog.__table__)
                .where(AuditLog.user_id == user_id)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).mappings()
        return [
            dict(
                id=r["id"],
                at=r["created_at"],
                kind=r["kind"],
                ref_id=r["ref_id"],
                payload=r["payload"],
            )
            for r in rows
        ]


async def load_policy(user_id, key, kind="manager"):
    row = await fetch_one(Policy, Policy.user_id == user_id, Policy.policy_id == key)
    if row:
        model = TinyPolicy.deserialize(
            bytes(row["blob"]), CAP_KEYS if kind == "manager" else STRATEGIES
        )
    else:
        model = (
            manager_policy()
            if kind == "manager"
            else worker_policy(seed=42 + sum((user_id + key).encode()) % 10000)
        )
    model.persisted_version = row["version"] if row else None
    return model


async def save_policy(user_id, key, model, session=None):
    async with database.scope(session) as current:
        previous = getattr(model, "persisted_version", None)
        blob = model.serialize()
        if previous is None:
            result = await current.execute(
                pg_insert(Policy)
                .values(
                    user_id=user_id, policy_id=key, version=model.version, blob=blob
                )
                .on_conflict_do_nothing()
                .returning(Policy.version)
            )
        else:
            result = await current.execute(
                update(Policy)
                .where(
                    Policy.user_id == user_id,
                    Policy.policy_id == key,
                    Policy.version == previous,
                )
                .values(version=model.version, blob=blob)
                .returning(Policy.version)
            )
        if result.scalar_one_or_none() is None:
            raise PolicyConflict()
        await insert_row(
            PolicyVersion,
            dict(
                user_id=user_id,
                policy_id=key,
                version=model.version,
                blob=blob,
                created_at=stamp(),
            ),
            current,
        )


async def register_user(uid, email, name, salt, digest):
    async def commit(session):
        await insert_row(
            User,
            dict(
                id=uid,
                email=email,
                display_name=name,
                password_salt=salt,
                password_hash=digest,
                created_at=stamp(),
                session_version=0,
            ),
            session,
        )
        await insert_row(
            Agent,
            dict(
                id="root_manager",
                user_id=uid,
                org_id=None,
                department_id=None,
                capability="manager",
                role="Manager",
                config={"kind": "manager"},
                created_at=stamp(),
            ),
            session,
        )
        await save_policy(uid, "root_manager", manager_policy(), session)

    await transaction(commit)


async def user_by_id(uid):
    row = await fetch_one(User, User.id == uid)
    return (
        {k: row[k] for k in ("id", "email", "display_name", "created_at")}
        if row
        else None
    )


async def user_credentials(email):
    return await fetch_one(User, User.email == email)


async def issue_session(uid, token_hash, csrf, now, expires, expected_version=None):
    async with database.scope() as session:
        # Serialize session issuance against password changes for this account.
        result = await session.execute(
            select(User).where(User.id == uid).with_for_update()
        )
        user = result.scalar_one_or_none()
        if not user or (
            expected_version is not None and user.session_version != expected_version
        ):
            return False
        await session.execute(
            delete(Session).where(Session.user_id == uid, Session.expires_at < now)
        )
        await insert_row(
            Session,
            dict(
                token_hash=token_hash,
                user_id=uid,
                csrf=csrf,
                created_at=now,
                expires_at=expires,
                session_version=user.session_version,
            ),
            session,
        )
        return True


async def session_for(token_hash):
    async with database.scope() as session:
        row = (
            (
                await session.execute(
                    select(Session.__table__)
                    .join(User, User.id == Session.user_id)
                    .where(
                        Session.token_hash == token_hash,
                        Session.expires_at > stamp(),
                        Session.session_version == User.session_version,
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


async def destroy_session(user_id, token_hash):
    async with database.scope() as session:
        await session.execute(
            delete(Session).where(
                Session.user_id == user_id, Session.token_hash == token_hash
            )
        )


async def change_password(user_id, expected_version, salt, digest):
    async with database.scope() as session:
        result = await session.execute(
            update(User)
            .where(User.id == user_id, User.session_version == expected_version)
            .values(
                password_salt=salt,
                password_hash=digest,
                session_version=User.session_version + 1,
            )
        )
        if result.rowcount != 1:
            return False
        await session.execute(delete(Session).where(Session.user_id == user_id))
        await add_event(user_id, "password_changed", user_id, {}, session)
        return True


async def update_profile(user_id, name):
    async with database.scope() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(display_name=name)
        )


async def throttle(key, expires):
    async with database.scope() as session:
        # Expiry is opportunistic and durable; no background worker is required.
        await session.execute(delete(RateLimit).where(RateLimit.expires_at < stamp()))
        statement = pg_insert(RateLimit).values(id=key, count=1, expires_at=expires)
        row = await session.execute(
            statement.on_conflict_do_update(
                index_elements=[RateLimit.id], set_={"count": RateLimit.count + 1}
            ).returning(RateLimit.count)
        )
        return row.scalar_one()


async def materialize_graph(user_id, org_id, plan, agent_rows, created, session):
    departments = {}
    for a in agent_rows:
        name = a.get("team") or a["capability"]
        if name not in departments:
            department_id = new_id("dept")
            departments[name] = department_id
            await insert_row(
                Department,
                dict(
                    user_id=user_id,
                    org_id=org_id,
                    id=department_id,
                    name=name,
                    config={"designed_by": "root_manager"},
                ),
                session,
            )
        await insert_row(
            Agent,
            dict(
                id=a["id"],
                user_id=user_id,
                org_id=org_id,
                department_id=departments[name],
                capability=a["capability"],
                role=a["role"],
                config=a,
                created_at=created,
            ),
            session,
        )
    for edge in plan.get("relationships", []):
        allowed = {a["id"] for a in agent_rows} | {"root_manager"}
        if edge["source"] not in allowed or edge["target"] not in allowed:
            raise ValueError("Relationship endpoint is outside the organization")
        await insert_row(
            Relationship,
            dict(
                id=new_id("relation"),
                user_id=user_id,
                org_id=org_id,
                source=edge["source"],
                target=edge["target"],
                kind=edge["type"],
                created_at=created,
            ),
            session,
        )


async def add_org(user_id, org_id, business, plan, agent_rows, policies):
    if plan.get("agents") != agent_rows:
        raise ValueError("Agents do not match plan")

    async def commit(session):
        await require_user(user_id, session)
        created = stamp()
        await insert_row(
            Organization,
            dict(
                id=org_id,
                user_id=user_id,
                created_at=created,
                business=business,
                plan=plan,
                status="planned",
                manager_agent_id="root_manager",
            ),
            session,
        )
        await insert_row(
            Membership,
            dict(
                org_id=org_id,
                user_id=user_id,
                owner_id=user_id,
                role="owner",
                created_at=created,
            ),
            session,
        )
        await materialize_graph(user_id, org_id, plan, agent_rows, created, session)
        for a in agent_rows:
            policy = policies[a["id"]]
            # Inherited weights create a new policy namespace, retaining its trained version.
            blob = policy.serialize()
            await insert_row(
                Policy,
                dict(
                    user_id=user_id,
                    policy_id=a["id"],
                    version=policy.version,
                    blob=blob,
                ),
                session,
            )
            await insert_row(
                PolicyVersion,
                dict(
                    user_id=user_id,
                    policy_id=a["id"],
                    version=policy.version,
                    blob=blob,
                    created_at=created,
                ),
                session,
            )
        await insert_row(
            Decision,
            dict(
                id=new_id("decision"),
                user_id=user_id,
                org_id=org_id,
                agent_id="root_manager",
                run_id=None,
                created_at=created,
                data=plan["manager_filter"],
            ),
            session,
        )
        await add_event(
            user_id,
            "organization_created",
            org_id,
            {"agents": len(agent_rows), "mode": plan["planning_mode"]},
            session,
        )

    await transaction(commit)


async def get_org(user_id, org_id):
    row = await fetch_one(
        Organization, Organization.user_id == user_id, Organization.id == org_id
    )
    return (
        {k: row[k] for k in ("id", "created_at", "business", "plan", "status")}
        if row
        else None
    )


async def list_orgs(user_id, limit=100, offset=0):
    async with database.scope() as session:
        rows = (
            await session.execute(
                select(Organization)
                .where(Organization.user_id == user_id)
                .order_by(Organization.created_at.desc(), Organization.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return [
            dict(
                id=r.id,
                created_at=r.created_at,
                business=r.business,
                status=r.status,
                agent_count=len(r.plan.get("agents", [])),
            )
            for r in rows
        ]


async def list_agents(user_id, limit=100, offset=0):
    async with database.scope() as session:
        rows = (
            await session.execute(
                select(Agent, Organization.business, Policy.version)
                .join(
                    Organization,
                    (Agent.org_id == Organization.id)
                    & (Agent.user_id == Organization.user_id),
                )
                .join(
                    Policy,
                    (Policy.user_id == Agent.user_id) & (Policy.policy_id == Agent.id),
                )
                .where(Agent.user_id == user_id)
                .order_by(Agent.created_at.desc(), Agent.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            dict(
                id=a.id,
                org_id=a.org_id,
                capability=a.capability,
                role=a.role,
                created_at=a.created_at,
                business_name=b["name"],
                policy_version=v,
            )
            for a, b, v in rows
        ]


async def record_run(user_id, run_id, org_id, mode, status, outputs):
    async def commit(session):
        org = await require_org(user_id, org_id, session)
        await insert_row(
            Run,
            dict(
                id=run_id,
                user_id=user_id,
                org_id=org_id,
                created_at=stamp(),
                mode=mode,
                status=status,
                outputs=outputs,
            ),
            session,
        )
        steps = outputs.get("steps", [])
        for index, step in enumerate(steps):
            await insert_row(
                Decision,
                dict(
                    id=new_id("decision"),
                    user_id=user_id,
                    org_id=org_id,
                    agent_id=step["agent_id"],
                    run_id=run_id,
                    created_at=stamp(),
                    data=step["strategy"],
                ),
                session,
            )
            assigned = next(
                a["task"] for a in org["plan"]["agents"] if a["id"] == step["agent_id"]
            )
            await insert_row(
                Conversation,
                dict(
                    id=new_id("message"),
                    user_id=user_id,
                    org_id=org_id,
                    run_id=run_id,
                    sender_id="root_manager",
                    receiver_id=step["agent_id"],
                    content=assigned,
                    created_at=stamp(),
                ),
                session,
            )
            if mode == "ai":
                for prior in steps[max(0, index - 4) : index]:
                    await insert_row(
                        Conversation,
                        dict(
                            id=new_id("message"),
                            user_id=user_id,
                            org_id=org_id,
                            run_id=run_id,
                            sender_id=prior["agent_id"],
                            receiver_id=step["agent_id"],
                            content=prior["deliverable"][:550],
                            created_at=stamp(),
                        ),
                        session,
                    )
        if status == "completed":
            await session.execute(
                update(Organization)
                .where(Organization.user_id == user_id, Organization.id == org_id)
                .values(status="executed_demo" if mode == "demo" else "executed_ai")
            )
        await add_event(
            user_id,
            "run_recorded",
            org_id,
            {"run_id": run_id, "status": status, "mode": mode},
            session,
        )

    await transaction(commit)


async def list_org_records(model, user_id, org_id, limit=100, offset=0):
    async with database.scope() as session:
        await require_org(user_id, org_id, session)
        rows = (
            await session.execute(
                select(model.__table__)
                .where(model.user_id == user_id, model.org_id == org_id)
                .order_by(model.created_at.desc(), model.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).mappings()
        return [{k: v for k, v in row.items() if k != "user_id"} for row in rows]


async def list_runs(user_id, org_id, limit=100, offset=0):
    return await list_org_records(Run, user_id, org_id, limit, offset)


async def add_feedback(
    user_id, org_id, score, caps, notes, verified, policy_version, session=None
):
    async with database.scope(session) as current:
        await require_org(user_id, org_id, current)
        await insert_row(
            Feedback,
            dict(
                id=new_id("feedback"),
                user_id=user_id,
                org_id=org_id,
                created_at=stamp(),
                score=score,
                capabilities=caps,
                notes=notes,
                verified=bool(verified),
                policy_version=policy_version,
            ),
            current,
        )
        await add_event(
            user_id,
            "verified_feedback" if verified else "unverified_feedback",
            org_id,
            {"score": score, "corrected_capabilities": caps},
            current,
        )


async def add_worker_feedback(
    user_id, org_id, agent_id, strategy, verified, version, session
):
    await require_org(user_id, org_id, session)
    await insert_row(
        Feedback,
        dict(
            id=new_id("feedback"),
            user_id=user_id,
            org_id=org_id,
            agent_id=agent_id,
            created_at=stamp(),
            verified=bool(verified),
            corrected_strategy=strategy,
            policy_version=version,
            capabilities=[],
            notes="",
        ),
        session,
    )


async def org_metadata(user_id, org_id, kind, limit=100, offset=0):
    if kind in ("conversations", "decisions", "feedback", "relationships"):
        model = {
            "conversations": Conversation,
            "decisions": Decision,
            "feedback": Feedback,
            "relationships": Relationship,
        }[kind]
        return await list_org_records(model, user_id, org_id, limit, offset)
    async with database.scope() as session:
        await require_org(user_id, org_id, session)
        if kind == "departments":
            query = (
                select(Department.__table__)
                .where(Department.user_id == user_id, Department.org_id == org_id)
                .order_by(Department.id)
            )
        else:
            query = (
                select(Membership.__table__)
                .where(Membership.owner_id == user_id, Membership.org_id == org_id)
                .order_by(Membership.user_id)
            )
        return [
            dict(r)
            for r in (
                await session.execute(query.offset(offset).limit(limit))
            ).mappings()
        ]


async def agent_detail(user_id, org_id, agent_id):
    row = await fetch_one(
        Agent, Agent.user_id == user_id, Agent.org_id == org_id, Agent.id == agent_id
    )
    if not row:
        raise KeyError("Agent not found")
    return {k: v for k, v in row.items() if k != "user_id"}


async def update_agent(user_id, org_id, agent_id, changes):
    import copy

    async with database.scope() as session:
        row = (
            await session.execute(
                select(Organization)
                .where(Organization.user_id == user_id, Organization.id == org_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise KeyError("Organization not found")
        plan = copy.deepcopy(row.plan)
        agent = next((a for a in plan["agents"] if a["id"] == agent_id), None)
        if not agent:
            raise KeyError("Agent not found")
        agent.update(changes)
        await session.execute(
            update(Agent)
            .where(
                Agent.user_id == user_id, Agent.org_id == org_id, Agent.id == agent_id
            )
            .values(config=agent, role=agent["role"])
        )
        await session.execute(
            update(Organization)
            .where(Organization.user_id == user_id, Organization.id == org_id)
            .values(plan=plan)
        )
        await add_event(
            user_id, "agent_updated", agent_id, {"fields": list(changes)}, session
        )
    return await agent_detail(user_id, org_id, agent_id)
