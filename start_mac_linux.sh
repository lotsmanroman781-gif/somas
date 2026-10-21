#!/bin/sh
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -r requirements.txt
: "${DATABASE_URL:?Set DATABASE_URL for PostgreSQL; see README.md}"
python -m alembic upgrade head
echo "SOMAS v1.2 backend: http://127.0.0.1:8000 - use npm run dev for the Pages proxy."
python run.py
