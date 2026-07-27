#!/bin/sh
# Build a local Postgres holding both schemas and load the demo into it.
# The work is in scripts/localdb.py; this exists to choose the interpreter.
set -e
ROOT="$(git rev-parse --show-toplevel)"

# The project's Python is uv-managed and lives in .venv, and this script talks
# to Postgres through psycopg. A system `python3` has none of the project's
# dependencies, so running it there fails at the import rather than doing
# something subtly different — but the same reasoning that put this guard in
# scripts/hooks/pre-commit applies here: a missing .venv is a broken
# environment, not a reason to run something else.
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "localdb: no $PY" >&2
  echo "  this project's Python is uv-managed, never a system interpreter." >&2
  echo "  create it: uv venv --python 3.13 && uv pip install -e '.[dev]'" >&2
  exit 1
fi

exec "$PY" "$ROOT/scripts/localdb.py" "$@"
