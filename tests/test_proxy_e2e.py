import asyncio
import os
import shutil
import subprocess
import sys

import httpx
import pytest


async def test_live_proxy_roundtrip(postgres_database):
    node = os.getenv("SOMAS_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for live proxy roundtrip")
    secret = "local-integration-secret-32-characters"
    # The disposable database belongs to this test's fixture, never Neon.
    env = dict(
        os.environ,
        SOMAS_PROXY_SECRET=secret,
        SOMAS_SECURE_COOKIES="1",
        SOMAS_ALLOWED_ORIGINS="https://somas.test",
        SOMAS_PORT="18081",
    )
    backend = subprocess.Popen(
        [
            sys.executable,
            "run.py",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            for _ in range(100):
                if backend.poll() is not None:
                    pytest.fail(
                        "Local backend startup failed: " + backend.stderr.read()
                    )
                try:
                    if (
                        await client.get("http://127.0.0.1:18081/readyz")
                    ).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.2)
            else:
                pytest.fail("Local backend did not become ready")
        result = await asyncio.to_thread(
            subprocess.run,
            [node, "--test", "tests/proxy.test.js"],
            env=dict(
                env, SOMAS_E2E_BACKEND="http://127.0.0.1:18081", SOMAS_E2E_SECRET=secret
            ),
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        backend.terminate()
        await asyncio.to_thread(backend.wait, timeout=10)
        backend.stderr.close()
