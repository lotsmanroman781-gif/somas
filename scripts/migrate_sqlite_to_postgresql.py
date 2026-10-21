"""Explicit, read-only-source v1.1 import. Dry-run is the default; no automatic startup import."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib
from sqlalchemy import text
from app import models
from app import store
from app.catalog import CAP_KEYS, STRATEGIES
from app.neural import TinyPolicy


def utc(value):
    time = datetime.fromisoformat(value)
    if time.tzinfo is None:
        raise ValueError("Legacy timestamp must include timezone")
    time = time.astimezone(timezone.utc)
    return time.replace(microsecond=time.microsecond // 1000 * 1000)


def read_source(path):
    path = Path(path).resolve(strict=True)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        columns = {r["name"] for r in source.execute("PRAGMA table_info(orgs)")}
        if "user_id" not in columns:
            raise ValueError("Unowned v1.0 database rejected; no records imported")
        names = (
            "users",
            "sessions",
            "policies",
            "orgs",
            "agents",
            "runs",
            "feedback",
            "events",
        )
        tables = {
            name: [dict(r) for r in source.execute(f"SELECT * FROM {name}")]
            for name in names
        }
    users = {row["id"] for row in tables["users"]}
    owners = {row["id"]: row["user_id"] for row in tables["orgs"]}
    agent_owners = {
        row["id"]: (row["user_id"], row["org_id"]) for row in tables["agents"]
    }
    if any(owner not in users for owner in owners.values()):
        raise ValueError("Unknown organization owner")
    documents = []
    for table, rows in tables.items():
        for original in rows:
            row = dict(original)
            if table != "users" and row["user_id"] not in users:
                raise ValueError("Orphaned owner; import rejected")
            if (
                table in ("agents", "runs", "feedback")
                and owners.get(row["org_id"]) != row["user_id"]
            ):
                raise ValueError("Cross-owner organization reference; import rejected")
            if "created_at" in row:
                row["created_at"] = utc(row["created_at"])
            target = table
            if table == "users":
                row["email"] = row["email"].strip().lower()
                row["password_salt"] = bytes(row["password_salt"])
                row["password_hash"] = bytes(row["password_hash"])
                row["session_version"] = 0
                key = {"id": row["id"]}
            elif table == "sessions":
                row["expires_at"] = utc(row["expires_at"])
                row["session_version"] = 0
                key = {"token_hash": row["token_hash"]}
            elif table == "policies":
                policy_id = row.pop("id")
                if (
                    policy_id != "root_manager"
                    and agent_owners.get(policy_id, (None,))[0] != row["user_id"]
                ):
                    raise ValueError("Cross-owner neural policy; import rejected")
                model = TinyPolicy.deserialize(
                    row["blob"], CAP_KEYS if policy_id == "root_manager" else STRATEGIES
                )
                if model.version != row["version"]:
                    raise ValueError("Policy version does not match binary weights")
                row["policy_id"] = policy_id
                row["blob"] = bytes(row["blob"])
                key = {"user_id": row["user_id"], "policy_id": policy_id}
            elif table == "orgs":
                target = "organizations"
                row["business"] = json.loads(row["business"])
                row["plan"] = json.loads(row["plan"])
                for agent in row["plan"]["agents"]:
                    if agent_owners.get(agent["id"]) != (row["user_id"], row["id"]):
                        raise ValueError("Organization plan contains foreign agent")
                key = {"id": row["id"]}
            elif table == "runs":
                row["outputs"] = json.loads(row["outputs"])
                key = {"id": row["id"]}
            elif table == "feedback":
                row["capabilities"] = json.loads(row["capabilities"])
                row["verified"] = bool(row["verified"])
                row["id"] = f"legacy_feedback_{row['user_id']}_{row['id']}"
                key = {"id": row["id"], "user_id": row["user_id"]}
            elif table == "events":
                row["at"] = utc(row["at"])
                row["created_at"] = row.pop("at")
                target = "audit_logs"
                row["payload"] = json.loads(row["payload"])
                row["id"] = f"legacy_event_{row['user_id']}_{row['id']}"
                key = {"id": row["id"], "user_id": row["user_id"]}
            else:
                key = {"id": row["id"]}
            documents.append((target, key, row))
    return expand_relations(documents)


def expand_relations(documents):
    from app.neural import manager_policy

    by_name = {}
    for name, key, row in documents:
        by_name.setdefault(name, []).append((key, row))
    result = []
    users = by_name.get("users", [])
    orgs = {row["id"]: row for _, row in by_name.get("organizations", [])}
    policies = {
        (r["user_id"], r["policy_id"]): (k, r) for k, r in by_name.get("policies", [])
    }

    def add(name, key, row):
        result.append((name, key, row))

    for key, user in users:
        add("users", key, user)
        add(
            "agents",
            {"user_id": user["id"], "id": "root_manager"},
            dict(
                user_id=user["id"],
                id="root_manager",
                org_id=None,
                department_id=None,
                capability="manager",
                role="Manager",
                config={"kind": "manager"},
                created_at=user["created_at"],
            ),
        )
        if (user["id"], "root_manager") not in policies:
            model = manager_policy()
            row = dict(
                user_id=user["id"],
                policy_id="root_manager",
                version=0,
                blob=model.serialize(),
            )
            policies[(user["id"], "root_manager")] = (
                {"user_id": user["id"], "policy_id": "root_manager"},
                row,
            )
    for key, org in by_name.get("organizations", []):
        org["manager_agent_id"] = "root_manager"
        add("organizations", key, org)
        add(
            "memberships",
            {"org_id": org["id"], "user_id": org["user_id"]},
            dict(
                org_id=org["id"],
                user_id=org["user_id"],
                owner_id=org["user_id"],
                role="owner",
                created_at=org["created_at"],
            ),
        )
    departments = {}
    for key, agent in by_name.get("agents", []):
        org = orgs[agent["org_id"]]
        config = next(
            (a for a in org["plan"]["agents"] if a["id"] == agent["id"]), None
        )
        if config is None:
            raise ValueError("Agent not present in organization plan")
        name = config.get("team") or agent["capability"]
        identity = (agent["user_id"], agent["org_id"], name)
        dept_id = (
            "legacy_dept_"
            + hashlib.sha256(":".join(identity).encode()).hexdigest()[:24]
        )
        if identity not in departments:
            departments[identity] = dept_id
            add(
                "departments",
                dict(user_id=agent["user_id"], org_id=agent["org_id"], id=dept_id),
                dict(
                    user_id=agent["user_id"],
                    org_id=agent["org_id"],
                    id=dept_id,
                    name=name,
                    config={"designed_by": "root_manager"},
                ),
            )
        agent.update(department_id=dept_id, config=config)
        add("agents", {"user_id": agent["user_id"], "id": agent["id"]}, agent)
    for org in orgs.values():
        permitted = {a["id"] for a in org["plan"]["agents"]} | {"root_manager"}
        for i, edge in enumerate(org["plan"].get("relationships", [])):
            if edge["source"] not in permitted or edge["target"] not in permitted:
                raise ValueError("Foreign relationship endpoint")
            identity = "legacy_relation_" + org["id"] + "_" + str(i)
            add(
                "relationships",
                {"id": identity},
                dict(
                    id=identity,
                    user_id=org["user_id"],
                    org_id=org["id"],
                    created_at=org["created_at"],
                    source=edge["source"],
                    target=edge["target"],
                    kind=edge["type"],
                ),
            )
    for key, row in policies.values():
        add("policies", key, row)
        created = next(u["created_at"] for _, u in users if u["id"] == row["user_id"])
        add(
            "policy_versions",
            dict(key, version=row["version"]),
            dict(row, created_at=created),
        )
    for name in ("sessions", "runs", "feedback", "audit_logs"):
        for key, row in by_name.get(name, []):
            add(name, key, row)
    return result


async def import_documents(documents, apply=False):
    if len(documents) > 10000:
        raise ValueError("Import exceeds 10000 rows; requires reviewed batching")
    # Stable dependency order; departments must precede their agents.
    order = {
        "users": 0,
        "organizations": 2,
        "memberships": 3,
        "departments": 4,
        "relationships": 6,
        "policies": 7,
        "policy_versions": 8,
        "sessions": 9,
        "runs": 10,
        "feedback": 11,
        "audit_logs": 12,
    }
    ordered = sorted(
        documents,
        key=lambda d: (
            (1 if d[0] == "agents" and d[2]["id"] == "root_manager" else 5)
            if d[0] == "agents"
            else order[d[0]]
        ),
    )

    async def operation(session):
        await session.execute(text("SELECT pg_advisory_xact_lock(731295121)"))
        for name, key, expected in ordered:
            table = models.Base.metadata.tables[name]
            model = next(
                m.class_
                for m in models.Base.registry.mappers
                if m.local_table.name == name
            )
            where = [table.c[k] == v for k, v in key.items()]
            existing = await store.fetch_one(model, *where, session=session)
            if existing:
                if any(existing.get(k) != v for k, v in expected.items()):
                    raise ValueError(
                        "Target contains conflicting data; nothing overwritten"
                    )
            elif apply:
                await store.insert_row(model, expected, session)
            else:
                raise ValueError("Verification failed: missing target row")

    await store.transaction(operation)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    documents = read_source(args.source)
    if not args.apply and not args.verify:
        print(f"Dry run: validated {len(documents)} owned rows. No database writes.")
        return
    await store.init_db()
    try:
        await import_documents(documents, apply=args.apply)
        print(f"{'Imported' if args.apply else 'Verified'} {len(documents)} rows.")
    finally:
        await store.close_db()


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except Exception:
        # Do not print connection strings, account rows, or database diagnostics.
        print(
            "Migration failed. Check source ownership/schema, target conflicts and database access.",
            file=sys.stderr,
        )
        sys.exit(1)
