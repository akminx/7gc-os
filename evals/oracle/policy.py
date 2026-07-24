"""Requirement evaluation — the sufficiency matrix, supersession, R1-R5.

Every predicate here is stated once in docs/SPEC.md (§7.2 calibration,
§7.3 sufficiency, §7.4 the evidence reducer, §6.3 approvals) and implemented
once here. Three representations of one rule is what caused two failed fixer
cycles; two is the minimum that lets the spec be read by a human.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from model import (
    CONFLICTING,
    VERDICT_ORDER,
    WINDOWED_REQUIREMENTS,
    OracleError,
    best,
    d,
    fmt,
    minus_months,
    money,
    worst,
)


class PolicyMixin:
    def matrix_lookup(self, req: str, doc: dict, position_type: str) -> dict:
        for row in self.matrix:
            if (
                row["req"] == req
                and row["source_class"] == doc["source_class"]
                and row["execution_status"] == doc["execution_status"]
                and row["position_type"] == position_type
            ):
                return row
        raise OracleError(
            f"unenumerated policy tuple: ({req}, {doc['source_class']}, "
            f"{doc['execution_status']}, {position_type}). Fail closed — add the "
            f"cell to primitives.yaml deliberately."
        )

    def applicable_links(self, holding: str, req: str, on: date) -> list[tuple[str, dict]]:
        out = []
        for link in self.links:
            if link["holding"] != holding or link["requirement"] != req:
                continue
            doc = self.docs[link["document"]]
            if req in WINDOWED_REQUIREMENTS:
                if d(doc["applicable_from"]) > on:
                    continue
                to = d(doc.get("applicable_to"))
                if to is not None and to < on:
                    continue
            else:
                if d(doc["date"]) > on:
                    continue
            out.append((link["document"], doc))
        return out

    def supersede(self, links: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
        """SPEC §7.4. Supersession is WITHIN a priced class, not global.

        r5 grouped by priced_class and kept one global winner; r6 added claim ids
        but kept the same global selection, so it was a cosmetic fix. A probe with
        independent `sa` and `sb` claims retained only the later one — the two
        must coexist, because each prices a different class the fund holds.
        An explicit `supersedes` pointer removes a superseded version.
        """
        if not links:
            return links
        by_class: dict[str, dict[str, list[tuple[str, dict]]]] = {}
        for name, doc in links:
            key = doc.get("priced_class") or f"__{doc['claim']}"
            by_class.setdefault(key, {}).setdefault(doc["claim"], []).append((name, doc))
        out: list[tuple[str, dict]] = []
        for claims in by_class.values():
            winner = max(claims.values(), key=lambda g: max(d(doc["date"]) for _, doc in g))
            out.extend(winner)
        superseded = {doc.get("supersedes") for _, doc in out if doc.get("supersedes")}
        return [(n, dd) for n, dd in out if n not in superseded]

    def gaps_for(self, holding: str, req: str, sec_class: str | None = None) -> list[dict]:
        return [
            g
            for g in self.gaps
            if g["holding"] == holding
            and g["requirement"] == req
            and (sec_class is None or g.get("security_class") == sec_class)
        ]

    # ---------- requirements ----------

    def r1(self, holding: str, on: date) -> dict:
        """Existence and cost — evaluated per held lot, worst wins (INV-7)."""
        pt = self.holdings[holding]["position_type"]
        per_lot, actions = {}, set()
        for lot in self.held_lots(holding, on):
            cls = self.class_at(lot, on)
            candidates = []
            for _, doc in self.applicable_links(holding, "R1", on):
                covers = doc["priced_class"] in (None, cls)
                if covers:
                    row = self.matrix_lookup("R1", doc, pt)
                    candidates.append(row["verdict"])
                    if row.get("next_action"):
                        actions.add(row["next_action"])
            for g in self.gaps_for(holding, "R1", lot["security_class"]):
                gv = self.gap_verdicts[g["kind"]]
                candidates.append(gv["verdict"])
                actions.add(gv["next_action"])
            if not candidates:
                candidates = ["missing"]
                actions.add("REQUEST_FROM_COMPANY")
            per_lot[lot["id"]] = best(candidates)
        if not per_lot:
            return {"verdict": "not_applicable", "next_actions": []}
        return {
            "verdict": worst(list(per_lot.values())),
            "per_lot": per_lot,
            "next_actions": sorted(actions),
        }

    def r2(self, holding: str, on: date) -> dict:
        """Fair value support at this measurement date."""
        if not self.held_lots(holding, on):
            return {
                "verdict": "not_applicable",
                "reasons": [],
                "next_actions": [],
                "relied_on": [],
                "cross_class": False,
                "pro_forma": False,
                "subsequent_evidence": False,
            }
        pt = self.holdings[holding]["position_type"]
        links = self.supersede(self.applicable_links(holding, "R2", on))
        verdicts, reasons, actions, relied = [], set(), set(), []

        for name, doc in links:
            row = self.matrix_lookup("R2", doc, pt)
            verdicts.append(row["verdict"])
            relied.append((name, doc))
            if row.get("reason"):
                reasons.add(row["reason"])
            if row.get("next_action"):
                actions.add(row["next_action"])

        if not links:
            gaps = self.gaps_for(holding, "R2")
            kind = gaps[0]["kind"] if gaps else "none"
            gv = self.gap_verdicts[kind]
            verdicts.append(gv["verdict"])
            actions.add(gv["next_action"])
            reasons.add(f"NO_APPLICABLE_SUPPORT_{kind.upper()}")

        # Q1-8: two relied-upon documents asserting the SAME claim with
        # different prices materially contradict. `conflicting` dominates and
        # persists until a recorded resolution supersedes one claim (SPEC §7.4).
        by_claim: dict[str, set] = {}
        for _, doc in relied:
            if doc.get("pps"):
                by_claim.setdefault(doc["claim"], set()).add(str(money(doc["pps"])))
        contradicted = sorted(c for c, v in by_claim.items() if len(v) > 1)
        if contradicted:
            resolved = {
                r.get("claim")
                for r in self.p.get("claim_resolutions", [])
                if r.get("holding") == holding
            }
            if not set(contradicted) <= resolved:
                return {
                    "verdict": CONFLICTING,
                    "reasons": ["CONTRADICTORY_CLAIMS"],
                    "next_actions": ["RESOLVE_CONTRADICTION"],
                    "relied_on": [n for n, _ in relied],
                    "cross_class": False,
                    "pro_forma": False,
                    "subsequent_evidence": False,
                    "contradicted_claims": contradicted,
                }

        verdict = best(verdicts)

        # Q1-7: a document covering ONE class must not mark a multi-lot holding
        # sufficient. Any held class with no covering relied-upon document caps
        # the verdict at `partial`.
        held = self.held_lots(holding, on)
        covered = {doc.get("priced_class") for _, doc in relied}
        uncovered = [
            self.class_at(lt, on)
            for lt in held
            if None not in covered and self.class_at(lt, on) not in covered
        ]
        if uncovered and verdict == "sufficient":
            verdict = "partial"
            reasons.add("UNCOVERED_SECURITY_CLASS")
            actions.add("REQUEST_SUPPORT_FOR_CLASS")

        # Cross-class pricing (INV-17), derived from held class vs priced class —
        # independent of any label, so omitting a label cannot bypass it.
        held_classes = {self.class_at(lt, on) for lt in self.held_lots(holding, on)}
        cross = False
        for _, doc in relied:
            pc = doc.get("priced_class")
            if pc and any(c != pc for c in held_classes):
                cross = True
        scoped = [
            x
            for x in self.policy_decisions
            if x.get("holding") == holding and x.get("date") == on.isoformat()
        ]
        if cross and not scoped:
            if VERDICT_ORDER.index(verdict) > VERDICT_ORDER.index("partial"):
                verdict = "partial"
            reasons.add("CROSS_CLASS_POLICY_DECISION_REQUIRED")
            actions.add("RECORD_VALUATION_POLICY_DECISION")

        # pro_forma derived from relied-upon execution statuses (INV-4)
        pro_forma = any(doc["execution_status"] == "pro_forma" for _, doc in relied)
        if pro_forma:
            latest_pf = max(
                d(doc["date"]) for _, doc in relied if doc["execution_status"] == "pro_forma"
            )
            if any(
                doc["execution_status"] == "executed" and d(doc["date"]) >= latest_pf
                for _, doc in relied
            ):
                pro_forma = False

        subsequent = any(d(doc.get("delivered") or doc["date"]) > on for _, doc in relied)

        return {
            "verdict": verdict,
            "reasons": sorted(reasons),
            "next_actions": sorted(actions),
            "relied_on": [n for n, _ in relied],
            "cross_class": cross,
            "pro_forma": pro_forma,
            "subsequent_evidence": subsequent,
        }

    def r3(self, holding: str, on: date, fund: str) -> dict:
        """Unchanged-mark calibration. SPEC §7.2.

        (a) reported amount equals the immediately preceding mark OBSERVATION
            (lineage-only periods may serve as that predecessor — they establish
            that the value is unchanged without resetting support age);
        (b) AT LEAST ONE material component lacks qualifying support dated within
            the preceding 12 calendar months. Exactly 12 months is not stale.
        """
        obs = self.obs.get(holding, {})
        pid = self._period_id(fund, on)
        if pid not in obs:
            return {"verdict": "not_applicable", "reason": "no mark at this date"}

        prior = [
            (d(self.periods[k]["date"]), v)
            for k, v in obs.items()
            if self.periods[k]["fund"] == fund and d(self.periods[k]["date"]) < on
        ]
        if not prior:
            return {"verdict": "not_applicable", "reason": "no preceding mark observation"}
        prev_date, prev_val = max(prior, key=lambda x: x[0])
        if money(prev_val) != money(obs[pid]):
            return {"verdict": "not_applicable", "reason": f"value changed since {prev_date}"}

        threshold = minus_months(on, 12)
        stale = []
        for comp in self.support.get(holding, []):
            dates = [d(x) for x in comp["dates"] if d(x) <= on]
            if not dates:
                stale.append({"component": comp["component"], "latest": None})
            elif max(dates) < threshold:
                stale.append({"component": comp["component"], "latest": max(dates).isoformat()})
        if not stale:
            return {
                "verdict": "not_applicable",
                "reason": "all components have support within 12 months",
            }

        approved = [
            a
            for a in self.assessments
            if a.get("holding") == holding
            and a.get("date") == on.isoformat()
            and a.get("status") == "approved"
            and self.fingerprint_ok(a, holding, on)
        ]
        return {
            "verdict": "sufficient" if approved else "missing",
            "stale_components": stale,
            "unchanged_since": prev_date.isoformat(),
            "next_actions": [] if approved else ["DRAFT_MANAGEMENT_ASSESSMENT"],
        }

    def r4(self, holding: str, on: date, fund: str) -> dict:
        """Realisation support for EVERY lot realised in this window.

        r5 selected `realized[0]`, so a holding with two realised lots could be
        judged from the wrong event, and a first event outside the window
        suppressed a second event inside it.
        """
        pt = self.holdings[holding]["position_type"]
        prev = self._prev_packet_date(fund, on)
        events = [
            lt
            for lt in self.lots
            if lt["holding"] == holding
            and lt["realized"]
            and d(lt["realized"]) <= on
            and (prev is None or d(lt["realized"]) > prev)
        ]
        if not events:
            return {"verdict": "not_applicable"}
        links = self.applicable_links(holding, "R4", on)
        per_lot = {}
        for lot in events:
            covering = [
                (n, doc)
                for n, doc in links
                if doc.get("priced_class") in (None, lot["security_class"])
            ]
            per_lot[lot["id"]] = (
                best([self.matrix_lookup("R4", doc, pt)["verdict"] for _, doc in covering])
                if covering
                else "missing"
            )
        return {
            "verdict": worst(list(per_lot.values())),
            "per_lot": per_lot,
            "events": [lt["id"] for lt in events],
            "relied_on": [n for n, _ in links],
            "next_actions": []
            if all(v == "sufficient" for v in per_lot.values())
            else ["REQUEST_REALIZATION_SUPPORT"],
        }

    def r5(self, holding: str, on: date, r2: dict) -> dict:
        if not r2.get("pro_forma"):
            return {"verdict": "not_applicable"}
        return {
            "verdict": "sufficient",
            "note": "label present and derived from relied-upon inputs",
        }

    # ---------- helpers ----------

    def validated_amount(self, holding: str, on: date, relied, authorized: bool = False):
        """INV-13. Derived PER LOT from the claim pricing that lot's own class.

        r6 took `priced[0]["pps"]` and applied it to every held lot. A probe with
        100 class-A shares at $10 and 100 class-B at $20 derived $4,000 instead of
        $3,000. Cross-class propagation is now only possible with a cited policy
        decision (`authorized`), and even then it is recorded as such.
        """
        if not relied:
            return None, "not_derivable", "NO_APPLICABLE_EVIDENCE", []
        for _, doc in relied:
            if doc.get("concluded_value") is not None:
                return money(doc["concluded_value"]), "derivable", "THIRD_PARTY_CONCLUSION", []
            if doc.get("nav") is not None:
                return money(doc["nav"]), "derivable", "ADMINISTRATOR_NAV", []
        priced = [doc for _, doc in relied if doc.get("pps")]
        if not priced:
            return None, "not_derivable", "NO_PRICE_IN_EVIDENCE", []
        held = self.held_lots(holding, on)
        if any(self.shares_at(lt, on) is None for lt in held):
            return None, "not_derivable", "COMPONENT_WITHOUT_SHARE_COUNT", []
        by_class = {doc["priced_class"]: doc for doc in priced if doc.get("priced_class")}
        latest = max(priced, key=lambda x: d(x["date"]))
        total, lineage, uncovered = Decimal(0), [], []
        for lot in held:
            cls = self.class_at(lot, on)
            doc = by_class.get(cls)
            if doc is None:
                if not authorized:
                    uncovered.append(cls)
                    continue
                doc = latest
            amt = Decimal(self.shares_at(lot, on)) * money(doc["pps"])
            total += amt
            lineage.append(
                {
                    "lot": lot["id"],
                    "class": cls,
                    "pps": doc["pps"],
                    "shares": self.shares_at(lot, on),
                    "amount": fmt(amt),
                    "cross_class": doc.get("priced_class") != cls,
                }
            )
        if uncovered:
            return (
                None,
                "not_derivable",
                f"NO_PRICE_FOR_CLASS:{','.join(sorted(set(uncovered)))}",
                [],
            )
        return total, "derivable", "PER_CLASS_SHARES_X_PPS", lineage

    def current_fingerprint(self, holding: str, on: date) -> dict:
        """The identity an approval must match to still be current."""
        r2 = self.r2(holding, on)
        return {
            "mark_revision": f"{holding}@{on.isoformat()}",
            "evidence_set_hash": "|".join(sorted(r2.get("relied_on", []))) or "none",
            "policy_version": self.p.get("policy_version", "v1"),
        }

    def fingerprint_ok(self, record: dict, holding: str, on: date) -> bool:
        want = self.current_fingerprint(holding, on)
        return all(record.get(k) == v for k, v in want.items())

    @staticmethod
    def reduce_row(applicable: list[str]) -> str:
        """SPEC §6.2.1. `conflicting` dominates and is outside the severity scale;
        otherwise the weakest applicable verdict wins.

        Extracted so `conflicting` is exercisable: no corpus document contradicts
        another, and a branch that cannot be reached by any test is the failure
        mode this whole exercise exists to avoid.
        """
        if CONFLICTING in applicable:
            return CONFLICTING
        rest = [v for v in applicable if v != CONFLICTING]
        return worst(rest) if rest else "not_applicable"
