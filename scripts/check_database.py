"""Verify DATABASE_URL without writing data or printing connection details."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.database import SCHEMA_REVISION, make_engine


async def check(check_schema=False):
    engine = make_engine()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await connection.execute(text("SELECT 1"))
            if check_schema:
                table = await connection.scalar(
                    text("SELECT to_regclass('alembic_version')")
                )
                if not table:
                    print(
                        "Connection OK. Schema is not initialized; run python -m alembic upgrade head."
                    )
                    return 1
                revision = await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                if revision != SCHEMA_REVISION:
                    print(
                        "Connection OK. Schema revision does not match this application."
                    )
                    return 1
                print(
                    "Connection OK. Schema revision: "
                    + SCHEMA_REVISION
                    + ". Read-only check completed."
                )
            else:
                print("Database connection OK. Read-only check completed.")
        return 0
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema", action="store_true", help="Also check the Alembic revision"
    )
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(check(args.schema))
    except Exception:
        print(
            "Database check failed. Check DATABASE_URL, TLS, network access, and database availability. No connection details were printed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
