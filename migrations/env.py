"""Run PostgreSQL schema migrations using the same async psycopg driver as FastAPI."""

import asyncio
import sys
from alembic import context
from sqlalchemy import text
from app.database import database_url, make_engine
from app.models import Base


def run(connection):
    context.configure(
        connection=connection, target_metadata=Base.metadata, compare_type=True
    )
    with context.begin_transaction():
        # A deploy/restart may race another deploy; only one migrator proceeds at a time.
        connection.execute(text("SELECT pg_advisory_xact_lock(731295120)"))
        context.run_migrations()


async def online():
    engine = make_engine()
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=database_url(), target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(online())
