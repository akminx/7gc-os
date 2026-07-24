#!/usr/bin/env python3
"""Shared harness for the anchor suites: assertion helper and fixtures.

These expectations were computed by hand from the source documents. They do NOT
call derive.py's predicates to produce an expected value — that would be the
"second implementation agreeing for the wrong reasons" failure the diagnosis
review warned about. Every number here is written literally.

Run:  .venv/bin/python evals/oracle/anchors.py
"""

from __future__ import annotations

from pathlib import Path

from derive import Oracle
from model import OracleError
from model import fmt as fmt_

HERE = Path(__file__).parent
FAILURES: list[str] = []


SYNTH_BASE = {
    "meta": {
        "corpus": "synthetic",
        "positions": 1,
        "physical_source_files": 1,
        "evidence_records": 1,
    },
    "periods": [{"id": "p1", "fund": "f", "date": "2025-12-31", "audit_scope": "packet"}],
    "holdings": {"h": {"fund": "f", "position_type": "direct_equity"}},
    "lots": [
        {
            "id": "l1",
            "holding": "h",
            "security_class": "sa",
            "shares": 100,
            "entry_pps": "10.00",
            "cost": "1000",
            "acquired": "2025-01-01",
            "realized": None,
        }
    ],
    "mark_observations": {"h": {"p1": "1000"}},
    "tracker_totals": {"f": {"p1": "1000"}},
    "documents": {
        "d1": {
            "holding": "h",
            "claim": "h/price",
            "source_class": "executed_transaction_doc",
            "execution_status": "executed",
            "date": "2025-06-01",
            "applicable_from": "2025-06-01",
            "applicable_to": None,
            "priced_class": "sa",
            "pps": "10.00",
        }
    },
    "document_gaps": [],
    "evidence_links": [
        {"holding": "h", "requirement": "R1", "document": "d1"},
        {"holding": "h", "requirement": "R2", "document": "d1"},
    ],
    "support_observations": {"h": [{"component": "valuation", "dates": ["2025-06-01"]}]},
    "management_assessments": [],
    "valuation_policy_decisions": [],
    "valuation_approvals": [],
    "policy_matrix": [
        {
            "req": "R1",
            "source_class": "executed_transaction_doc",
            "execution_status": "executed",
            "position_type": "direct_equity",
            "verdict": "sufficient",
        },
        {
            "req": "R2",
            "source_class": "executed_transaction_doc",
            "execution_status": "executed",
            "position_type": "direct_equity",
            "verdict": "sufficient",
        },
        {
            "req": "R4",
            "source_class": "executed_transaction_doc",
            "execution_status": "executed",
            "position_type": "direct_equity",
            "verdict": "sufficient",
        },
    ],
    "gap_verdicts": {
        "with_counsel": {"verdict": "partial", "next_action": "A"},
        "referenced_location_unspecified": {"verdict": "insufficient", "next_action": "B"},
        "not_located": {"verdict": "missing", "next_action": "C"},
        "none": {"verdict": "missing", "next_action": "C"},
    },
}


def synth(**over):
    import copy as _c

    base = _c.deepcopy(SYNTH_BASE)
    for k, v in over.items():
        base[k] = v
    # Keep the synthetic manifest self-consistent; the declared-count guard is
    # for the real corpus, not for scenarios built on the fly.
    for name, doc in base["documents"].items():
        doc.setdefault("source_file", f"{name}.pdf")
    base["meta"]["evidence_records"] = len(base["documents"])
    base["meta"]["physical_source_files"] = len(
        {d["source_file"] for d in base["documents"].values()}
    )
    base["meta"]["positions"] = len(base["holdings"])
    base["meta"]["lot_count"] = len(base["lots"])
    base["meta"]["packet_periods"] = sum(1 for x in base["periods"] if x["audit_scope"] == "packet")
    return Oracle.from_dict(base)


def check(label: str, actual, expected) -> None:
    if actual == expected:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}\n          expected: {expected!r}\n          actual:   {actual!r}")
        FAILURES.append(label)


def totals(snap, fund, iso):
    return next(t for t in snap["totals"] if t["fund"] == fund and t["date"] == iso)


def row(snap, holding, iso):
    return next(r for r in snap["rows"] if r["holding"] == holding and r["date"] == iso)


__all__ = [
    "Oracle",
    "OracleError",
    "fmt_",
    "SYNTH_BASE",
    "synth",
    "check",
    "totals",
    "row",
    "FAILURES",
]
