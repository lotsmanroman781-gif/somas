#!/bin/sh
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
python -m pip install -r requirements.txt
echo "SOMAS dashboard: http://127.0.0.1:8000"
python run.py
