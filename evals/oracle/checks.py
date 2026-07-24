"""Standalone validator outputs: V1, V8, V9, V13, F5 and the change view.

Each returns a list of explicit pass/fail records rather than raising, so the
generated snapshot shows what was checked as well as what failed.
"""

from __future__ import annotations

from decimal import Decimal

from model import d, fmt, money


class ChecksMixin:
    def recap_checks(self) -> list[dict]:
        """V13 — prior shares x exchange ratio must equal stated post-recap shares,
        and must be an integer. INV-11 puts fractional shares out of scope, so a
        fractional result is a REJECTION, not a rounding rule."""
        out = []
        for lot in self.lots:
            conv = lot.get("converted")
            if not conv:
                continue
            computed = Decimal(lot["shares"]) * money(conv["ratio"])
            integral = computed == computed.to_integral_value()
            ok = integral and computed == Decimal(conv["shares"])
            out.append(
                {
                    "lot": lot["id"],
                    "prior_shares": lot["shares"],
                    "ratio": conv["ratio"],
                    "computed": fmt(computed),
                    "stated": conv["shares"],
                    "check": "pass"
                    if ok
                    else ("FAIL" if integral else "FRACTIONAL_SHARE_UNSUPPORTED"),
                }
            )
        return out

    def realization_checks(self) -> list[dict]:
        """V9/G9 — the proceeds arithmetic itself, not merely evidence coverage.

        r6's r4() proved a merger notice was linked and never proved
        500,000 x $6.20 = $3,100,000, so an implementation could report any
        amount and still pass.
        """
        out = []
        for lot in self.lots:
            if not lot.get("realized"):
                continue
            r = lot.get("realization", {})
            shares = r.get("shares", lot["shares"])
            pps = money(r.get("cash_per_share")) if r.get("cash_per_share") else None
            if shares is None or pps is None:
                out.append({"lot": lot["id"], "check": "missing_terms"})
                continue
            gross = Decimal(shares) * pps
            comps = {k: money(r.get(k, "0")) for k in ("fees", "escrow", "earnout", "withholding")}
            net = gross - sum(comps.values(), Decimal(0))
            out.append(
                {
                    "lot": lot["id"],
                    "realized": lot["realized"],
                    "shares": shares,
                    "cash_per_share": r["cash_per_share"],
                    "gross": fmt(gross),
                    "stated_gross": r.get("gross"),
                    **{k: fmt(v) for k, v in comps.items()},
                    "net": fmt(net),
                    "stated_net": r.get("net"),
                    "check": "pass"
                    if (
                        r.get("gross")
                        and money(r["gross"]) == gross
                        and r.get("net")
                        and money(r["net"]) == net
                    )
                    else "FAIL",
                }
            )
        return out

    def basis_checks(self) -> list[dict]:
        """F5 / INV-9 — a mark carried at COST where last-round methodology gives
        more. Computed over ALL periods, including lineage-only ones.

        Deferring this was wrong: SPEC §2 requires lineage periods in the change
        view, §15 retains the Fluidstack reconciliation finding, and §15 declares
        every F1-F12 finding non-negotiable. Caught in pre-build clearance.
        """
        out = []
        for holding, meta in self.holdings.items():
            for pid, amount in self.obs.get(holding, {}).items():
                if self.periods[pid]["fund"] != meta["fund"]:
                    continue
                on = d(self.periods[pid]["date"])
                held = self.held_lots(holding, on)
                if not held or any(self.shares_at(lt, on) is None for lt in held):
                    continue
                cost = sum((money(lt["cost"]) for lt in held), Decimal(0))
                top = max(money(lt["entry_pps"]) for lt in held)
                last_round = sum((Decimal(self.shares_at(lt, on)) * top for lt in held), Decimal(0))
                if money(amount) == cost and last_round > cost:
                    out.append(
                        {
                            "holding": holding,
                            "period": pid,
                            "date": on.isoformat(),
                            "audit_scope": self.periods[pid]["audit_scope"],
                            "tracker_amount": amount,
                            "cost_basis": fmt(cost),
                            "last_round_basis": fmt(last_round),
                            "variance": fmt(last_round - cost),
                            "declared_basis": "cost",
                        }
                    )
        return out

    def change_view(self) -> list[dict]:
        """INV-20 — lineage-only periods must appear here even though they never
        enter a packet. One row per mark transition."""
        out = []
        for holding in self.holdings:
            obs = [(d(self.periods[k]["date"]), k, v) for k, v in self.obs.get(holding, {}).items()]
            for i, (dt, pid, val) in enumerate(sorted(obs)):
                prev = sorted(obs)[i - 1] if i else None
                delta = (money(val) - money(prev[2])) if prev else None
                out.append(
                    {
                        "holding": holding,
                        "period": pid,
                        "date": dt.isoformat(),
                        "audit_scope": self.periods[pid]["audit_scope"],
                        "amount": val,
                        "previous_amount": prev[2] if prev else None,
                        "delta": fmt(delta) if delta is not None else None,
                        "changed": bool(delta) if delta is not None else None,
                    }
                )
        return out

    @staticmethod
    def classify_variance(concluded: Decimal, recomputed: Decimal | None) -> str:
        """SPEC V8. A rounding variance is the recomputation rounded to a stated
        scale — Moonfare's 999,970 is 1,000,000 to the nearest thousand. Anything
        else routes to human review; it is never silently passed."""
        if recomputed is None:
            return "NO_RECOMPUTATION"
        if concluded == recomputed:
            return "EXACT"
        # The rounding scale must be small relative to the value. Without this
        # cap, 987,654 "rounds" to 1,000,000 at a scale equal to the number
        # itself — which is not rounding, it is a different figure.
        limit = abs(concluded) * Decimal("0.001")
        for exp in range(0, 12):
            scale = Decimal(10) ** exp
            if scale > limit:
                break
            if (recomputed / scale).quantize(Decimal(1)) * scale == concluded:
                return "ROUNDING_VARIANCE"
        return "UNRECOGNISED_VARIANCE_REVIEW_REQUIRED"

    def concluded_value_checks(self) -> list[dict]:
        """INV-1 — a third-party memo's CONCLUDED value is authoritative.

        The system may recompute as a cross-check but must never substitute its
        own arithmetic. Moonfare FY2023: EUR 950,000 x 1.0526 = 999,970 while the
        memo concludes 1,000,000 (rounded). The $30 delta is a variance record,
        never a correction. Previously unguarded — replacing the concluded value
        with the recomputation left every anchor green.
        """
        out = []
        for name, doc in self.docs.items():
            concluded = doc.get("concluded_value")
            if concluded is None:
                continue
            holding = doc["holding"]
            lot = next(lt for lt in self.lots if lt["holding"] == holding)
            recomputed = None
            if doc.get("fx_rate") and lot.get("foreign_amount"):
                recomputed = money(lot["foreign_amount"]) * money(doc["fx_rate"])
            on = d(doc["applicable_from"])
            pid = self._period_id(self.holdings[holding]["fund"], on)
            reported = self.obs.get(holding, {}).get(pid)
            out.append(
                {
                    "document": name,
                    "concluded_value": concluded,
                    "reported_amount": reported,
                    "recomputed": fmt(recomputed) if recomputed is not None else None,
                    "variance": fmt(money(concluded) - recomputed)
                    if recomputed is not None
                    else None,
                    "authoritative": "concluded_value",
                    "classification": self.classify_variance(money(concluded), recomputed),
                    "check": "pass"
                    if reported is not None and money(reported) == money(concluded)
                    else "FAIL",
                }
            )
        return out

    def entry_costs(self) -> list[dict]:
        out = []
        for lot in self.lots:
            if lot["shares"] is None:
                out.append(
                    {
                        "lot": lot["id"],
                        "check": "not_applicable",
                        "cost": lot["cost"],
                        "reason": "no share count",
                    }
                )
                continue
            computed = Decimal(lot["shares"]) * money(lot["entry_pps"])
            out.append(
                {
                    "lot": lot["id"],
                    "shares": lot["shares"],
                    "entry_pps": lot["entry_pps"],
                    "computed": fmt(computed),
                    "stated": lot["cost"],
                    "check": "pass" if computed == money(lot["cost"]) else "FAIL",
                }
            )
        return out
