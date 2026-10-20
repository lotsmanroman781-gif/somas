"""Async SQLAlchemy/psycopg lifecycle. Schema changes belong to Alembic."""

import os
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

engine = None
sessions = None
SCHEMA_REVISION = "0001_v12"


def database_url(value=None):
    value = value or os.getenv("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    url = make_url(value)
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise RuntimeError("Only PostgreSQL with psycopg 3 is supported")
    url = url.set(drivername="postgresql+psycopg")
    if url.host not in ("localhost", "127.0.0.1", "::1") and url.query.get(
        "sslmode"
    ) not in ("require", "verify-ca", "verify-full"):
        raise RuntimeError(
            "Remote PostgreSQL connections require TLS (sslmode=require or verify-full)"
        )
    return url


def make_engine(value=None):
    url = database_url(value)
    if os.getenv("VERCEL") == "1":
        # Each short transaction returns its connection to Neon's external pooler.
        # No idle connections or cross-event-loop connections survive a warm invocation.
        if url.host not in ("localhost", "127.0.0.1", "::1") and not (
            url.host
            and url.host.endswith(".neon.tech")
            and url.host.split(".")[0].endswith("-pooler")
        ):
            raise RuntimeError("Vercel requires the Neon pooled DATABASE_URL")
        return create_async_engine(
            url,
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"prepare_threshold": None, "connect_timeout": 10},
        )
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=2,
        pool_recycle=300,
        hide_parameters=True,
        connect_args={"prepare_threshold": None, "connect_timeout": 10},
    )


async def init_db():
    global engine, sessions
    if os.getenv("SOMAS_DB"):
        raise RuntimeError(
            "Legacy SOMAS_DB is unsupported; explicitly import owned v1.1 data"
        )
    engine = make_engine()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            if revision != SCHEMA_REVISION:
                raise RuntimeError(
                    "Database schema is out of date; run alembic upgrade head"
                )
    except Exception:
        await close_db()
        raise


async def close_db():
    global engine, sessions
    if engine is not None:
        await engine.dispose()
    engine = sessions = None


@asynccontextmanager
async def scope(session=None):
    if session is not None:
        yield session
        return
    if sessions is None:
        raise RuntimeError("Database has not been initialized")
    async with sessions.begin() as opened:
        await opened.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        await opened.execute(text("SET LOCAL statement_timeout = '15s'"))
        await opened.execute(text("SET LOCAL lock_timeout = '5s'"))
        yield opened


async def ping():
    async with scope() as session:
        await session.execute(text("SELECT 1"))
