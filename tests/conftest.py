import asyncio
import os
import sys
import uuid
import pytest
import pytest_asyncio
import psycopg
from psycopg import sql
from alembic.config import Config
from alembic import command
from httpx import AsyncClient, ASGITransport
from app import store, database
from app.main import app

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture(autouse=True)
async def postgres_database(request, monkeypatch):
    if (
        request.node.name
        == "test_neural_policy_is_genuinely_trainable_and_serializable"
    ):
        yield None
        return
    uri = os.getenv("SOMAS_TEST_DATABASE_URL")
    if not uri:
        pytest.skip(
            "Set SOMAS_TEST_DATABASE_URL to a disposable local PostgreSQL server"
        )
    url = database.database_url(uri)
    if url.host not in ("127.0.0.1", "localhost", "::1"):
        pytest.fail(
            "Tests require a local disposable PostgreSQL server, never live Neon"
        )
    dbname = "somas_test_" + uuid.uuid4().hex
    admin_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    connection = await psycopg.AsyncConnection.connect(admin_url, autocommit=True)
    await connection.execute(
        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
    )
    monkeypatch.setenv(
        "DATABASE_URL", url.set(database=dbname).render_as_string(hide_password=False)
    )
    monkeypatch.setenv("SOMAS_ALLOWED_ORIGINS", "http://testserver")
    monkeypatch.setenv("SOMAS_ALLOW_PUBLIC_SIGNUP", "true")
    for name in (
        "SOMAS_DB",
        "SOMAS_PROXY_SECRET",
        "SOMAS_SECURE_COOKIES",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    try:
        await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
        await store.init_db()
        yield dbname
    finally:
        await store.close_db()
        if not dbname.startswith("somas_test_"):
            raise RuntimeError("Unexpected test database")
        await connection.execute(
            sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname))
        )
        await connection.close()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as c:
        res = await c.post(
            "/api/auth/register",
            json={
                "email": "tester@example.com",
                "display_name": "Test User",
                "password": "correct-horse-battery-01",
            },
        )
        assert res.status_code == 201, res.text
        c.headers.update({"X-CSRF-Token": res.json()["csrf_token"]})
        c.test_user_id = res.json()["user"]["id"]
        yield c


@pytest.fixture
def retail():
    return {
        "name": "Test Retail",
        "industry": "E-commerce retail",
        "goal": "Reduce late shipping deliveries and customer complaints with improved inventory operations",
        "size": "small",
        "country": "United States",
        "language": "English",
        "budget_usd": 1000,
        "mode": "demo",
    }
