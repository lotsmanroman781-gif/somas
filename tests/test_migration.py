import json
import sqlite3

import pytest

from app import store, database
from app.models import User
from sqlalchemy import update
from app.neural import manager_policy
from app.neural import worker_policy
from app import auth
from app.models import Policy, Session
from datetime import datetime, timedelta, timezone
import hashlib
import asyncio
import os
import subprocess
import sys
from scripts.migrate_sqlite_to_postgresql import import_documents, read_source


def legacy_file(path, unowned=False):
    with sqlite3.connect(path) as c:
        if unowned:
            c.execute("CREATE TABLE orgs(id TEXT)")
            return
        c.executescript("""
            CREATE TABLE users(id,email,display_name,password_salt,password_hash,created_at);
            CREATE TABLE sessions(token_hash,user_id,csrf,created_at,expires_at);
            CREATE TABLE policies(user_id,id,version,blob);
            CREATE TABLE orgs(id,user_id,created_at,business,plan,status);
            CREATE TABLE agents(id,user_id,org_id,capability,role,created_at);
            CREATE TABLE runs(id,user_id,org_id,created_at,mode,status,outputs);
            CREATE TABLE feedback(id,user_id,org_id,created_at,score,capabilities,notes,verified,policy_version);
            CREATE TABLE events(id,user_id,at,kind,ref_id,payload);
        """)
        now = "2026-10-20T12:00:00+00:00"
        c.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,?)",
            ("usr_legacy", "alice@example.com", "Alice", b"salt", b"hash", now),
        )
        c.execute(
            "INSERT INTO policies VALUES(?,?,?,?)",
            ("usr_legacy", "root_manager", 0, manager_policy().serialize()),
        )
        c.execute(
            "INSERT INTO orgs VALUES(?,?,?,?,?,?)",
            (
                "org_legacy",
                "usr_legacy",
                now,
                json.dumps({"name": "Legacy"}),
                json.dumps({"agents": []}),
                "planned",
            ),
        )


async def test_migration_dry_read_idempotent_apply_verify_and_conflict(
    tmp_path, postgres_database
):
    source = tmp_path / "owned.db"
    legacy_file(source)
    documents = read_source(source)
    assert await store.fetch_one(User, User.id == "usr_legacy") is None

    await import_documents(documents, apply=True)
    await import_documents(documents, apply=True)
    await import_documents(documents)
    assert (await store.fetch_one(User, User.id == "usr_legacy"))[
        "display_name"
    ] == "Alice"
    async with database.scope() as session:
        await session.execute(
            update(User).where(User.id == "usr_legacy").values(display_name="Changed")
        )
    with pytest.raises(ValueError, match="conflicting"):
        await import_documents(documents, apply=True)


async def test_migration_cli_dry_run_apply_verify_and_repeat(tmp_path):
    source = tmp_path / "cli-source.db"
    legacy_file(source)
    for flag in ("--dry-run", "--apply", "--verify", "--apply"):
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "scripts/migrate_sqlite_to_postgresql.py",
                str(source),
                flag,
            ],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if flag == "--dry-run":
            assert await store.fetch_one(User, User.id == "usr_legacy") is None
    upgraded = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert upgraded.returncode == 0, "Standalone Alembic command failed"


async def test_migration_rejects_unowned_source(tmp_path):
    source = tmp_path / "unowned.db"
    legacy_file(source, unowned=True)
    with pytest.raises(ValueError, match="Unowned"):
        read_source(source)


async def test_import_preserves_login_sessions_agent_weights_and_owner(tmp_path):
    source = tmp_path / "complete.db"
    legacy_file(source)
    password = "legacy-password-for-tests"
    salt = b"legacy-test-salt"
    worker = worker_policy()
    worker.fit([[0.0] * 140], [[1, 0, 0, 0, 0, 0]], epochs=2)
    blob = worker.serialize()
    agent = {
        "id": "agent_legacy",
        "capability": "research",
        "role": "Researcher",
        "team": "Evidence",
        "task": "Research market evidence",
        "reports_to": "root_manager",
    }
    with sqlite3.connect(source) as c:
        c.execute(
            "UPDATE users SET password_salt=?,password_hash=?",
            (salt, auth.hash_password(password, salt)),
        )
        c.execute(
            "UPDATE orgs SET plan=?",
            (
                json.dumps(
                    {
                        "agents": [agent],
                        "relationships": [
                            {
                                "source": "root_manager",
                                "target": "agent_legacy",
                                "type": "reports_to",
                            }
                        ],
                    }
                ),
            ),
        )
        c.execute(
            "INSERT INTO agents VALUES(?,?,?,?,?,?)",
            (
                "agent_legacy",
                "usr_legacy",
                "org_legacy",
                "research",
                "Researcher",
                "2026-10-20T12:00:00+00:00",
            ),
        )
        c.execute(
            "INSERT INTO policies VALUES(?,?,?,?)",
            ("usr_legacy", "agent_legacy", 1, blob),
        )
        c.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?)",
            (
                hashlib.sha256(b"legacy-token").hexdigest(),
                "usr_legacy",
                "legacy-csrf",
                "2026-10-20T12:00:00+00:00",
                (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            ),
        )
    original = source.read_bytes()
    documents = read_source(source)
    await import_documents(documents, apply=True)
    await import_documents(documents, apply=True)
    await import_documents(documents)
    assert source.read_bytes() == original
    assert (await auth.verify_credentials("alice@example.com", password))[
        "id"
    ] == "usr_legacy"
    assert (await auth.session_for("legacy-token"))["csrf"] == "legacy-csrf"
    restored = await store.load_policy("usr_legacy", "agent_legacy", "worker")
    assert restored.version == 1
    row = await store.fetch_one(
        Policy, Policy.user_id == "usr_legacy", Policy.policy_id == "agent_legacy"
    )
    assert row["blob"] == blob
    assert await store.get_org("other-user", "org_legacy") is None
    assert await store.fetch_one(Session, Session.user_id == "usr_legacy") is not None


async def test_import_rejects_forged_ownership_before_writing(tmp_path):
    source = tmp_path / "forged.db"
    legacy_file(source)
    with sqlite3.connect(source) as c:
        c.execute(
            "INSERT INTO agents VALUES(?,?,?,?,?,?)",
            (
                "agent_bad",
                "foreign-user",
                "org_legacy",
                "research",
                "Researcher",
                "2026-10-20T12:00:00+00:00",
            ),
        )
    with pytest.raises(ValueError, match="owner"):
        read_source(source)
    assert await store.fetch_one(User, User.id == "usr_legacy") is None
