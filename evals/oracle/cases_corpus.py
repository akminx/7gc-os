"""Anchors over the real corpus: totals, findings F1-F12, R3 boundaries."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

from harness import Oracle, OracleError, check, row, totals

HERE = Path(__file__).parent


def run(snap: dict, o: Oracle) -> None:
    cross_class_is_symmetric()
    print("\n── Entry cost: every share-bearing lot ties exactly ──")
    check("all 17 lots checked", len(snap["entry_costs"]), 17)
    check("zero arithmetic failures", [e for e in snap["entry_costs"] if e["check"] == "FAIL"], [])
    check("14 share-bearing lots", sum(1 for e in snap["entry_costs"] if e["check"] == "pass"), 14)
    check(
        "3 non-share lots not_applicable",
        sum(1 for e in snap["entry_costs"] if e["check"] == "not_applicable"),
        3,
    )

    print("\n── F4: Fund II FY2023 held-at-date total ──")
    # Jackpocket was held at 12/31/2023 and realised 5/20/2024. The tracker's
    # "TOTAL (active)" omits it. 1,000,000 + 1,000,000 + 2,000,000 + 2,000,000.
    t = totals(snap, "fund_ii", "2023-12-31")
    check("held-at-date total", t["held_at_date_reported_total"], "6000000")
    check("tracker states", t["tracker_stated_total"], "4000000")
    check("reconciliation delta", t["reconciliation_delta"], "2000000")
    check("positions held", t["positions_held"], 4)

    print("\n── Unsupported subtotals ──")
    # 25Q4: every position fails something. Poolside is R1/R2 sufficient but its
    # R3 calibration is missing, so it is not fully supported either.
    check(
        "fund_ii 25Q4 unsupported",
        totals(snap, "fund_ii", "2025-12-31")["unsupported_subtotal"],
        "25648515",
    )
    check(
        "fund_ii 23Q4 unsupported",
        totals(snap, "fund_ii", "2023-12-31")["unsupported_subtotal"],
        "6000000",
    )
    # 24Q4: Poolside (2,000,000) and Fluidstack (1,000,000) are fully supported.
    # Fluidstack's A-2 lot was not acquired until 30 May 2025, so its
    # with_counsel gap does not apply at this date.
    check(
        "fund_ii 24Q4 unsupported",
        totals(snap, "fund_ii", "2024-12-31")["unsupported_subtotal"],
        "7548515",
    )
    # Fund I: only Jio is fully supported at every date.
    check(
        "fund_i FY2023 unsupported",
        totals(snap, "fund_i", "2023-12-31")["unsupported_subtotal"],
        "4970000",
    )
    check(
        "fund_i FY2024 unsupported",
        totals(snap, "fund_i", "2024-12-31")["unsupported_subtotal"],
        "4905000",
    )
    check(
        "fund_i FY2025 unsupported",
        totals(snap, "fund_i", "2025-12-31")["unsupported_subtotal"],
        "4881000",
    )

    print("\n── approved_fair_value_total is null at all six packet dates ──")
    check("all six null", [t["approved_fair_value_total"] for t in snap["totals"]], [None] * 6)

    print("\n── R3 boundary: exactly 12 months is NOT stale ──")
    # Capsule's memo is dated 12/31/2022. At FY2023 that is exactly 12 months.
    check(
        "capsule FY2023 not applicable",
        row(snap, "capsule", "2023-12-31")["requirements"]["R3"]["verdict"],
        "not_applicable",
    )
    check(
        "capsule FY2024 missing",
        row(snap, "capsule", "2024-12-31")["requirements"]["R3"]["verdict"],
        "missing",
    )
    # Moonfare's FX memo is exactly 12 months old at 25Q4, but the underlying
    # EUR valuation dates to March 2023 — 33 months. "At least one" fires.
    check(
        "moonfare 25Q4 missing",
        row(snap, "moonfare", "2025-12-31")["requirements"]["R3"]["verdict"],
        "missing",
    )
    check(
        "moonfare stale component is the underlying, not the FX rate",
        [
            c["component"]
            for c in row(snap, "moonfare", "2025-12-31")["requirements"]["R3"]["stale_components"]
        ],
        ["underlying_valuation"],
    )

    print("\n── R3 predecessor: lineage-only periods may establish 'unchanged' ──")
    # Fund I FY2021/FY2022 are lineage-only, but Roofstock is flat at 1,500,000
    # across them, which proves the mark did not move.
    check(
        "roofstock FY2023 fires",
        row(snap, "roofstock", "2023-12-31")["requirements"]["R3"]["verdict"],
        "missing",
    )
    # Because Market has no observation before 23Q4, so 'unchanged' is unprovable.
    check(
        "because_market 23Q4 not applicable",
        row(snap, "because_market", "2023-12-31")["requirements"]["R3"]["verdict"],
        "not_applicable",
    )
    # Jio's administrator statement is re-dated annually — never stale.
    for iso in ("2023-12-31", "2024-12-31", "2025-12-31"):
        check(
            f"jio {iso} never fires",
            row(snap, "jio", iso)["requirements"]["R3"]["verdict"],
            "not_applicable",
        )

    print("\n── F11: exactly six positions at their latest packet date ──")
    latest = {"fund_ii": "2025-12-31", "fund_i": "2025-12-31"}
    fired = sorted(
        r["holding"]
        for r in snap["rows"]
        if r["date"] in latest.values() and r["requirements"]["R3"]["verdict"] == "missing"
    )
    check(
        "F11 set",
        fired,
        ["because_market", "capsule", "mom_project", "moonfare", "poolside", "roofstock"],
    )

    print("\n── F1 / F2: the two non-derivable marks ──")
    # `missing`, and this anchor has now been written both ways — which is the
    # useful part of its history.
    #
    # It briefly asserted `insufficient`, on the reading that "the interest will
    # be re-measured at the closing rate at each future measurement date" is
    # INV-6 speaking about the RATE rather than INV-16 speaking about reliance,
    # so the window should stand open and the memo be in scope at 25Q4. The
    # sentence's grammatical subject settles it the other way: the subject is
    # THE INTEREST, and the closing rate is the instrument of re-measurement,
    # not the thing being scoped. It is a whole-document reliance clause of the
    # same family as Capsule's memo and Moonfare's own FY2023 one.
    #
    # The cost of the other reading was not this verdict but the NEXT ACTION.
    # `insufficient` asks an auditor to go and get primary evidence for support
    # the packet is holding; `missing` tells them the support expired and an
    # updated valuation is required. The document that would have supplied the
    # first is the one whose stale figure the gap exists to flag.
    #
    # The reason and action are asserted, not just the verdict: `missing` alone
    # is what Because Market also reports, and never-had-any and had-and-expired
    # are the two findings this row exists to keep apart.
    moonfare_r2 = row(snap, "moonfare", "2025-12-31")["requirements"]["R2"]
    check(
        "moonfare 25Q4 R2 missing (its own memo does not reach this date)",
        moonfare_r2["verdict"],
        "missing",
    )
    check(
        "moonfare 25Q4 R2 reason",
        moonfare_r2["reasons"],
        ["SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW"],
    )
    check("moonfare 25Q4 R2 action", moonfare_r2["next_actions"], ["REQUEST_UPDATED_VALUATION"])
    check(
        "anthropic 25Q4 R2 insufficient (press)",
        row(snap, "anthropic", "2025-12-31")["requirements"]["R2"]["verdict"],
        "insufficient",
    )
    check(
        "anthropic reason",
        "PRESS_CANNOT_SUPPORT_FAIR_VALUE"
        in row(snap, "anthropic", "2025-12-31")["requirements"]["R2"]["reasons"],
        True,
    )

    print("\n── F3: Capsule's memo does not reach subsequent dates ──")
    for iso in ("2023-12-31", "2024-12-31", "2025-12-31"):
        check(
            f"capsule {iso} R2 missing",
            row(snap, "capsule", iso)["requirements"]["R2"]["verdict"],
            "missing",
        )

    print("\n── INV-17: cross-class derived from held vs priced class ──")
    for h in ("dream", "fluidstack", "lucra"):
        check(
            f"{h} 25Q4 cross_class",
            row(snap, h, "2025-12-31")["requirements"]["R2"]["cross_class"],
            True,
        )
    check(
        "mom_project FY2025 cross_class",
        row(snap, "mom_project", "2025-12-31")["requirements"]["R2"]["cross_class"],
        True,
    )
    # Sway's Series A converted INTO Series A-3, which is the class the recap
    # prices. Held class equals priced class, so this is not cross-class.
    check(
        "sway 25Q4 NOT cross_class",
        row(snap, "sway", "2025-12-31")["requirements"]["R2"]["cross_class"],
        False,
    )
    check(
        "poolside NOT cross_class",
        row(snap, "poolside", "2025-12-31")["requirements"]["R2"]["cross_class"],
        False,
    )

    print("\n── INV-4: pro_forma from relied-upon inputs, not from 'not executed' ──")
    for h in ("sway", "dream", "fluidstack"):
        check(f"{h} 25Q4 pro_forma", row(snap, h, "2025-12-31")["labels"].count("pro_forma"), 1)
    check(
        "jio FY2025 NOT pro_forma", "pro_forma" in row(snap, "jio", "2025-12-31")["labels"], False
    )
    check(
        "banzai FY2025 NOT pro_forma",
        "pro_forma" in row(snap, "banzai", "2025-12-31")["labels"],
        False,
    )
    # Anthropic's mark rests on press — there is no pro forma DOCUMENT at all.
    # The tracker calls it "PRO FORMA"; the derived label disagrees, and that
    # disagreement is a reconciliation finding rather than a contradiction.
    check(
        "anthropic 25Q4 derives NOT pro_forma",
        "pro_forma" in row(snap, "anthropic", "2025-12-31")["labels"],
        False,
    )

    print("\n── Held-at-date: Fluidstack's second tranche ──")
    check("24Q4 one lot held", len(o.held_lots("fluidstack", date(2024, 12, 31))), 1)
    check("25Q4 two lots held", len(o.held_lots("fluidstack", date(2025, 12, 31))), 2)
    check(
        "fluidstack 24Q4 fully supported",
        row(snap, "fluidstack", "2024-12-31")["fully_supported"],
        True,
    )
    check(
        "fluidstack 25Q4 not fully supported",
        row(snap, "fluidstack", "2025-12-31")["fully_supported"],
        False,
    )

    print("\n── Jackpocket realisation boundary ──")
    check("held at 23Q4", len(o.held_lots("jackpocket", date(2023, 12, 31))), 1)
    check("not held at 24Q4", len(o.held_lots("jackpocket", date(2024, 12, 31))), 0)

    print("\n── Metamorphic: a changed input must move only dependent outputs ──")
    o2 = Oracle(HERE / "primitives.yaml")
    o2.lots = copy.deepcopy(o2.lots)
    for lot in o2.lots:
        if lot["id"] == "pool_1":
            lot["shares"] = 60000  # 60,000 × $40.00 = 2,400,000 ≠ stated cost
    snap2 = o2.run()
    pool = next(e for e in snap2["entry_costs"] if e["lot"] == "pool_1")
    check("perturbed Poolside lot now FAILs entry cost", pool["check"], "FAIL")
    check("perturbed computed value", pool["computed"], "2400000")
    check(
        "unrelated lot unaffected",
        next(e for e in snap2["entry_costs"] if e["lot"] == "roof_1")["check"],
        "pass",
    )
    check(
        "totals unaffected by a share-count change",
        totals(snap2, "fund_ii", "2025-12-31")["held_at_date_reported_total"],
        totals(snap, "fund_ii", "2025-12-31")["held_at_date_reported_total"],
    )

    print("\n── Fail-closed: an unenumerated policy tuple must raise ──")
    o3 = Oracle(HERE / "primitives.yaml")
    o3.matrix = [r for r in o3.matrix if not (r["req"] == "R2" and r["source_class"] == "press")]
    try:
        o3.run()
        check("removing the press cell raises", False, True)
    except OracleError as e:
        check("removing the press cell raises", "unenumerated policy tuple" in str(e), True)

    print("\n── R4: Jackpocket's realisation is assessed at 12/31/2024 ──")
    # It is NOT held at that date — that is the point. Building rows from held
    # holdings alone made r4() dead code at every date.
    jp = row(snap, "jackpocket", "2024-12-31")
    check("R4 sufficient", jp["requirements"]["R4"]["verdict"], "sufficient")
    check(
        "relies on the merger notice", jp["requirements"]["R4"]["relied_on"], ["jackpocket_merger"]
    )
    check("not counted as held", jp["held_at_date"], False)
    check(
        "R2 not applicable to a realised row", jp["requirements"]["R2"]["verdict"], "not_applicable"
    )
    check(
        "excluded from the held-at-date total",
        totals(snap, "fund_ii", "2024-12-31")["held_at_date_reported_total"],
        "10548515",
    )
    check(
        "still assessed at 23Q4 when held",
        row(snap, "jackpocket", "2023-12-31")["held_at_date"],
        True,
    )

    print("\n── Conversion must not erase acquisition-document lineage ──")
    # Sway's Series A converted to A-3 on 30 Sep 2025. The Series A SPA is still
    # the acquisition document and is still with counsel.
    sway = row(snap, "sway", "2025-12-31")["requirements"]["R1"]
    check("sway 25Q4 R1 partial", sway["verdict"], "partial")
    check(
        "sway 25Q4 keeps REQUEST_FROM_COUNSEL", "REQUEST_FROM_COUNSEL" in sway["next_actions"], True
    )

    print("\n── Gap kinds resolve to distinct verdicts and actions ──")
    anth = row(snap, "anthropic", "2024-12-31")["requirements"]["R1"]
    check("referenced_location_unspecified → insufficient", anth["verdict"], "insufficient")
    check("… with REQUEST_WITH_LOCATION", "REQUEST_WITH_LOCATION" in anth["next_actions"], True)
    check(
        "with_counsel → partial",
        row(snap, "banzai", "2025-12-31")["requirements"]["R1"]["verdict"],
        "partial",
    )
    check(
        "not_located → missing",
        row(snap, "capsule", "2025-12-31")["requirements"]["R1"]["verdict"],
        "missing",
    )

    print("\n── V13: recap ratio is validated, not trusted ──")
    check("one recap in corpus", len(snap["recap_checks"]), 1)
    check("800,000 × 1.09375 = 875,000", snap["recap_checks"][0]["computed"], "875000")
    check("passes", snap["recap_checks"][0]["check"], "pass")
    o4 = Oracle(HERE / "primitives.yaml")
    o4.lots = copy.deepcopy(o4.lots)
    for lot in o4.lots:
        if lot["id"] == "sway_1":
            lot["converted"]["ratio"] = "1.1"  # 800,000 × 1.1 = 880,000 ≠ 875,000
    check("a wrong ratio FAILs", o4.recap_checks()[0]["check"], "FAIL")
    o5 = Oracle(HERE / "primitives.yaml")
    o5.lots = copy.deepcopy(o5.lots)
    for lot in o5.lots:
        if lot["id"] == "sway_1":
            lot["converted"]["ratio"] = "1.093755"  # 875,004 exactly? no — fractional
            lot["shares"] = 7
    check(
        "a fractional result is rejected, not rounded",
        o5.recap_checks()[0]["check"],
        "FRACTIONAL_SHARE_UNSUPPORTED",
    )

    print("\n── Supersession is derived, not encoded in the data ──")
    # Fluidstack's Series A SPA has applicable_to: null. The Series B cap table
    # supersedes it at 25Q4 by being a later priced_class group — but not at 24Q4.
    check(
        "24Q4 relies on the Series A SPA",
        row(snap, "fluidstack", "2024-12-31")["requirements"]["R2"]["relied_on"],
        ["fluidstack_a_spa"],
    )
    # THREE, not two. The A-2 cap-table reference prices series_a2 — a class the
    # fund holds 100,000 shares of at this date — and was relied on for nothing,
    # so the derivation had no price for that class and reported `unconfirmable`
    # while the price sat cited in the corpus. The principle this case defends is
    # unchanged (claims pricing different held classes coexist); the enumeration
    # was short by the one that was unreachable.
    # Asserted IN ORDER. This was wrapped in `sorted()`, which is why the
    # oracle and the product could disagree about the order of these three and
    # nothing said so: the wrapper normalised both sides of a value the packet
    # publishes as a sequence. The A-2 reference and the Series B cap table are
    # both dated 12/18/2025, so this is the case where the tiebreak is load
    # bearing.
    check(
        "25Q4 retains a claim per priced class, in the order the evidence arose",
        row(snap, "fluidstack", "2025-12-31")["requirements"]["R2"]["relied_on"],
        ["fluidstack_a_spa", "fluidstack_a2_ref", "fluidstack_b_cap"],
    )
    # Dream's cap table and closing email evidence the SAME round — they
    # corroborate rather than supersede, so pro_forma must survive.
    check(
        "dream relies on both same-round documents, cap table then closing email",
        row(snap, "dream", "2025-12-31")["requirements"]["R2"]["relied_on"],
        ["dream_b_cap", "dream_close_email"],
    )
    check("dream stays pro_forma", "pro_forma" in row(snap, "dream", "2025-12-31")["labels"], True)

    print("\n── Approval is a separate record, not 'nothing unsupported' ──")
    check(
        "all six blocked by unsupported rows",
        [t["approved_blocked_by"] for t in snap["totals"]],
        ["unsupported_rows"] * 6,
    )
    check(
        "no approved total anywhere",
        [t["approved_fair_value_total"] for t in snap["totals"]],
        [None] * 6,
    )

    print("\n── Omissions must fail closed, not fail open ──")
    for label, mutate in [
        ("missing support_observations raises", lambda o: o.support.pop("roofstock")),
        ("duplicate policy cell raises", lambda o: o.matrix.append(dict(o.matrix[0]))),
        (
            "unknown verdict raises",
            lambda o: o.matrix.__setitem__(0, {**o.matrix[0], "verdict": "probably_fine"}),
        ),
    ]:
        oo = Oracle(HERE / "primitives.yaml")
        oo.support = copy.deepcopy(oo.support)
        oo.matrix = copy.deepcopy(oo.matrix)
        mutate(oo)
        try:
            oo._validate()
            check(label, False, True)
        except OracleError:
            check(label, True, True)


def cross_class_is_symmetric() -> None:
    """INV-17 · held classes must equal priced classes.

    Both one-way tests of this were wrong on the corpus, in opposite directions,
    and the database and the oracle disagreed with each other on the same facts.
    """
    o17 = Oracle(HERE / "primitives.yaml")
    # INV-17 is PROPAGATION, and both one-way tests were wrong here. The rule
    # is equality of held and priced class sets. Lucra pins priced-minus-held
    # (holds A-1, marked at the A-2 price, so "is every held class covered" says
    # yes); Mom pins held-minus-priced (three classes, priced off Series C, so
    # "is the priced class held" says yes and clears the case INV-17 exists for).
    on = date(2025, 12, 31)
    for who, n_classes in (("lucra", 1), ("mom_project", 3)):
        held = {o17.class_at(lt, on) for lt in o17.held_lots(who, on)}
        check(
            f"{who} holds {n_classes} class(es) and is cross-class",
            (len(held), "CROSS_CLASS_POLICY_DECISION_REQUIRED" in o17.r2(who, on)["reasons"]),
            (n_classes, True),
        )
