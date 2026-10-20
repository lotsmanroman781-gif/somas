import asyncio
import os
import subprocess
import sys

from sqlalchemy import func, select
from app import database
from app.models import User


async def test_read_only_connection_and_schema_cli(postgres_database):
    async with database.scope() as session:
        before = await session.scalar(select(func.count()).select_from(User))
    for options in ([], ["--schema"]):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "scripts/check_database.py", *options],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "Read-only check completed" in result.stdout
        assert os.environ["DATABASE_URL"] not in result.stdout + result.stderr
    async with database.scope() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == before


async def test_connection_failure_does_not_print_uri(postgres_database):
    secret = "invalid-uri-with-sensitive-value"
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "scripts/check_database.py"],
        env=dict(os.environ, DATABASE_URL=secret),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert secret not in result.stdout + result.stderr
