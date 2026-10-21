import asyncio
import hashlib
import os
import subprocess
import sys
from datetime import timedelta

import numpy as np
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError, IntegrityError
from alembic import command
from alembic.config import Config

from app import auth, database, engine, store
from app.models import (
    Agent,
    Conversation,
    Decision,
    Feedback,
    Membership,
    Organization,
    Policy,
    PolicyVersion,
    Session,
    User,
)


async def count(model, *where):
    async with database.scope() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(*where)
        )


async def test_expiry_and_version_revocation(client):
    async with database.scope() as session:
        await session.execute(
            update(Session)
            .where(Session.user_id == client.test_user_id)
            .values(expires_at=store.stamp() - timedelta(seconds=1))
        )
    assert (await client.get("/api/auth/me")).status_code == 401
    token, csrf = await auth.issue_session(client.test_user_id)
    client.cookies.set(auth.COOKIE_NAME, token)
    async with database.scope() as session:
        await session.execute(
            update(User).where(User.id == client.test_user_id).values(session_version=1)
        )
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_restart_preserves_user_session_org_and_trained_weights(client, retail):
    org = (await client.post("/api/organizations", json=retail)).json()
    oid = org["id"]
    aid = org["plan"]["agents"][0]["id"]
    assert (
        await client.post(
            f"/api/organizations/{oid}/feedback",
            json={"score": 5, "correct_capabilities": ["quality"], "verified": True},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/organizations/{oid}/agents/{aid}/feedback",
            json={"corrected_strategy": "verify", "verified": True},
        )
    ).status_code == 200
    await client.post(f"/api/organizations/{oid}/run", json={"mode": "demo"})
    manager = await store.load_policy(client.test_user_id, "root_manager")
    worker = await store.load_policy(client.test_user_id, aid, "worker")
    row = await store.fetch_one(
        Policy, Policy.user_id == client.test_user_id, Policy.policy_id == aid
    )
    program = """import asyncio,os,sys,hashlib
if sys.platform=='win32':asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from app import store
from app.models import Policy
async def main():
 await store.init_db()
 row=await store.fetch_one(Policy,Policy.user_id==os.environ['TEST_OWNER'],Policy.policy_id==os.environ['TEST_AGENT'])
 print(hashlib.sha256(bytes(row['blob'])).hexdigest())
 await store.close_db()
asyncio.run(main())
"""
    child = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", program],
        env=dict(os.environ, TEST_OWNER=client.test_user_id, TEST_AGENT=aid),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 0, "Separate persistence reader failed"
    assert child.stdout.strip() == hashlib.sha256(row["blob"]).hexdigest()
    await store.close_db()
    await store.init_db()
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.get(f"/api/organizations/{oid}")).status_code == 200
    assert len((await client.get(f"/api/organizations/{oid}/runs")).json()) == 1
    assert np.array_equal(
        manager.w2, (await store.load_policy(client.test_user_id, "root_manager")).w2
    )
    assert np.array_equal(
        worker.w2, (await store.load_policy(client.test_user_id, aid, "worker")).w2
    )
    assert await count(Feedback, Feedback.user_id == client.test_user_id) == 2
    assert (
        await count(
            PolicyVersion,
            PolicyVersion.user_id == client.test_user_id,
            PolicyVersion.policy_id == aid,
        )
        == 2
    )


async def test_concurrent_training_compare_and_set(client, retail):
    org = (await client.post("/api/organizations", json=retail)).json()
    x = engine.business_state(org["business"])
    a = await store.load_policy(client.test_user_id, "root_manager")
    b = await store.load_policy(client.test_user_id, "root_manager")
    a.fit([x], [[1] * 13], epochs=2)
    b.fit([x], [[0] * 13], epochs=2)
    results = await asyncio.gather(
        store.save_policy(client.test_user_id, "root_manager", a),
        store.save_policy(client.test_user_id, "root_manager", b),
        return_exceptions=True,
    )
    assert sum(isinstance(r, store.PolicyConflict) for r in results) == 1
    assert (await store.load_policy(client.test_user_id, "root_manager")).version == 1


async def test_training_conflict_rolls_back_feedback(client, retail, monkeypatch):
    org = (await client.post("/api/organizations", json=retail)).json()

    async def conflict(*args, **kwargs):
        raise store.PolicyConflict()

    monkeypatch.setattr(store, "save_policy", conflict)
    response = await client.post(
        f"/api/organizations/{org['id']}/feedback",
        json={"score": 5, "correct_capabilities": ["quality"], "verified": True},
    )
    assert response.status_code == 409
    assert await count(Feedback) == 0


async def test_partial_organization_transaction_rolls_back(client, retail, monkeypatch):
    original = store.insert_row

    async def fail(model, values, session=None):
        if model is Agent and values["id"] != "root_manager":
            raise IntegrityError(
                "injected", "secret-parameters", Exception("collision")
            )
        return await original(model, values, session)

    monkeypatch.setattr(store, "insert_row", fail)
    response = await client.post("/api/organizations", json=retail)
    assert response.status_code == 503
    assert "secret-parameters" not in response.text
    assert await count(Organization) == await count(Membership) == 0
    assert await count(Agent, Agent.org_id.is_not(None)) == 0


async def test_database_outage_and_recovery(client, monkeypatch):
    original = store.session_for

    async def unavailable(*args):
        raise OperationalError("private", "secret", Exception("outage"))

    monkeypatch.setattr(store, "session_for", unavailable)
    response = await client.get("/api/organizations")
    assert response.status_code == 503
    assert "secret" not in response.text
    assert (await client.get("/healthz")).status_code == 200
    monkeypatch.setattr(store, "session_for", original)
    await store.close_db()
    await store.init_db()
    assert (await client.get("/readyz")).status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_origin_limits_signup_switch_and_gateway(client, monkeypatch):
    invalid = await client.post(
        "/api/auth/register",
        json={"email": "invalid", "display_name": "User", "password": "SECRET-PW"},
    )
    assert invalid.status_code == 422
    assert "SECRET-PW" not in invalid.text
    assert (
        await client.post(
            "/api/auth/logout", headers={"Origin": "https://evil.example"}
        )
    ).status_code == 403
    assert (
        await client.post("/api/auth/login", content="x" * 32769)
    ).status_code == 413
    assert (await client.get("/api/organizations?limit=101")).status_code == 422
    monkeypatch.setenv("SOMAS_ALLOW_PUBLIC_SIGNUP", "false")
    assert (
        await client.post(
            "/api/auth/register",
            json={
                "email": "new@example.com",
                "display_name": "New User",
                "password": "long-enough-password",
            },
        )
    ).status_code == 403
    monkeypatch.setenv("SOMAS_PROXY_SECRET", "s" * 32)
    assert (await client.get("/api/auth/me")).status_code == 403
    assert (
        await client.get("/api/auth/me", headers={"X-Somas-Proxy-Secret": "s" * 32})
    ).status_code == 200


async def test_durable_throttle_survives_restart(client):
    for _ in range(2):
        await auth.throttle("test", "identity", 2)
    await store.close_db()
    await store.init_db()
    with pytest.raises(Exception) as failure:
        await auth.throttle("test", "identity", 2)
    assert failure.value.status_code == 429


async def test_auto_mode_never_calls_paid_provider(client, retail, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")

    def forbidden(*args):
        raise AssertionError("Unexpected paid request")

    monkeypatch.setattr(engine, "_openai_text", forbidden)
    response = await client.post("/api/organizations", json={**retail, "mode": "auto"})
    assert response.status_code == 201
    assert response.json()["plan"]["planning_mode"] == "demo"


async def test_manager_departments_agent_management_and_record_isolation(
    client, retail
):
    org = (await client.post("/api/organizations", json=retail)).json()
    oid = org["id"]
    aid = org["plan"]["agents"][0]["id"]
    assert (await client.get("/api/manager")).json()["owner_id"] == client.test_user_id
    assert len(
        (await client.get(f"/api/organizations/{oid}/departments")).json()
    ) == len(org["plan"]["agents"])
    assert (await client.get(f"/api/organizations/{oid}/memberships")).json()[0][
        "role"
    ] == "owner"
    response = await client.patch(
        f"/api/organizations/{oid}/agents/{aid}",
        json={"task": "Analyze evidence and verify acceptance criteria"},
    )
    assert response.status_code == 200
    await client.post(f"/api/organizations/{oid}/run", json={"mode": "demo"})
    assert await count(Conversation, Conversation.user_id == client.test_user_id) > 0
    assert await count(Decision, Decision.user_id == client.test_user_id) > 1
    assert (
        await client.get(f"/api/organizations/{oid}/conversations")
    ).status_code == 200
    from tests.test_accounts import signup
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as other:
        await signup(other, "outsider@example.com", "Outsider")
        for path in (
            "conversations",
            "decisions",
            "departments",
            "memberships",
            "relationships",
            "feedback",
            f"agents/{aid}",
        ):
            assert (
                await other.get(f"/api/organizations/{oid}/{path}")
            ).status_code == 404
        assert (
            await other.patch(
                f"/api/organizations/{oid}/agents/{aid}", json={"role": "Intruder"}
            )
        ).status_code == 404


async def test_composite_foreign_key_blocks_cross_owner_insert(client, retail):
    org = (await client.post("/api/organizations", json=retail)).json()
    await store.register_user(
        "usr_other", "other@example.com", "Other", b"salt", b"hash"
    )
    with pytest.raises(IntegrityError):
        await store.insert_row(
            Feedback,
            dict(
                id="forged",
                user_id="usr_other",
                org_id=org["id"],
                created_at=store.stamp(),
                score=5,
                capabilities=[],
                notes="",
                verified=True,
                policy_version=0,
            ),
        )


async def test_alembic_upgrade_repeat_downgrade_upgrade(postgres_database):
    await store.close_db()
    config = Config("alembic.ini")
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "base")
    await asyncio.to_thread(command.upgrade, config, "head")
    await store.init_db()
    await database.ping()


async def test_missing_url_fails_without_sqlite_fallback(monkeypatch):
    await store.close_db()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await store.init_db()
