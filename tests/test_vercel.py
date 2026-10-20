"""Exercise native ASGI cold/warm lifecycles without external cloud services."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app import database, store
from app.main import app


async def test_vercel_pooler_requirements(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    for uri in (
        "postgresql://user@ep-example.us-east-2.aws.neon.tech/db?sslmode=require",
        "postgresql://user@untrusted.example/db?sslmode=require",
        "postgresql://user@ep-example-pooler.us-east-2.aws.neon.tech/db",
    ):
        with pytest.raises(RuntimeError):
            database.make_engine(uri)
    engine = database.make_engine(
        "postgresql://user@ep-example-pooler.us-east-2.aws.neon.tech/db?sslmode=require"
    )
    assert isinstance(engine.pool, NullPool)
    await engine.dispose()


async def test_vercel_cold_warm_restart_persistence(monkeypatch, retail):
    await database.close_db()
    monkeypatch.setenv("VERCEL", "1")
    secret = "test-only-vercel-gateway-secret-32-characters"
    monkeypatch.setenv("SOMAS_PROXY_SECRET", secret)
    monkeypatch.setenv("SOMAS_ALLOWED_ORIGINS", "https://pages.test")
    headers = {"Origin": "https://pages.test", "X-Somas-Proxy-Secret": secret}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://pages.test", headers=headers
    ) as client:
        async with app.router.lifespan_context(app):
            assert isinstance(database.engine.pool, NullPool)
            warm_engine = database.engine
            response = await client.post(
                "/api/auth/register",
                json={
                    "email": "serverless@example.com",
                    "display_name": "Serverless",
                    "password": "correct-serverless-password-01",
                },
            )
            assert response.status_code == 201, response.text
            cookie = response.headers["set-cookie"].lower()
            assert all(
                value in cookie
                for value in ("httponly", "secure", "samesite=strict", "path=/")
            )
            assert "domain=" not in cookie
            user_id = response.json()["user"]["id"]
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
            response = await client.post("/api/organizations", json=retail)
            assert response.status_code == 201, response.text
            org = response.json()
            agent = org["plan"]["agents"][0]["id"]
            assert (
                await client.post(
                    f"/api/organizations/{org['id']}/run", json={"mode": "demo"}
                )
            ).status_code == 200
            for suffix, correction in (
                (
                    "feedback",
                    {"score": 5, "verified": True, "correct_capabilities": ["quality"]},
                ),
                (
                    f"agents/{agent}/feedback",
                    {"verified": True, "corrected_strategy": "verify"},
                ),
            ):
                result = await client.post(
                    f"/api/organizations/{org['id']}/{suffix}", json=correction
                )
                assert result.status_code == 200, result.text
                assert result.json()["policy_version"] == 1
            weights = (await store.load_policy(user_id, agent, "worker")).w2.copy()
            assert database.engine is warm_engine
            assert (await client.get("/readyz")).status_code == 200
            assert (await client.get("/healthz")).json()["version"] == "1.3.0"
            # An HTTP completion includes all writes; no deferred background persistence.
        assert database.engine is None
        async with app.router.lifespan_context(app):
            assert database.engine is not warm_engine
            assert (await client.get("/api/auth/me")).status_code == 200
            assert (await client.get(f"/api/organizations/{org['id']}/runs")).json()
            assert (await client.get("/api/manager")).status_code == 200
            assert (await client.get("/api/status")).json()[
                "manager_policy_version"
            ] == 1
            restored = await store.load_policy(user_id, agent, "worker")
            assert restored.version == 1 and np.array_equal(restored.w2, weights)
            csrf = client.headers.pop("X-CSRF-Token")
            assert (
                await client.post(
                    f"/api/organizations/{org['id']}/run", json={"mode": "demo"}
                )
            ).status_code == 403
            client.headers["X-CSRF-Token"] = csrf
            assert (await client.post("/api/auth/logout")).status_code == 200
            assert (await client.get("/api/auth/me")).status_code == 401


async def test_vercel_schema_validation_never_migrates(monkeypatch):
    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE alembic_version SET version_num = 'unknown_revision'")
        )
    await database.close_db()
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv(
        "SOMAS_PROXY_SECRET", "test-only-vercel-gateway-secret-32-characters"
    )
    monkeypatch.setenv("SOMAS_ALLOWED_ORIGINS", "https://pages.test")
    with pytest.raises(RuntimeError, match="schema is out of date"):
        async with app.router.lifespan_context(app):
            pytest.fail("An unknown schema must not serve requests")
    assert database.engine is None
    engine = database.make_engine()
    try:
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "unknown_revision"
            )
    finally:
        await engine.dispose()


async def test_native_bundle_import_without_frontend(tmp_path):
    shutil.copytree(
        "app", tmp_path / "app", ignore=shutil.ignore_patterns("__pycache__")
    )
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import numpy as np
from app.main import app
from app import database
from app.neural import TinyPolicy
assert app.version == '1.3.0'
assert database.engine is None  # imports neither connect nor migrate
assert TinyPolicy(['a', 'b']).serialize()
assert np.isfinite(np.tanh(np.array([1.0]))).all()
assert not any(getattr(route, 'path', '') == '/static' for route in app.routes)
print('Native FastAPI and NumPy import passed without frontend or migration files')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(tmp_path)],
        cwd=tmp_path,
        env=dict(os.environ, VERCEL="1"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def test_vercel_configuration_and_manual_migration_gate():
    config = json.loads(Path("vercel.json").read_text())
    assert config["framework"] == "fastapi"
    assert set(config["functions"]) == {"app/main.py"}
    assert config["functions"]["app/main.py"]["maxDuration"] == 180
    assert not {"buildCommand", "installCommand", "builds", "routes"} & config.keys()
    assert Path(".python-version").read_text().strip() == "3.12"
    workflow = Path(".github/workflows/migrate-database.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert all(
        trigger not in workflow
        for trigger in ("pull_request:", "pull_request_target:", "push:", "schedule:")
    )
    assert "github.ref == 'refs/heads/main'" in workflow
    assert 'test "$REVIEWED_COMMIT" = "$GITHUB_SHA"' in workflow
    assert "vars.SOMAS_MIGRATIONS_ENABLED == 'true'" in workflow
    assert workflow.count("secrets.NEON_MIGRATION_DATABASE_URL") == 1
    assert "cancel-in-progress: false" in workflow
