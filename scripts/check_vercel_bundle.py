"""Audit a clean dependency staging directory, without cloud access or credentials.

Run pip install -r requirements.txt --target .vercel-check/vendor first.
This conservative uncompressed size check includes all vendor files, not dev tooling.
It is a preflight, not a substitute for Vercel's actual deployment bundle report.
"""

import os
from pathlib import Path
import subprocess
import sys


def main():
    vendor = Path(".vercel-check/vendor").resolve()
    if not (vendor / "numpy").is_dir() or not (vendor / "psycopg").is_dir():
        sys.exit("First install requirements.txt into .vercel-check/vendor")
    roots = (vendor, Path("app"))
    size = sum(
        path.stat().st_size
        for root in roots
        for path in root.rglob("*")
        if path.is_file()
    )
    print(
        f"Runtime dependencies and application: {size / (1024 * 1024):.1f} MiB uncompressed"
    )
    # Leave room for the native platform adapter and metadata below its 500 MB limit.
    if size >= 450_000_000:
        sys.exit("Bundle preflight exceeds 450 MB safety budget")
    code = """
import sys
sys.path[:0] = sys.argv[1:]
import numpy as np
import psycopg
from app.main import app
from app.neural import TinyPolicy
assert app.version == '1.3.0'
assert np.isfinite(np.tanh(np.ones(5))).all()
assert TinyPolicy(['a', 'b']).serialize()
print('Staged FastAPI, psycopg and native NumPy imports passed')
"""
    subprocess.run(
        [sys.executable, "-I", "-c", code, str(vendor), str(Path.cwd())],
        env=dict(os.environ, VERCEL="1"),
        check=True,
        timeout=30,
    )


if __name__ == "__main__":
    main()
