from app.models import Run, Feedback

"""Security regression tests: user data and trainable weights must never cross accounts."""

from httpx import AsyncClient, ASGITransport
from app import store
from app.main import app

PASSWORD = "strong-password-for-tests-99"


async def signup(client, email, name):
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "display_name": name, "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
    client.headers.update({"X-CSRF-Token": r.json()["csrf_token"]})
    return r.json()["user"]


def business(name):
    return {
        "name": name,
        "industry": "Software services",
        "goal": "Build a customer support and software QA process that reduces response time and improves customer outcomes",
        "size": "small",
        "country": "US",
        "language": "English",
        "budget_usd": 1000,
        "mode": "demo",
    }


async def test_unauthenticated_routes_require_session(tmp_path, monkeypatch):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as c:
        for route in [
            "/api/status",
            "/api/catalog",
            "/api/events",
            "/api/agents",
            "/api/organizations",
            "/api/organizations/random",
            "/api/organizations/random/export",
        ]:
            assert (await c.get(route)).status_code == 401, route
        assert (
            await c.post("/api/organizations", json=business("Fail"))
        ).status_code == 401


async def test_cross_account_isolation_all_resources_and_training(
    tmp_path, monkeypatch
):
    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as a,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as b,
    ):
        ua = await signup(a, "owner.a@example.com", "Alice")
        ub = await signup(b, "owner.b@example.com", "Bob")
        org_a = (await a.post("/api/organizations", json=business("Alice only"))).json()
        oid = org_a["id"]
        aid = org_a["plan"]["agents"][0]["id"]
        run = await a.post(f"/api/organizations/{oid}/run", json={"mode": "demo"})
        assert run.status_code == 200
        assert len((await a.get("/api/events")).json()) > 0
        assert (await b.get("/api/organizations")).json() == []
        assert (await b.get("/api/agents")).json() == []
        assert len((await a.get("/api/agents")).json()) == len(org_a["plan"]["agents"])
        assert (await b.get("/api/events")).json() == []
        assert (await b.get("/api/status")).json()["manager_policy_version"] == 0
        protected = [
            ("get", f"/api/organizations/{oid}", None),
            ("get", f"/api/organizations/{oid}/runs", None),
            ("get", f"/api/organizations/{oid}/export", None),
            ("post", f"/api/organizations/{oid}/run", {"mode": "demo"}),
            ("post", f"/api/organizations/{oid}/reorganize", {"mode": "demo"}),
            (
                "post",
                f"/api/organizations/{oid}/feedback",
                {"score": 4, "verified": True, "correct_capabilities": ["quality"]},
            ),
            (
                "post",
                f"/api/organizations/{oid}/agents/{aid}/feedback",
                {"verified": True, "corrected_strategy": "verify"},
            ),
        ]
        for method, url, payload in protected:
            res = (
                await getattr(b, method)(url, json=payload)
                if payload
                else await getattr(b, method)(url)
            )
            assert res.status_code == 404, (method, url, res.text)
        res = await a.post(
            f"/api/organizations/{oid}/feedback",
            json={"score": 5, "verified": True, "correct_capabilities": ["quality"]},
        )
        assert res.status_code == 200 and res.json()["policy_version"] == 1
        assert (await a.get("/api/status")).json()["manager_policy_version"] == 1
        assert (await b.get("/api/status")).json()["manager_policy_version"] == 0
        assert (await store.load_policy(ua["id"], "root_manager")).version == 1
        assert (await store.load_policy(ub["id"], "root_manager")).version == 0
        org_b = (await b.post("/api/organizations", json=business("Bob only"))).json()
        assert org_b["id"] != oid
        assert org_b["plan"]["agents"][0]["id"] != aid
        assert all(
            (
                row["business"]["name"] == "Bob only"
                for row in (await b.get("/api/organizations")).json()
            )
        )
        assert all(
            (
                row["business_name"] == "Bob only"
                for row in (await b.get("/api/agents")).json()
            )
        )
        assert all(
            (
                row["business"]["name"] == "Alice only"
                for row in (await a.get("/api/organizations")).json()
            )
        )
        assert (
            await b.post(
                f"/api/organizations/{org_b['id']}/agents/{aid}/feedback",
                json={"verified": True, "corrected_strategy": "verify"},
            )
        ).status_code == 404


async def test_csrf_and_session_logout(tmp_path, monkeypatch):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as c:
        user = await signup(c, "security@example.com", "Security Tester")
        assert (await c.get("/api/auth/me")).json()["user"]["id"] == user["id"]
        csrf = c.headers.pop("X-CSRF-Token")
        assert (
            await c.post("/api/organizations", json=business("blocked"))
        ).status_code == 403
        c.headers["X-CSRF-Token"] = "bad-token"
        assert (
            await c.post("/api/organizations", json=business("blocked"))
        ).status_code == 403
        c.headers["X-CSRF-Token"] = csrf
        assert (
            await c.post("/api/organizations", json=business("allowed"))
        ).status_code == 201
        assert (await c.post("/api/auth/logout")).status_code == 200
        assert (await c.get("/api/organizations")).status_code == 401


async def test_password_login_profile_and_session_revocation(tmp_path, monkeypatch):
    async with (
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as c,
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as other,
    ):
        await signup(c, "example@testmail.org", "Initial Name")
        assert (
            await c.patch("/api/auth/profile", json={"display_name": "New Name"})
        ).json()["display_name"] == "New Name"
        assert (
            await other.post(
                "/api/auth/login",
                json={"email": "example@testmail.org", "password": "wrong"},
            )
        ).status_code == 401
        token = await other.post(
            "/api/auth/login",
            json={"email": "example@testmail.org", "password": PASSWORD},
        )
        assert token.status_code == 200
        change = await c.post(
            "/api/auth/change-password",
            json={
                "old_password": PASSWORD,
                "new_password": "longer-password-after-change",
            },
        )
        assert change.status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 401
        assert (await other.get("/api/auth/me")).status_code == 401
        assert (
            await c.post(
                "/api/auth/login",
                json={"email": "example@testmail.org", "password": PASSWORD},
            )
        ).status_code == 401
        assert (
            await c.post(
                "/api/auth/login",
                json={
                    "email": "example@testmail.org",
                    "password": "longer-password-after-change",
                },
            )
        ).status_code == 200
        assert (await c.get("/api/auth/me")).json()["user"][
            "display_name"
        ] == "New Name"


async def test_duplicate_account_password_rules_and_storage_ownership(
    tmp_path, monkeypatch
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://testserver"},
    ) as c:
        await signup(c, "foo@example.com", "Foo")
        assert (
            await c.post(
                "/api/auth/register",
                json={
                    "email": "FOO@example.com",
                    "display_name": "Foo2",
                    "password": PASSWORD,
                },
            )
        ).status_code == 409
        assert (
            await c.post(
                "/api/auth/register",
                json={
                    "email": "tiny@example.com",
                    "display_name": "Tiny",
                    "password": "short",
                },
            )
        ).status_code == 422
        org = (await c.post("/api/organizations", json=business("Foo Co"))).json()
        import pytest

        with pytest.raises(KeyError):
            await store.record_run(
                "not_the_owner", "spoofed_run", org["id"], "demo", "completed", {}
            )
        assert await store.fetch_one(Run, Run.id == "spoofed_run") is None
        with pytest.raises(KeyError):
            await store.add_feedback(
                "not_the_owner", org["id"], 5, [], "forged", True, 0
            )
        assert await store.fetch_one(Feedback, Feedback.org_id == org["id"]) is None


async def test_legacy_database_refuses_implicit_account_claim(monkeypatch):
    import pytest

    monkeypatch.setenv("SOMAS_DB", "legacy.db")
    with pytest.raises(RuntimeError, match="Legacy SOMAS_DB"):
        await store.init_db()
