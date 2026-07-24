"""Oracle core — manifest loading, integrity validation, and lot/period logic.

Split out of derive.py when the gate's 600-line file-size limit caught it. The
split is by responsibility, not by line count: this module owns WHAT IS, the
policy module owns WHAT IT MEANS, and derive.py owns assembly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Self

import yaml

HERE = Path(__file__).parent
VERDICT_ORDER = ["missing", "insufficient", "partial", "sufficient"]
CONFLICTING = "conflicting"  # dominates; outside the severity scale
WINDOWED_REQUIREMENTS = {"R2"}  # existence/cost documents do not expire (INV-5)


class OracleError(Exception):
    """Raised on any unenumerated case. Fail closed, never default."""


def d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def money(s: str | None) -> Decimal | None:
    return Decimal(s) if s is not None else None


def fmt(x: Decimal) -> str:
    """Stable money rendering so committed JSON diffs stay readable.

    Decimal preserves operand scale, so 60000 * Decimal("40.00") renders as
    "2400000.00" while a literal renders as "2400000". Both are equal as
    Decimals — every comparison in this file is Decimal-based — but the string
    difference would churn the committed snapshot. Quantise to cents, then drop
    a zero fractional part. This corpus is whole dollars throughout.
    """
    q = x.quantize(Decimal("0.01"))
    return str(q.to_integral_value()) if q == q.to_integral_value() else str(q)


def minus_months(anchor: date, months: int) -> date:
    """Anchor shifted back N calendar months, clamping the day if needed."""
    y, m = anchor.year, anchor.month - months
    while m <= 0:
        m += 12
        y -= 1
    day = anchor.day
    while day > 0:
        try:
            return date(y, m, day)
        except ValueError:
            day -= 1
    raise OracleError("unreachable date arithmetic")


def worst(verdicts: list[str]) -> str:
    return min(verdicts, key=VERDICT_ORDER.index)


def best(verdicts: list[str]) -> str:
    return max(verdicts, key=VERDICT_ORDER.index)


class OracleBase:
    @classmethod
    def from_dict(cls, data: dict) -> Self:
        """Build from an in-memory manifest. Used by anchors to reach branches the
        fixed corpus cannot exercise (positive approval, multi-lot realisation,
        scoped decisions, contradictions)."""
        o = cls.__new__(cls)
        o._load(data)
        return o

    def __init__(self, path: Path):
        self._load(yaml.safe_load(path.read_text()))

    def _load(self, data: dict) -> None:
        self.p = data
        self.periods = {x["id"]: x for x in self.p["periods"]}
        self.holdings = self.p["holdings"]
        self.lots = self.p["lots"]
        self.docs = self.p["documents"]
        self.gaps = self.p["document_gaps"]
        self.links = self.p["evidence_links"]
        self.matrix = self.p["policy_matrix"]
        self.gap_verdicts = self.p["gap_verdicts"]
        self.obs = self.p["mark_observations"]
        self.support = self.p["support_observations"]
        self.assessments = self.p["management_assessments"]
        self.policy_decisions = self.p["valuation_policy_decisions"]
        self.tracker_labels = self.p.get("tracker_labels", {})
        self._validate()

    # ---------- integrity ----------

    def _validate(self) -> None:
        for lot in self.lots:
            if lot["holding"] not in self.holdings:
                raise OracleError(f"lot {lot['id']} references unknown holding")
        for doc in self.docs.values():
            if doc["holding"] not in self.holdings:
                raise OracleError("document references unknown holding")
        for link in self.links:
            if link["document"] not in self.docs:
                raise OracleError(f"link references unknown document {link['document']}")
        for h in self.obs:
            if h not in self.holdings:
                raise OracleError(f"mark observation for unknown holding {h}")
        missing = set(self.holdings) - {x["holding"] for x in self.lots}
        if missing:
            raise OracleError(f"holdings without lots: {missing}")

        # Omissions previously failed OPEN: a holding absent from
        # support_observations returned "all components have support" and R3
        # silently never fired.
        if len(self.docs) != self.p["meta"]["evidence_records"]:
            raise OracleError(
                f"meta.evidence_records={self.p['meta']['evidence_records']} but "
                f"{len(self.docs)} document records exist"
            )
        m = self.p["meta"]
        checks = {
            "physical_source_files": len({doc["source_file"] for doc in self.docs.values()}),
            "positions": len(self.holdings),
            "lot_count": len(self.lots),
            "packet_periods": sum(1 for x in self.periods.values() if x["audit_scope"] == "packet"),
        }
        for key, actual in checks.items():
            if key in m and m[key] != actual:
                raise OracleError(f"meta.{key}={m[key]} but {actual} found")
        for name, doc in self.docs.items():
            if "source_file" not in doc:
                raise OracleError(
                    f"{name} has no source_file — every claim must bind to a physical artifact"
                )

        no_support = set(self.holdings) - set(self.support)
        if no_support:
            raise OracleError(
                f"holdings without support_observations: {no_support}. Record an "
                f"explicit empty dates list where absence is intentional."
            )

        seen = set()
        for r in self.matrix:
            key = (r["req"], r["source_class"], r["execution_status"], r["position_type"])
            if key in seen:
                raise OracleError(f"duplicate policy_matrix cell: {key}")
            seen.add(key)
            if r["verdict"] not in VERDICT_ORDER:
                raise OracleError(f"unknown verdict {r['verdict']!r} in policy_matrix")
        for g in self.gap_verdicts.values():
            if g["verdict"] not in VERDICT_ORDER:
                raise OracleError(f"unknown verdict {g['verdict']!r} in gap_verdicts")

        # Every held holding must have a mark at every packet date.
        for fund in {m["fund"] for m in self.holdings.values()}:
            for pd_ in self._packet_dates(fund):
                pid = self._period_id(fund, pd_)
                for h in self.held_holdings(fund, pd_):
                    if pid not in self.obs.get(h, {}):
                        raise OracleError(
                            f"{h} is held at {pd_} but has no mark observation — "
                            f"a missing mark must not be summed as zero (SPEC V3 "
                            f"blocked_incomplete)."
                        )

    # ---------- lots ----------

    def class_at(self, lot: dict, on: date) -> str:
        conv = lot.get("converted")
        if conv and on >= d(conv["date"]):
            return conv["security_class"]
        return lot["security_class"]

    def shares_at(self, lot: dict, on: date) -> int | None:
        conv = lot.get("converted")
        if conv and on >= d(conv["date"]):
            return conv["shares"]
        return lot["shares"]

    def held_lots(self, holding: str, on: date) -> list[dict]:
        out = []
        for lot in self.lots:
            if lot["holding"] != holding:
                continue
            if d(lot["acquired"]) > on:
                continue
            r = d(lot["realized"])
            if r is not None and r <= on:
                continue
            out.append(lot)
        return out

    def held_holdings(self, fund: str, on: date) -> list[str]:
        return [
            h for h, meta in self.holdings.items() if meta["fund"] == fund and self.held_lots(h, on)
        ]

    def realized_in_window(self, fund: str, on: date) -> list[str]:
        """Holdings with a lot realised in (previous packet date, on].

        Jackpocket is NOT held at 12/31/2024 — it was realised in May 2024 — yet
        that is precisely the packet where its realisation must be evidenced
        (PBC ¶4). Building rows from held_holdings alone made R4 dead code: the
        merger notice, its evidence link and r4()'s sufficient path were never
        reached at any date. Caught by the oracle-code adversary pass.
        """
        prev = self._prev_packet_date(fund, on)
        out = []
        for h, meta in self.holdings.items():
            if meta["fund"] != fund:
                continue
            for lot in self.lots:
                if lot["holding"] != h:
                    continue
                r = d(lot["realized"])
                if r is not None and r <= on and (prev is None or r > prev):
                    out.append(h)
                    break
        return out

    def packet_holdings(self, fund: str, on: date) -> list[tuple[str, bool]]:
        """(holding, held_at_date). Realised-in-window rows appear in the packet
        but are excluded from held-at-date totals."""
        held = self.held_holdings(fund, on)
        realized = [h for h in self.realized_in_window(fund, on) if h not in held]
        return [(h, True) for h in held] + [(h, False) for h in realized]

    # ---------- policy ----------

    def _period_id(self, fund: str, on: date) -> str | None:
        for k, v in self.periods.items():
            if v["fund"] == fund and d(v["date"]) == on:
                return k
        return None

    def _packet_dates(self, fund: str) -> list[date]:
        return sorted(
            d(v["date"])
            for v in self.periods.values()
            if v["fund"] == fund and v["audit_scope"] == "packet"
        )

    def _prev_packet_date(self, fund: str, on: date) -> date | None:
        earlier = [x for x in self._packet_dates(fund) if x < on]
        return max(earlier) if earlier else None

    # ---------- assembly ----------
