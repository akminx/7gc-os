#!/usr/bin/env python3
"""Build a local Postgres holding both schemas the suite needs, and load the demo.

The gate is 22 minutes against Supabase and 11 seconds against a local
Postgres, and none of the difference is the SQL: `EXPLAIN ANALYZE` on the
heaviest retrieval query reports 14.9 ms with every buffer cached, while the
same query measured from the client costs 576-953 ms. It is round trips to
us-east-1, and there are hundreds of thousands of them across 749 tests.

Two schemas, because the suite and the demo want opposite things from one
database. `public` is what the schema suites seed and roll back, so it must be
empty. `demo` holds the fund, and `tests/test_api.py` reads it at COLLECTION
time — which is why the full suite errors against a fresh local database until
this has run, and why this is the first thing to run on a new machine.

    scripts/localdb.sh                       # build both schemas, load the demo
    scripts/localdb.sh --url postgresql://…  # against a different local server

**Idempotent by rebuild.** Every run drops both schemas and builds them again
from the migration files. Locally that is about two seconds, which buys the one
property that matters here: the schema cannot drift from
`supabase/migrations/`. A local database that silently diverges from the
deployed one produces a green gate about a schema nobody runs, and the cheapest
way never to be in that state is never to carry state forward.

Applying the same files in the same order is the whole contract, so a migration
that does not apply stops the run and names itself. All eleven apply to stock
Postgres 17 — no `auth.`, no `storage.`, no roles, no RLS, no extensions.

**It refuses a non-loopback host, and there is no flag to override that.** The
first thing this does is `drop schema demo cascade`, and `.env` in this repo
points `MIGRATION_DATABASE_URL` at the deployed database that holds the fund.
One forgotten export is the whole distance between the two, so the refusal is
in the code rather than in the operator's memory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "supabase" / "migrations"
VENV_PY = ROOT / ".venv" / "bin" / "python"

#: `public` is seeded and rolled back by the suites; `demo` holds the fund. Both
#: are built from the same files, which is the only reason a test passing
#: against one says anything about the other.
LOADED_SCHEMA = "demo"
EMPTY_SCHEMA = "public"

#: In dependency order, and the order is part of the contract: documents bind to
#: holdings the tracker load writes, and the policy seed binds to claims the
#: document load writes. Each rolls back without `--commit`, deliberately, for a
#: reason its own module records — psycopg's outermost `transaction()` block
#: COMMITS on exit, so a loader without an explicit outer block writes during
#: its own dry run, and `--commit` becomes decorative.
LOADERS = ("ingest.load", "ingest.documents.load", "ingest.policy_seed")

#: A host this script is allowed to drop schemas on.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

#: Structure, read out of the catalog. Compared between the two schemas after
#: they are built: they came from the same files in the same order, so anything
#: that differs is a half-applied schema rather than a design choice.
CATALOG: tuple[tuple[str, str], ...] = (
    (
        "columns",
        "select table_name, column_name, data_type, is_nullable, column_default"
        " from information_schema.columns where table_schema = %s order by 1, 2",
    ),
    (
        "constraints",
        "select tc.table_name, tc.constraint_type, pg_get_constraintdef(c.oid)"
        " from information_schema.table_constraints tc"
        " join pg_constraint c on c.conname = tc.constraint_name"
        " join pg_namespace n on n.oid = c.connamespace and n.nspname = tc.constraint_schema"
        " where tc.table_schema = %s order by 1, 2, 3",
    ),
    (
        "triggers",
        "select event_object_table, trigger_name, action_timing, event_manipulation,"
        " action_statement from information_schema.triggers"
        " where trigger_schema = %s order by 1, 2, 3, 4",
    ),
    ("indexes", "select tablename, indexdef from pg_indexes where schemaname = %s order by 1, 2"),
    (
        "routines",
        "select routine_name, routine_definition from information_schema.routines"
        " where routine_schema = %s order by 1",
    ),
)

#: Counted after the load and asserted non-empty. The numbers themselves are NOT
#: written down here. A count transcribed into a script is a hand-maintained
#: derived value, which this project has already failed at twice, and a reload
#: changing one is exactly the legitimate event that would then read as a
#: failure. The loaders report their own totals; these are printed beside them.
CORE_TABLES = (
    "fund",
    "company",
    "holding",
    "reporting_period",
    "lot",
    "mark",
    "document_version",
    "claim",
    "extracted_fact",
    "claim_requirement",
    "document_gap",
    "valuation_component",
)

Conn = psycopg.Connection[tuple[object, ...]]


class LocalDbError(Exception):
    """The bootstrap cannot proceed, and carrying on would build the wrong database."""


def local_only(url: str) -> str:
    """The DSN, if it names a host this script may drop schemas on.

    Not a warning and not a flag. `.env` points `MIGRATION_DATABASE_URL` at the
    deployed database, `api.config.load_env()` merges it under the process
    environment, and the difference between this being safe and this being the
    worst command in the repository is one `export` that did not happen.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host not in LOOPBACK:
        raise LocalDbError(
            f"refusing to build against {host!r} — this drops and recreates both schemas,\n"
            "  and it is written for a local container only. Start one:\n"
            "    docker run -d --name pg7gc -e POSTGRES_PASSWORD=pg -e POSTGRES_DB=ledger \\\n"
            "      -p 55432:5432 postgres:17-alpine\n"
            # The password is `pg` and the host is loopback, because the line
            # above is the `docker run` that CREATES both. detect-secrets reads
            # it as basic-auth credentials, which is the right default and the
            # wrong answer here: this string is the remedy the error suggests,
            # not a credential the repository holds.
            "  then pass "
            "--url postgresql://postgres:pg@127.0.0.1:55432/ledger"  # pragma: allowlist secret
        )
    return url


def connect(url: str, schema: str | None = None, autocommit: bool = False) -> Conn:
    """A connection, carrying `prepare_threshold=None` like every other in this repo.

    Irrelevant against a local server and set anyway, because the value of that
    rule is that it holds everywhere: the connection that omits it is the one
    that meets a transaction-mode pooler.

    `search_path` arrives as a connection option rather than a statement.
    `set search_path to %s` quotes the value as a string LITERAL and silently
    selects nothing, so a schema name has to be formatted — and the identifier
    check here is what makes formatting it safe.
    """
    if schema is not None and not schema.replace("_", "").isalnum():
        raise LocalDbError(f"{schema!r} is not a plain identifier")
    return psycopg.connect(
        url,
        options=f"-c search_path={schema}" if schema else "",
        connect_timeout=10,
        prepare_threshold=None,
        autocommit=autocommit,
    )


def shown(path: Path) -> str:
    """A path as a reader would type it, and never an exception.

    `relative_to` RAISES for anything outside the tree, so using it directly in
    an error message means the failure path fails — which is what happened the
    first time this module's loud failure was reproduced, with a migration
    directory in a scratch folder. An error handler that can throw is one the
    operator meets only on the worst day.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def migration_files() -> list[Path]:
    files = sorted(MIGRATIONS.glob("*.sql"))
    if not files:
        raise LocalDbError(f"no migrations under {shown(MIGRATIONS)}")
    return files


def build(url: str, schema: str, files: list[Path]) -> None:
    """Drop the schema and apply every migration into it, loudly.

    The drop is what makes re-running safe. Applying the files rather than
    reconciling against them is what makes the result honest: this schema IS the
    migrations, not an approximation that happened to converge on them.
    """
    ident = sql.Identifier(schema)
    with connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("drop schema if exists {} cascade").format(ident))
        conn.execute(sql.SQL("create schema {}").format(ident))
    with connect(url, schema) as conn:
        for f in files:
            try:
                conn.execute(f.read_text())
            except psycopg.Error as exc:
                # The half-applied schema is left in place on purpose: it is the
                # only evidence of how far the run got, and the next run drops it
                # before doing anything, so nothing is carried forward.
                raise LocalDbError(
                    f"{shown(f)} did not apply into {schema}:\n  {exc}\n"
                    f"  {schema} is left half-applied for inspection; re-running rebuilds it."
                ) from exc
        conn.commit()
    print(f"  {schema:8} {len(files)} migrations applied")


def structure(conn: Conn, schema: str) -> dict[str, list[tuple[str, ...]]]:
    """The catalog for one schema, with its own name rubbed out.

    Postgres renders an object's schema qualifier only when that schema is not
    on the search path, so `demo` reads `demo.reject_mutation()` where `public`
    reads `reject_mutation()`. The difference is about the reader, not the
    schema, and comparing it would report a divergence on every run.
    """
    out: dict[str, list[tuple[str, ...]]] = {}
    for name, query in CATALOG:
        out[name] = [
            tuple(str(col).replace(f"{schema}.", "") for col in row)
            for row in conn.execute(query, (schema,)).fetchall()
        ]
    return out


def same_structure(url: str) -> None:
    """The two schemas must be indistinguishable. Both were built from the same files."""
    with connect(url) as conn:
        empty = structure(conn, EMPTY_SCHEMA)
        loaded = structure(conn, LOADED_SCHEMA)
    problems: list[str] = []
    for name, rows in empty.items():
        other = loaded[name]
        if rows == other:
            continue
        if len(rows) != len(other):
            problems.append(
                f"{name}: {EMPTY_SCHEMA} has {len(rows)}, {LOADED_SCHEMA} has {len(other)}"
            )
            continue
        first = next((f"{a} != {b}" for a, b in zip(rows, other, strict=True) if a != b), "")
        problems.append(f"{name}: {first}")
    if problems:
        raise LocalDbError(
            "the two schemas differ, so one of them is half-applied:\n  " + "\n  ".join(problems)
        )
    print("  structure " + ", ".join(f"{len(v)} {k}" for k, v in empty.items()) + " — both alike")


def load(url: str) -> None:
    """The three loaders, run as the commands a reader would type.

    Subprocesses rather than in-process calls, so that what this does is what
    the loaders' own docstrings document, and so a failure can be reproduced by
    copying one line out of this output.

    Both URLs are injected. Without that the loaders read `.env`, whose
    `MIGRATION_DATABASE_URL` is the deployed database — and a dry run that
    writes the fund somewhere nobody asked for is precisely the accident
    `local_only` exists to prevent.
    """
    env = {**os.environ, "MIGRATION_DATABASE_URL": url, "DATABASE_URL": url}
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    for module in LOADERS:
        argv = [py, "-m", module, "--schema", LOADED_SCHEMA, "--commit"]
        # Flushed, because the child writes straight to the same descriptor. Left
        # buffered, the parent's line lands AFTER the output it introduces, and
        # every loader appears to be reporting the previous one's work.
        print(f"\n$ .venv/bin/python {' '.join(argv[1:])}", flush=True)
        if subprocess.run(argv, cwd=ROOT, env=env, check=False).returncode != 0:
            raise LocalDbError(f"{module} failed; the schema is built but not loaded")


def count(conn: Conn, table: str) -> int:
    row = conn.execute(sql.SQL("select count(*) from {}").format(sql.Identifier(table))).fetchone()
    if row is None:
        raise LocalDbError(f"count(*) on {table} returned nothing")
    n = row[0]
    if not isinstance(n, int):
        raise LocalDbError(f"count(*) on {table} returned {n!r}")
    return n


def census(url: str) -> None:
    """Every core table, counted. Non-zero is asserted; the figures are only printed.

    The check is that each loader left something behind in the tables it is
    responsible for — which is the shape a decorative `--commit` fails, having
    reported success and written nothing.
    """
    with connect(url, LOADED_SCHEMA) as conn:
        counts = {t: count(conn, t) for t in CORE_TABLES}
    bare = [t for t, n in counts.items() if n == 0]
    if bare:
        raise LocalDbError(
            "loaded, and these tables are still empty: "
            + ", ".join(bare)
            + "\n  a loader reported success and wrote nothing."
        )
    print(f"\n{LOADED_SCHEMA} loaded:")
    for table, n in counts.items():
        print(f"  {table:22} {n}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a local Postgres with both schemas and load the demo.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="local DSN; defaults to MIGRATION_DATABASE_URL, then DATABASE_URL",
    )
    args = parser.parse_args(argv)

    url = args.url or os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "no DSN. Pass --url, or export MIGRATION_DATABASE_URL.\n"
            "  Deliberately NOT read from .env: that file names the deployed\n"
            "  database, and this script drops schemas.",
            file=sys.stderr,
        )
        return 1

    try:
        local_only(url)
        files = migration_files()
        split = urlsplit(url)
        print(f"{split.hostname}:{split.port} — rebuilding both schemas from {len(files)} files")
        for schema in (EMPTY_SCHEMA, LOADED_SCHEMA):
            build(url, schema, files)
        same_structure(url)
        load(url)
        census(url)
    except LocalDbError as exc:
        print(f"\nlocaldb: {exc}", file=sys.stderr)
        return 1

    print(
        "\nready. Point the suite at it:\n"
        f"    export MIGRATION_DATABASE_URL={url}\n"
        f"    export DATABASE_URL={url}\n"
        "    export REQUIRE_DB_TESTS=1\n"
        "    .venv/bin/python -m pytest -q"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
