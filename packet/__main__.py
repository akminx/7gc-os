"""Generate auditor packets from the command line.

    .venv/bin/python -m packet --out out/packets                 # every packet period
    .venv/bin/python -m packet --fund fund_ii --out out/packets  # one fund
    .venv/bin/python -m packet --period fund_ii_25q4 --out out/packets

The output directory is gitignored. A generated packet is a build artefact of a
private corpus and does not belong in the repository.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from api import ledger
from api.config import dsn, ledger_schema
from packet.export import PacketExportError, export_packet, record

DEFAULT_OUT = Path("out/packets")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="packet", description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--fund", help="restrict to one fund id")
    parser.add_argument("--period", help="restrict to one reporting period id")
    parser.add_argument(
        "--schema",
        default=None,
        help="Postgres schema to read (defaults to LEDGER_SCHEMA, then 'public')",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="also register the packet version and its manifest in the ledger",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    url = dsn()
    if url is None:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    schema = args.schema or ledger_schema()
    # An identifier, so it is interpolated rather than parameterised — a bound
    # parameter in `search_path` is quoted as a literal and selects nothing. That
    # makes the shape of the value the only check there is, so it is checked.
    if not schema.replace("_", "").isalnum():
        print(f"{schema!r} is not a plain identifier", file=sys.stderr)
        return 2
    failures = 0
    with psycopg.connect(url, options=f"-c search_path={schema}") as conn:
        periods = [
            (fund, period)
            for fund, period, _ in ledger.packet_periods(conn)
            if (args.fund is None or fund == args.fund)
            and (args.period is None or period == args.period)
        ]
        if not periods:
            print("no packet-scope periods matched", file=sys.stderr)
            return 2
        for fund, period in periods:
            destination = args.out / period
            try:
                written = export_packet(conn, fund, period, destination)
            except PacketExportError as exc:
                failures += 1
                print(f"{period}: FAILED — {exc}", file=sys.stderr)
                continue
            if args.record:
                record(conn, written)
            print(
                f"{period}: {written.root} · {len(written.paths)} files · "
                f"manifest {written.manifest_hash[:12]}"
            )
        # A generated packet is a file on disk; registering it in the ledger is a
        # separate act the caller asked for or did not. Rolling back otherwise
        # keeps a read-only run read-only, which `with psycopg.connect(...)`
        # would not — its clean exit COMMITS.
        if args.record and not failures:
            conn.commit()
        else:
            conn.rollback()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
