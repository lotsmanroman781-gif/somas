"""Exercise the real local Pages Functions runtime, not just a mocked fetch."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest


async def test_pages_runtime_cookie_roundtrip(postgres_database, tmp_path):
    if os.getenv("SOMAS_TEST_PAGES_RUNTIME") != "1":
        pytest.skip(
            "Set SOMAS_TEST_PAGES_RUNTIME=1 to run the real Wrangler runtime check"
        )
    node = os.getenv("SOMAS_NODE") or shutil.which("node")
    wrangler = Path("node_modules/wrangler/bin/wrangler.js").resolve()
    assert node and wrangler.is_file(), (
        "Run npm ci and install Node 22 for Pages runtime tests"
    )
    secret = "pages-runtime-test-secret-with-32-characters"
    origin = "http://127.0.0.1:18788"
    env = dict(
        os.environ,
        SOMAS_PROXY_SECRET=secret,
        SOMAS_SECURE_COOKIES="0",
        SOMAS_PORT="18082",
        SOMAS_ALLOWED_ORIGINS=origin,
        WRANGLER_SEND_METRICS="false",
        WRANGLER_LOG_PATH=str(tmp_path / "wrangler-logs"),
        CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV="false",
    )
    processes = []
    with (tmp_path / "local-runtime.log").open(
        "w+", encoding="utf8", errors="replace"
    ) as log:
        try:
            processes.append(
                subprocess.Popen(
                    [sys.executable, "run.py"], env=env, stdout=log, stderr=log
                )
            )
            processes.append(
                subprocess.Popen(
                    [
                        node,
                        str(wrangler),
                        "pages",
                        "dev",
                        "frontend",
                        "--ip",
                        "127.0.0.1",
                        "--port",
                        "18788",
                        "--inspector-port",
                        "0",
                        "--compatibility-date",
                        "2026-10-20",
                        "--binding",
                        "RENDER_BACKEND_ORIGIN=http://127.0.0.1:18082",
                        "--binding",
                        "ALLOW_LOCAL_BACKEND=1",
                        "--binding",
                        "SOMAS_PROXY_SECRET=" + secret,
                    ],
                    env=env,
                    stdout=log,
                    stderr=log,
                )
            )
            async with httpx.AsyncClient(
                base_url=origin, headers={"Origin": origin}, trust_env=False, timeout=2
            ) as client:
                for _ in range(150):
                    if any(p.poll() is not None for p in processes):
                        log.flush()
                        log.seek(0)
                        pytest.fail("Local Pages/backend startup failed: " + log.read())
                    try:
                        response = await client.get("/api/auth/me")
                        if response.status_code == 401:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.2)
                else:
                    log.flush()
                    log.seek(0)
                    pytest.fail(
                        "Local Pages runtime did not become ready: " + log.read()
                    )
                assert (await client.get("/")).status_code == 200
                assert (
                    "javascript"
                    in (await client.get("/static/app.js")).headers["content-type"]
                )
                assert (await client.get("/static/style.css")).status_code == 200
                response = await client.post(
                    "/api/auth/register",
                    json={
                        "email": "pages@example.com",
                        "display_name": "Pages User",
                        "password": "pages-local-test-password",
                    },
                )
                assert response.status_code == 201, response.text
                assert "HttpOnly" in response.headers["set-cookie"]
                assert (await client.get("/api/auth/me")).status_code == 200
                assert (
                    await client.post(
                        "/api/auth/profile", json={"display_name": "Blocked"}
                    )
                ).status_code in (403, 405)
                assert (
                    await client.patch(
                        "/api/auth/profile", json={"display_name": "Blocked"}
                    )
                ).status_code == 403
                client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
                assert (
                    await client.patch(
                        "/api/auth/profile", json={"display_name": "Updated Pages User"}
                    )
                ).status_code == 200
                assert (await client.post("/api/auth/logout")).status_code == 200
                assert (await client.get("/api/auth/me")).status_code == 401
        finally:
            for process in reversed(processes):
                process.terminate()
                await asyncio.to_thread(process.wait, timeout=15)
