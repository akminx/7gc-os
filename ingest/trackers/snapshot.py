"""Reconcile the real workbooks and write the result down.

The reconciler's tests are mostly synthetic, because CI has no workbooks. That
is necessary and it is not sufficient: a synthetic fixture proves a rule fires,
and only the real data proves what the fund's actual books produce. Four review
rounds changed that output — from 11 findings to 34 and back down again — and
every one of those changes was invisible in a diff.

So the real output is generated, committed, and compared, exactly as
`evals/oracle/derived.json` is. The raw `.xlsx` stay out of the repository; the
figures derived from them are already committed practice here (see
`evals/oracle/primitives.yaml`).

    python -m ingest.trackers.snapshot          # regenerate
    python -m ingest.trackers.snapshot --check  # fail if it has drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from ingest.trackers.read import read_master_breakdown, read_valuation_tracker
from ingest.trackers.reconcile import reconcile

ROOT = Path(__file__).resolve().parent.parent.parent
TRACKERS = ROOT / "7GC Audit Case Study/01_Internal Trackers"
VALUATION = TRACKERS / "Funds I & II - Valuation Tracker (Case Study).xlsx"
MASTER = TRACKERS / "Master Investment Breakdown - Funds I & II (Case Study).xlsx"
SNAPSHOT = ROOT / "ingest/trackers/real_findings.json"


def workbooks_present() -> bool:
    return VALUATION.exists() and MASTER.exists()


def build() -> dict[str, object]:
    sheets = read_valuation_tracker(VALUATION)
    tranches = read_master_breakdown(MASTER)
    findings = reconcile(sheets, tranches)
    return {
        "positions": sum(len(s.companies) for s in sheets),
        "tranches": len(tranches),
        "fund_periods": sum(len(s.period_labels) for s in sheets),
        "finding_count": len(findings),
        # SPEC 2: only the six packet-scope periods reach the auditor packet.
        # A count that mixes them overstates what the audit letter asked about.
        "packet_scope_findings": sum(1 for f in findings if f.scope == "packet"),
        "lineage_only_findings": sum(1 for f in findings if f.scope == "lineage_only"),
        "by_kind": {
            k: sum(1 for f in findings if f.kind.value == k)
            for k in sorted({f.kind.value for f in findings})
        },
        "findings": [
            {
                "kind": f.kind.value,
                "subject": f.subject,
                "scope": f.scope,
                # str() rather than float: INV-11, a float amount is wrong
                # before anyone reads it. Normalised so 2000000.0 and 2000000
                # cannot show up as a spurious diff.
                "stated": _num(f.stated),
                "computed": _num(f.computed),
                "detail": f.detail,
            }
            for f in findings
        ],
    }


def _num(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalised = value.normalize()
    # normalize() renders large integers in exponent form (2E+6); quantize back.
    if normalised == normalised.to_integral_value():
        normalised = normalised.to_integral_value()
    return f"{normalised:f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if the snapshot has drifted")
    args = ap.parse_args()

    if not workbooks_present():
        print("case-study workbooks are not present — nothing to do")
        return 0

    fresh = json.dumps(build(), indent=2) + "\n"
    if not args.check:
        SNAPSHOT.write_text(fresh)
        print(f"wrote {SNAPSHOT.relative_to(ROOT)}")
        return 0

    if not SNAPSHOT.exists():
        print(f"✗ {SNAPSHOT.relative_to(ROOT)} does not exist — run without --check")
        return 1
    if SNAPSHOT.read_text() != fresh:
        print(
            f"✗ {SNAPSHOT.relative_to(ROOT)} is stale.\n"
            "  The findings the real workbooks produce have changed. That may be a fix\n"
            "  or a regression — look at the diff and decide, then regenerate:\n"
            "      .venv/bin/python -m ingest.trackers.snapshot"
        )
        return 1
    print("✓ real-data findings match the committed snapshot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
