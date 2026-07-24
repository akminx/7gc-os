#!/usr/bin/env python3
"""Oracle derivation — computes every derived expectation from primitives.yaml.

WHY THIS EXISTS
---------------
Two fixer cycles failed because ~200 hand-maintained derived cells in
docs/ORACLE.md drifted from the predicates stated elsewhere in the same
documents. Six of six unsupported subtotals were wrong; the adversary reviewing
them hand-computed one wrong too. Hand-maintained derived cells are unreliable
regardless of who maintains them.

RULES THIS FILE MUST OBEY
-------------------------
1. Imports NOTHING from production code. If production ever imports this, the
   oracle stops being independent.
2. Consumes only the reviewed primitive manifest.
3. Emits the COMPLETE derived snapshot; committed output makes diffs reviewable.
4. Fails loudly on unknown enum values or unenumerated policy tuples.
5. Contentious judgements are inputs, not calculations.

Checked by anchors.py, which hand-works boundary cases independently.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal

from checks import ChecksMixin
from model import HERE, OracleBase, fmt, money
from policy import PolicyMixin


class Oracle(ChecksMixin, PolicyMixin, OracleBase):
    """Assembly: per-row requirement results, totals, and the snapshot."""

    def row(self, holding: str, on: date, fund: str, held_at_date: bool = True) -> dict:
        r1 = self.r1(holding, on)
        r2 = self.r2(holding, on)
        r3 = self.r3(holding, on, fund)
        r4 = self.r4(holding, on, fund)
        r5 = self.r5(holding, on, r2)
        reqs = {"R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5}
        applicable = [v["verdict"] for v in reqs.values() if v["verdict"] != "not_applicable"]
        row_verdict = self.reduce_row(applicable)
        pid = self._period_id(fund, on)
        amount = self.obs.get(holding, {}).get(pid)
        authorized = bool(
            [
                x
                for x in self.policy_decisions
                if x.get("holding") == holding and x.get("date") == on.isoformat()
            ]
        )
        val, dstatus, dreason, dlineage = self.validated_amount(
            holding, on, [(n, self.docs[n]) for n in r2.get("relied_on", [])], authorized
        )
        return {
            "holding": holding,
            "date": on.isoformat(),
            "held_at_date": held_at_date,
            "reported_amount": amount,
            "validated_amount": fmt(val) if val is not None else None,
            "derivation_status": dstatus,
            "derivation_reason": dreason,
            "derivation_lineage": dlineage,
            "validated_matches_reported": (
                None if (val is None or amount is None) else money(amount) == val
            ),
            "requirements": {k: v for k, v in reqs.items()},
            "applicable_count": len(applicable),
            "sufficient_count": sum(1 for v in applicable if v == "sufficient"),
            "row_verdict": row_verdict,
            "fully_supported": row_verdict == "sufficient",
            "tracker_label": self.tracker_labels.get(holding, {}).get(pid, []),
            # Management asserted a label the evidence does not support. The
            # reverse (derived label, no tracker note) is not a disagreement —
            # silence is not an assertion of absence.
            "unsupported_tracker_labels": sorted(
                set(self.tracker_labels.get(holding, {}).get(pid, []))
                - ({"pro_forma"} if r2.get("pro_forma") else set())
            ),
            "labels": sorted(
                (["pro_forma"] if r2.get("pro_forma") else [])
                + (["cross_class_policy"] if r2.get("cross_class") else [])
                + (["subsequent_evidence"] if r2.get("subsequent_evidence") else [])
            ),
        }

    def run(self) -> dict:
        rows, totals = [], []
        # Funds are derived, not hardcoded — a hardcoded pair silently emitted
        # zero rows for any manifest using different fund ids.
        for fund in dict.fromkeys(m["fund"] for m in self.holdings.values()):
            for pd_ in self._packet_dates(fund):
                members = self.packet_holdings(fund, pd_)
                frows = [self.row(h, pd_, fund, held) for h, held in members]
                rows.extend(frows)
                held_rows = [r for r in frows if r["held_at_date"]]
                reported = sum(
                    ((money(r["reported_amount"]) or Decimal(0)) for r in held_rows), Decimal(0)
                )
                # INV-19: an aggregate inherits status from ITS INPUTS. A
                # realised-only row is a packet gap but is not an input to the
                # held-at-date total, so it must not block approval of it.
                unsupported_rows = [r for r in held_rows if not r["fully_supported"]]
                packet_gap_rows = [r for r in frows if not r["fully_supported"]]
                unsupported = sum(
                    (
                        (money(r["reported_amount"]) or Decimal(0))
                        for r in unsupported_rows
                        if r["held_at_date"]
                    ),
                    Decimal(0),
                )
                # SPEC §6.3 binds a valuation approval to
                # (mark_revision, evidence_set_hash, policy_version). r6 matched
                # holding+date only, so a probe supplying all three fields with
                # the literal value "wrong" still produced an approved total.
                approvals = {
                    a["holding"]
                    for a in self.p.get("valuation_approvals", [])
                    if a.get("date") == pd_.isoformat()
                    and self.fingerprint_ok(a, a.get("holding"), pd_)
                }
                unapproved = [r["holding"] for r in held_rows if r["holding"] not in approvals]
                tracker_pid = self._period_id(fund, pd_)
                tracker = self.p["tracker_totals"][fund].get(tracker_pid)
                totals.append(
                    {
                        "fund": fund,
                        "date": pd_.isoformat(),
                        "positions_held": len(held_rows),
                        "held_at_date_reported_total": fmt(reported),
                        "tracker_stated_total": tracker,
                        "reconciliation_delta": fmt(reported - money(tracker)) if tracker else None,
                        "unsupported_subtotal": fmt(unsupported),
                        "unsupported_row_count": len(unsupported_rows),
                        "packet_gap_row_count": len(packet_gap_rows),
                        "approved_fair_value_total": fmt(reported)
                        if (not unsupported_rows and not unapproved)
                        else None,
                        "approved_blocked_by": (
                            "unsupported_rows"
                            if unsupported_rows
                            else ("no_valuation_approval" if unapproved else None)
                        ),
                        "unapproved_marks": sorted(unapproved),
                        "labels": ["contains_unsupported_inputs"] if unsupported_rows else [],
                    }
                )
        return {
            "entry_costs": self.entry_costs(),
            "recap_checks": self.recap_checks(),
            "concluded_value_checks": self.concluded_value_checks(),
            "realization_checks": self.realization_checks(),
            "basis_checks": self.basis_checks(),
            "change_view": self.change_view(),
            "rows": rows,
            "totals": totals,
            "r3_applicable": [
                {
                    "holding": r["holding"],
                    "date": r["date"],
                    "verdict": r["requirements"]["R3"]["verdict"],
                    "stale": r["requirements"]["R3"].get("stale_components"),
                }
                for r in rows
                if r["requirements"]["R3"]["verdict"] != "not_applicable"
            ],
        }


V_SYM = {
    "sufficient": "✓",
    "partial": "~",
    "insufficient": "✗",
    "missing": "✗",
    "not_applicable": "·",
}


def to_markdown(snap: dict) -> str:
    L = [
        "# Derived oracle snapshot",
        "",
        "**GENERATED — do not edit.** `python evals/oracle/derive.py`",
        "",
        "Every value here is computed from `primitives.yaml`. Nothing in this",
        "file was typed by hand, which is the entire point: two fixer cycles",
        "failed on hand-maintained derived cells.",
        "",
        "## Totals",
        "",
        "| Fund | Date | Held | Reported | Tracker | Delta | Unsupported | Approved FV |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for t in snap["totals"]:
        L.append(
            f"| {t['fund']} | {t['date']} | {t['positions_held']} | "
            f"{t['held_at_date_reported_total']} | {t['tracker_stated_total']} | "
            f"{t['reconciliation_delta']} | {t['unsupported_subtotal']} | "
            f"{t['approved_fair_value_total'] or 'null'} |"
        )
    L += [
        "",
        "## Per-requirement verdicts",
        "",
        "`✓` sufficient · `~` partial · `✗` missing/insufficient · `·` not applicable",
        "",
        "| Holding | Date | Reported | R1 | R2 | R3 | R4 | R5 | Row | Labels |",
        "|---|---|---:|:--:|:--:|:--:|:--:|:--:|---|---|",
    ]
    for r in sorted(snap["rows"], key=lambda x: (x["date"], x["holding"])):
        rq = r["requirements"]
        L.append(
            f"| {r['holding']} | {r['date']} | {r['reported_amount'] or '—'} | "
            + " | ".join(V_SYM[rq[k]["verdict"]] for k in ("R1", "R2", "R3", "R4", "R5"))
            + f" | {r['row_verdict']} | {', '.join(r['labels']) or '—'} |"
        )
    L += [
        "",
        "## Calibration required (R3)",
        "",
        "| Holding | Date | Stale components |",
        "|---|---|---|",
    ]
    for r in snap["r3_applicable"]:
        L.append(
            f"| {r['holding']} | {r['date']} | "
            f"{', '.join(c['component'] for c in (r['stale'] or []))} |"
        )
    L += [
        "",
        "## Entry cost",
        "",
        "| Lot | Shares | PPS | Computed | Stated | Check |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for e in snap["entry_costs"]:
        L.append(
            f"| {e['lot']} | {e.get('shares') or '—'} | {e.get('entry_pps') or '—'} | "
            f"{e.get('computed') or '—'} | {e.get('stated')} | {e['check']} |"
        )
    return "\n".join(L) + "\n"


def main() -> int:
    o = Oracle(HERE / "primitives.yaml")
    snap = o.run()
    (HERE / "derived.json").write_text(json.dumps(snap, indent=2) + "\n")
    (HERE / "derived.md").write_text(to_markdown(snap))

    fails = [e for e in snap["entry_costs"] if e["check"] == "FAIL"]
    print(f"entry-cost lots: {len(snap['entry_costs'])}  failures: {len(fails)}")
    for f in fails:
        print("  FAIL", f)
    print(f"rows: {len(snap['rows'])}   R3 applicable: {len(snap['r3_applicable'])}")
    print()
    print(
        f"{'fund':9} {'date':12} {'held':>4} {'reported':>12} {'tracker':>12} "
        f"{'delta':>10} {'unsupported':>12} {'approved':>10}"
    )
    for t in snap["totals"]:
        print(
            f"{t['fund']:9} {t['date']:12} {t['positions_held']:>4} "
            f"{t['held_at_date_reported_total']:>12} {str(t['tracker_stated_total']):>12} "
            f"{str(t['reconciliation_delta']):>10} {t['unsupported_subtotal']:>12} "
            f"{str(t['approved_fair_value_total']):>10}"
        )
    print()
    print("R3 applicable (calibration required):")
    for r in snap["r3_applicable"]:
        comps = ", ".join(c["component"] for c in (r["stale"] or []))
        print(f"  {r['holding']:16} {r['date']}  {r['verdict']:10} stale: {comps}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
