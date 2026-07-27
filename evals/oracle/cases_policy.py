"""Anchors over policy behaviour: claims, approvals, derivation, contradictions.

Several use Oracle.from_dict to reach branches the fixed corpus cannot —
positive approval, multi-lot realisation, multi-class pricing.
"""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path

from harness import SYNTH_BASE, Oracle, OracleError, check, fmt_, row, synth

HERE = Path(__file__).parent


def run(snap: dict, o: Oracle) -> None:
    print("\n── §6.2.1: `conflicting` dominates the row reducer ──")
    check(
        "conflicting beats sufficient",
        Oracle.reduce_row(["sufficient", "conflicting"]),
        "conflicting",
    )
    check("conflicting beats missing", Oracle.reduce_row(["missing", "conflicting"]), "conflicting")
    check(
        "otherwise weakest wins", Oracle.reduce_row(["sufficient", "partial", "missing"]), "missing"
    )
    check(
        "insufficient beats missing", Oracle.reduce_row(["insufficient", "partial"]), "insufficient"
    )
    check("nothing applicable", Oracle.reduce_row([]), "not_applicable")

    print("\n── INV-4: management's label vs the derived label ──")
    # Exactly one row in the corpus where management asserted a label the
    # evidence does not support.
    dis = [(r["holding"], r["date"]) for r in snap["rows"] if r["unsupported_tracker_labels"]]
    check("exactly one disagreement", dis, [("anthropic", "2025-12-31")])
    anth = row(snap, "anthropic", "2025-12-31")
    check("management asserted pro_forma", anth["tracker_label"], ["pro_forma"])
    check("derivation did not", "pro_forma" in anth["labels"], False)
    # Silence is not an assertion of absence: Dream/Sway/Fluidstack derive
    # pro_forma with no tracker note, which is NOT a disagreement.
    check(
        "derived-only label is not an unsupported tracker claim",
        row(snap, "dream", "2025-12-31")["unsupported_tracker_labels"],
        [],
    )
    # If ingest ever copies tracker_label into pro_forma, this goes to zero.
    check("disagreement is representable at all", len(dis) > 0, True)

    print("\n── §6.2.2: execution_status describes the artifact, not the transaction ──")
    # Dream's email says the round CLOSED and the cap table cites an executed
    # SPA, yet what the Fund holds is a pro forma table — so the mark is pro forma.
    check(
        "dream derives pro_forma despite a closed round",
        "pro_forma" in row(snap, "dream", "2025-12-31")["labels"],
        True,
    )
    check(
        "and relies on both same-round artifacts",
        len(row(snap, "dream", "2025-12-31")["requirements"]["R2"]["relied_on"]),
        2,
    )

    print("\n── INV-1: the memo's concluded value stays authoritative ──")
    cv = {c["document"]: c for c in snap["concluded_value_checks"]}
    check("two memos carry a concluded value", sorted(cv), ["moonfare_fx_24", "moonfare_memo_23"])
    m23 = cv["moonfare_memo_23"]
    check("concluded is 1,000,000", m23["concluded_value"], "1000000")
    check("recomputed is 999,970", m23["recomputed"], "999970")
    check("variance is 30, recorded not corrected", m23["variance"], "30")
    check("the reported mark follows the concluded value", m23["check"], "pass")
    check("FY2024 recomputes exactly", cv["moonfare_fx_24"]["variance"], "0")

    print("\n── Q1-2/INV-13: validated amount is orthogonal to the verdict ──")
    for h, dt, val, st in [
        ("poolside", "2025-12-31", "2000000", "derivable"),
        # Not `not_derivable`: the evidence is present and in scope, and it
        # states a figure. It is the FUND's figure about the fund's own
        # position, so it validates nothing — a distinct status, because
        # "nobody has said" and "only the audited party has said" send an
        # auditor to different places.
        #
        # This case is at FY2024, not FY2025. It was written at FY2025 while
        # the FY2024 memo's reliance window stood open, which put the memo in
        # scope a year after it speaks. The window is closed again on the
        # sentence's own subject — "THE INTEREST will be re-measured", a
        # statement about the memo, not about the rate — so FY2025 has no
        # applicable evidence at all and the status that belongs there is
        # `not_derivable`.
        #
        # Both rows are pinned deliberately. The distinction this case exists
        # for is "only the audited party has said" versus "nobody has said",
        # and asserting one without the other lets the pair collapse the moment
        # a window moves again.
        ("moonfare", "2024-12-31", None, "management_carrying_value"),
        ("moonfare", "2025-12-31", None, "not_derivable"),
        ("anthropic", "2025-12-31", None, "not_derivable"),
        ("because_market", "2025-12-31", None, "not_derivable"),
        ("mom_project", "2025-12-31", None, "not_derivable"),
    ]:
        r = row(snap, h, dt)
        check(f"{h} validated_amount", r["validated_amount"], val)
        check(f"{h} derivation_status", r["derivation_status"], st)
    # Distinct reasons matter: Anthropic HAS applicable evidence, it just has no
    # price in it. Because Market has no evidence at all.
    check(
        "anthropic reason",
        row(snap, "anthropic", "2025-12-31")["derivation_reason"],
        "NO_PRICE_IN_EVIDENCE",
    )
    check(
        "because_market reason",
        row(snap, "because_market", "2025-12-31")["derivation_reason"],
        "NO_APPLICABLE_EVIDENCE",
    )
    # Because Market's arithmetic reproduces from the tracker (625,000 x $1.60)
    # yet is not derivable. Reproducible != supported.
    check(
        "reported still present while non-derivable",
        row(snap, "because_market", "2025-12-31")["reported_amount"],
        "1000000",
    )

    print("\n── Q1-3: supersession is claim-scoped, both directions ──")
    # r6 asserted only fluidstack_b_cap survived. That was the defect: the
    # Series A claim prices a class 7GC still holds, so both must coexist.
    check(
        "independent claims coexist, in the order the evidence arose",
        row(snap, "fluidstack", "2025-12-31")["requirements"]["R2"]["relied_on"],
        ["fluidstack_a_spa", "fluidstack_a2_ref", "fluidstack_b_cap"],
    )
    check(
        "earlier claim survives when it is the latest applicable",
        row(snap, "fluidstack", "2024-12-31")["requirements"]["R2"]["relied_on"],
        ["fluidstack_a_spa"],
    )
    check(
        "same-claim documents corroborate, neither is dropped, both in date order",
        row(snap, "dream", "2025-12-31")["requirements"]["R2"]["relied_on"],
        ["dream_b_cap", "dream_close_email"],
    )

    print("\n── Q1-8: contradictory claims produce `conflicting` end-to-end ──")
    o = synth(
        documents={
            "d1": {**SYNTH_BASE["documents"]["d1"]},
            "d2": {
                **SYNTH_BASE["documents"]["d1"],
                "date": "2025-07-01",
                "applicable_from": "2025-07-01",
                "pps": "12.00",
            },
        },
        evidence_links=[
            {"holding": "h", "requirement": "R1", "document": "d1"},
            {"holding": "h", "requirement": "R2", "document": "d1"},
            {"holding": "h", "requirement": "R2", "document": "d2"},
        ],
    )
    r = o.run()["rows"][0]
    check("R2 conflicting", r["requirements"]["R2"]["verdict"], "conflicting")
    check("row conflicting", r["row_verdict"], "conflicting")
    check("names the claim", r["requirements"]["R2"]["contradicted_claims"], ["h/price"])
    # A recorded resolution clears it; an unrelated one does not.
    o2 = synth(
        documents=o.docs,
        evidence_links=o.links,
        claim_resolutions=[{"holding": "h", "claim": "h/price"}],
    )
    check(
        "a bound resolution clears it",
        o2.run()["rows"][0]["requirements"]["R2"]["verdict"] != "conflicting",
        True,
    )
    o3 = synth(
        documents=o.docs,
        evidence_links=o.links,
        claim_resolutions=[{"holding": "other", "claim": "h/price"}],
    )
    check(
        "an unrelated resolution does not",
        o3.run()["rows"][0]["requirements"]["R2"]["verdict"],
        "conflicting",
    )

    print("\n── Q2-2: the positive approval branch ──")
    base = synth()
    t0 = base.run()["totals"][0]
    check(
        "fully supported but unapproved is blocked",
        t0["approved_blocked_by"],
        "no_valuation_approval",
    )
    check("… and reports no approved total", t0["approved_fair_value_total"], None)
    _fp = synth().current_fingerprint("h", date(2025, 12, 31))
    ok = synth(valuation_approvals=[{"holding": "h", "date": "2025-12-31", **_fp}])
    t1 = ok.run()["totals"][0]
    check("approved once every held mark is approved", t1["approved_fair_value_total"], "1000")
    check("… with nothing blocking", t1["approved_blocked_by"], None)
    # Two held marks, one approved: V3 requires EVERY held member.
    two = synth(
        holdings={
            "h": {"fund": "f", "position_type": "direct_equity"},
            "h2": {"fund": "f", "position_type": "direct_equity"},
        },
        lots=SYNTH_BASE["lots"] + [{**SYNTH_BASE["lots"][0], "id": "l2", "holding": "h2"}],
        mark_observations={"h": {"p1": "1000"}, "h2": {"p1": "1000"}},
        documents={
            "d1": SYNTH_BASE["documents"]["d1"],
            "d2": {**SYNTH_BASE["documents"]["d1"], "holding": "h2", "claim": "h2/price"},
        },
        evidence_links=[{"holding": "h", "requirement": r, "document": "d1"} for r in ("R1", "R2")]
        + [{"holding": "h2", "requirement": r, "document": "d2"} for r in ("R1", "R2")],
        support_observations={
            "h": SYNTH_BASE["support_observations"]["h"],
            "h2": SYNTH_BASE["support_observations"]["h"],
        },
        tracker_totals={"f": {"p1": "2000"}},
        valuation_approvals=[{"holding": "h", "date": "2025-12-31"}],
    )
    two.p["valuation_approvals"] = [
        {"holding": "h", "date": "2025-12-31", **two.current_fingerprint("h", date(2025, 12, 31))}
    ]
    t2 = two.run()["totals"][0]
    check("a partial approval set still blocks", t2["approved_blocked_by"], "no_valuation_approval")
    check("and names the unapproved mark", t2["unapproved_marks"], ["h2"])

    print("\n── Q1-4 / Q2-3: decisions are scoped and typed ──")
    draft = synth(
        management_assessments=[{"holding": "h", "date": "2025-12-31", "status": "draft"}]
    )
    check(
        "a draft assessment does not close R3 (n/a here, but status is read)",
        "status" in str(draft.assessments[0]),
        True,
    )
    # Corpus proof: Roofstock's calibration must stay open against a draft.
    rd = Oracle(HERE / "primitives.yaml")
    rd.assessments = [{"holding": "roofstock", "date": "2025-12-31", "status": "draft"}]
    check(
        "draft leaves Roofstock R3 missing",
        rd.r3("roofstock", date(2025, 12, 31), "fund_i")["verdict"],
        "missing",
    )
    rd.assessments = [
        {
            "holding": "roofstock",
            "date": "2025-12-31",
            "status": "approved",
            **rd.current_fingerprint("roofstock", date(2025, 12, 31)),
        }
    ]
    check(
        "approved AND correctly fingerprinted closes it",
        rd.r3("roofstock", date(2025, 12, 31), "fund_i")["verdict"],
        "sufficient",
    )
    # One holding's cross-class decision must not clear another's.
    pd_ = Oracle(HERE / "primitives.yaml")
    pd_.policy_decisions = [{"holding": "dream", "date": "2025-12-31"}]
    check(
        "a scoped decision does not leak to Mom Project",
        "CROSS_CLASS_POLICY_DECISION_REQUIRED"
        in pd_.r2("mom_project", date(2025, 12, 31))["reasons"],
        True,
    )
    check(
        "… and does clear the holding it names",
        "CROSS_CLASS_POLICY_DECISION_REQUIRED"
        not in pd_.r2("dream", date(2025, 12, 31))["reasons"],
        True,
    )

    print("\n── Q1-5 / Q2-4: R4 covers every realised lot ──")
    multi = synth(
        lots=[
            {**SYNTH_BASE["lots"][0], "id": "r1", "realized": "2025-06-15"},
            {**SYNTH_BASE["lots"][0], "id": "r2", "security_class": "sb", "realized": "2025-08-15"},
        ],
        mark_observations={"h": {}},
        tracker_totals={"f": {"p1": "0"}},
        evidence_links=[{"holding": "h", "requirement": "R4", "document": "d1"}],
    )
    r4 = multi.run()["rows"][0]["requirements"]["R4"]
    check("both realised lots assessed", sorted(r4["events"]), ["r1", "r2"])
    # d1 prices class `sa` only, so lot r2 has no covering document.
    check("uncovered lot drags the verdict down", r4["verdict"], "missing")
    check("per-lot detail retained", r4["per_lot"]["r1"], "sufficient")

    print("\n── Q1-6: a realised-only gap must not taint the held total ──")
    corpus = Oracle(HERE / "primitives.yaml")
    corpus.links = [lt for lt in corpus.links if lt["requirement"] != "R4"]
    t = corpus.run()["totals"][1]
    check(
        "Jackpocket's R4 gap leaves the held total intact",
        t["held_at_date_reported_total"],
        "10548515",
    )
    check("held-input blockers unchanged", t["approved_blocked_by"], "unsupported_rows")
    check(
        "but it is still a packet gap", t["packet_gap_row_count"] > t["unsupported_row_count"], True
    )

    print("\n── Q1-7: one covered class does not make a multi-lot holding sufficient ──")
    partial = synth(
        lots=SYNTH_BASE["lots"] + [{**SYNTH_BASE["lots"][0], "id": "l2", "security_class": "sb"}],
        mark_observations={"h": {"p1": "2000"}},
        tracker_totals={"f": {"p1": "2000"}},
    )
    pr = partial.run()["rows"][0]["requirements"]["R2"]
    check("verdict capped at partial", pr["verdict"], "partial")
    check("reason names the uncovered class", "UNCOVERED_SECURITY_CLASS" in pr["reasons"], True)

    print("\n── Q1-9: F5 and lineage-only output ──")
    b = snap["basis_checks"]
    check(
        "exactly the two Fluidstack quarters",
        [(x["holding"], x["period"]) for x in b],
        [("fluidstack", "f2_25q2"), ("fluidstack", "f2_25q3")],
    )
    check("both lineage-only", {x["audit_scope"] for x in b}, {"lineage_only"})
    check("cost basis 2,500,000", b[0]["cost_basis"], "2500000")
    check("last-round basis 3,000,000", b[0]["last_round_basis"], "3000000")
    check("variance 500,000", b[0]["variance"], "500000")
    cv = snap["change_view"]
    check(
        "lineage periods appear in the change view",
        sum(1 for x in cv if x["audit_scope"] == "lineage_only"),
        38,
    )
    check(
        "26Q1 present and unchanged",
        [x["changed"] for x in cv if x["period"] == "f2_26q1"],
        [False] * 8,
    )

    print("\n── Q1-10: declared counts are asserted ──")
    bad = synth()
    bad.p["meta"]["evidence_records"] = 99
    try:
        bad._validate()
        check("a wrong record count raises", False, True)
    except OracleError:
        check("a wrong record count raises", True, True)

    print("\n── Q1-1/Q1-5: independent claims coexist; derivation is per class ──")
    two_class = synth(
        lots=[SYNTH_BASE["lots"][0], {**SYNTH_BASE["lots"][0], "id": "l2", "security_class": "sb"}],
        documents={
            "da": {
                **SYNTH_BASE["documents"]["d1"],
                "claim": "h/sa_price",
                "priced_class": "sa",
                "pps": "10.00",
            },
            "db": {
                **SYNTH_BASE["documents"]["d1"],
                "claim": "h/sb_price",
                "priced_class": "sb",
                "pps": "20.00",
                "date": "2025-07-01",
                "applicable_from": "2025-07-01",
            },
        },
        evidence_links=[
            {"holding": "h", "requirement": r, "document": doc}
            for r in ("R1", "R2")
            for doc in ("da", "db")
        ],
        mark_observations={"h": {"p1": "3000"}},
        tracker_totals={"f": {"p1": "3000"}},
    )
    r = two_class.run()["rows"][0]
    # 100 x $10 + 100 x $20 = 3,000. Applying one price to both gives 4,000.
    check("both claims retained, older first", r["requirements"]["R2"]["relied_on"], ["da", "db"])
    check("derives 3,000, not 4,000", r["validated_amount"], "3000")
    check("per-class lineage recorded", len(r["derivation_lineage"]), 2)
    check(
        "no cross-class propagation",
        [x["cross_class"] for x in r["derivation_lineage"]],
        [False, False],
    )
    # A newer version of the SAME class supersedes the older one.
    versioned = synth(
        documents={
            "old": {**SYNTH_BASE["documents"]["d1"], "claim": "h/p1"},
            "new": {
                **SYNTH_BASE["documents"]["d1"],
                "claim": "h/p2",
                "date": "2025-09-01",
                "applicable_from": "2025-09-01",
                "pps": "11.00",
            },
        },
        evidence_links=[
            {"holding": "h", "requirement": r_, "document": doc}
            for r_ in ("R1", "R2")
            for doc in ("old", "new")
        ],
        mark_observations={"h": {"p1": "1100"}},
        tracker_totals={"f": {"p1": "1100"}},
    )
    check(
        "same-class newer claim supersedes older",
        versioned.run()["rows"][0]["requirements"]["R2"]["relied_on"],
        ["new"],
    )
    # Corpus: cross-class marks are NOT derivable without an authorising decision.
    check(
        "dream not derivable",
        row(snap, "dream", "2025-12-31")["derivation_reason"],
        "NO_PRICE_FOR_CLASS:series_a1",
    )
    # Lucra's tracker applies the A-2 price to A-1 shares; per class it is 1.5M.
    lu = row(snap, "lucra", "2025-12-31")
    check(
        "lucra derives 1,500,000 against a reported 2,250,000",
        (lu["validated_amount"], lu["reported_amount"]),
        ("1500000", "2250000"),
    )
    check("and the mismatch is flagged", lu["validated_matches_reported"], False)
    # A cited policy decision authorises propagation — and is recorded as such.
    auth = Oracle(HERE / "primitives.yaml")
    auth.policy_decisions = [{"holding": "dream", "date": "2025-12-31"}]
    v, st, _, lin = auth.validated_amount(
        "dream",
        date(2025, 12, 31),
        [(n, auth.docs[n]) for n in auth.r2("dream", date(2025, 12, 31))["relied_on"]],
        True,
    )
    check("authorised propagation derives 5,000,000", fmt_(v), "5000000")
    check("and records it as cross-class", [x["cross_class"] for x in lin], [True])

    print("\n── Q1-2: approvals bind their full identity ──")
    base = synth()
    fp = base.current_fingerprint("h", date(2025, 12, 31))
    good = synth(valuation_approvals=[{"holding": "h", "date": "2025-12-31", **fp}])
    check(
        "a correctly fingerprinted approval is accepted",
        good.run()["totals"][0]["approved_fair_value_total"],
        "1000",
    )
    for field in ("mark_revision", "evidence_set_hash", "policy_version"):
        bad = synth(
            valuation_approvals=[{"holding": "h", "date": "2025-12-31", **{**fp, field: "wrong"}}]
        )
        check(
            f"a stale {field} is rejected",
            bad.run()["totals"][0]["approved_blocked_by"],
            "no_valuation_approval",
        )
    nofp = synth(valuation_approvals=[{"holding": "h", "date": "2025-12-31"}])
    check(
        "an approval with no fingerprint is rejected",
        nofp.run()["totals"][0]["approved_blocked_by"],
        "no_valuation_approval",
    )

    print("\n── INV-13: a validated/reported disagreement blocks the approved total ──")
    # The reported mark is 9,999 while 100 shares at $10.00 derive 1,000. R1-R5
    # are all satisfied, so nothing about the EVIDENCE is missing — the figure
    # itself is wrong. Before this guard the row was approved and the approved
    # total carried the 9,999.
    _obs, _trk = {"h": {"p1": "9999"}}, {"f": {"p1": "9999"}}
    fp_mm = synth(mark_observations=_obs, tracker_totals=_trk).current_fingerprint(
        "h", date(2025, 12, 31)
    )
    mm = synth(
        mark_observations=_obs,
        tracker_totals=_trk,
        valuation_approvals=[{"holding": "h", "date": "2025-12-31", **fp_mm}],
    ).run()
    check("the evidence is still sufficient", mm["rows"][0]["row_verdict"], "sufficient")
    check("reported and validated disagree", mm["rows"][0]["validated_matches_reported"], False)
    check(
        "the disagreement itself blocks approval",
        mm["totals"][0]["approved_blocked_by"],
        "validated_reported_mismatch",
    )
    check("no approved total is stated", mm["totals"][0]["approved_fair_value_total"], None)
    check("and the mark is named", mm["totals"][0]["mismatched_marks"], ["h"])
    # The corpus carries TWO such rows. This comment used to say "exactly one",
    # and that was never true — Fluidstack's A-2 evidence was relied on for
    # nothing, so its derivation had no price for a class the fund holds and
    # reported `unconfirmable` instead of a 2,500,000-against-6,000,000
    # mismatch. An answer key that counts the instances it can see, and calls
    # that the total, is the same error one level up from the code.
    #
    # Both are blocked first for unrelated reasons, which is what kept them
    # latent, so the packet total must NAME them or the guard has nothing to
    # fail against.
    f2_25 = next(t for t in snap["totals"] if t["fund"] == "fund_ii" and t["date"] == "2025-12-31")
    check(
        "both corpus mismatches reach the packet total",
        f2_25["mismatched_marks"],
        ["fluidstack", "lucra"],
    )
    # An approved total is summed from VALIDATED amounts, so a held mark with no
    # validated amount cannot be approved either — there is nothing to sum, and
    # falling back to the reported figure is exactly the substitution above.
    _nopx = {k: v for k, v in SYNTH_BASE["documents"]["d1"].items() if k != "pps"}
    fp_nd = synth(documents={"d1": _nopx}).current_fingerprint("h", date(2025, 12, 31))
    nd = synth(
        documents={"d1": _nopx},
        valuation_approvals=[{"holding": "h", "date": "2025-12-31", **fp_nd}],
    ).run()
    check(
        "evidence sufficient, price absent",
        nd["rows"][0]["derivation_reason"],
        "NO_PRICE_IN_EVIDENCE",
    )
    check(
        "a reported figure with no validated amount is not approvable",
        nd["totals"][0]["approved_blocked_by"],
        "validated_amount_not_derivable",
    )
    check(
        "so the reported figure is not blessed", nd["totals"][0]["approved_fair_value_total"], None
    )

    print("\n── INV-10: an approval is bound to CONTENT, not to names ──")
    # The fingerprint used to be `holding@date` plus a pipe-joined list of
    # document ids. Editing a document's price in place left all three
    # components identical, so a stale approval kept passing.
    fp0 = synth().current_fingerprint("h", date(2025, 12, 31))
    repriced = copy.deepcopy(SYNTH_BASE["documents"])
    repriced["d1"]["pps"] = "12.00"
    tampered = synth(
        documents=repriced,
        mark_observations={"h": {"p1": "1200"}},
        tracker_totals={"f": {"p1": "1200"}},
        valuation_approvals=[{"holding": "h", "date": "2025-12-31", **fp0}],
    )
    check(
        "the evidence set is the same document",
        tampered.r2("h", date(2025, 12, 31))["relied_on"],
        ["d1"],
    )
    check(
        "but its content moved the hash",
        tampered.current_fingerprint("h", date(2025, 12, 31))["evidence_set_hash"]
        != fp0["evidence_set_hash"],
        True,
    )
    check(
        "so the approval taken before the edit no longer holds",
        tampered.run()["totals"][0]["approved_blocked_by"],
        "no_valuation_approval",
    )
    moved = synth(mark_observations={"h": {"p1": "1001"}}, tracker_totals={"f": {"p1": "1001"}})
    check(
        "a changed mark figure alone moves the mark revision",
        moved.current_fingerprint("h", date(2025, 12, 31))["mark_revision"] != fp0["mark_revision"],
        True,
    )
    relaxed = copy.deepcopy(SYNTH_BASE["policy_matrix"])
    for cell in relaxed:
        if cell["req"] == "R2":
            cell["verdict"] = "partial"
    check(
        "a changed policy input moves the policy component",
        synth(policy_matrix=relaxed).current_fingerprint("h", date(2025, 12, 31))["policy_version"]
        != fp0["policy_version"],
        True,
    )

    print("\n── Q1-3: V9 realisation arithmetic ──")
    rc = snap["realization_checks"][0]
    check("500,000 x $6.20 = 3,100,000", rc["gross"], "3100000")
    check("net equals gross with zero deductions", rc["net"], "3100000")
    check("passes", rc["check"], "pass")
    bad_net = Oracle(HERE / "primitives.yaml")
    bad_net.lots = copy.deepcopy(bad_net.lots)
    for lt in bad_net.lots:
        if lt["id"] == "jack_1":
            lt["realization"]["escrow"] = "100000"
    check(
        "right gross, wrong net component FAILs", bad_net.realization_checks()[0]["check"], "FAIL"
    )

    print("\n── Q1-4: V8 variance classification ──")
    cv = {c["document"]: c for c in snap["concluded_value_checks"]}
    check(
        "Moonfare's $30 is ROUNDING_VARIANCE",
        cv["moonfare_memo_23"]["classification"],
        "ROUNDING_VARIANCE",
    )
    check("an exact recomputation is EXACT", cv["moonfare_fx_24"]["classification"], "EXACT")
    check(
        "an unrecognised delta demands review",
        Oracle.classify_variance(Decimal("1000000"), Decimal("987654")),
        "UNRECOGNISED_VARIANCE_REVIEW_REQUIRED",
    )

    print("\n── Q1-6: every declared count is asserted ──")
    for key, wrong in [
        ("physical_source_files", 999),
        ("positions", 99),
        ("lot_count", 99),
        ("packet_periods", 99),
    ]:
        bad = Oracle(HERE / "primitives.yaml")
        bad.p = copy.deepcopy(bad.p)
        bad.p["meta"][key] = wrong
        try:
            bad._validate()
            check(f"wrong {key} raises", False, True)
        except OracleError:
            check(f"wrong {key} raises", True, True)

    print("\n── Q1-7: authority lives on the claim, not the artifact ──")
    jio = [
        d_
        for n, d_ in Oracle(HERE / "primitives.yaml").docs.items()
        if d_["source_file"] == "Jio statement 2025.pdf"
    ]
    check("one artifact carries two claims", len(jio), 2)
    # This asserted DIFFERENT classes, and passed only because the delivery
    # email was filed `company_communication` — the exact mis-tier INV-15 names.
    # The anchor was locking the defect in. Authority is read from the speaker,
    # and Meridian speaks as Administrator in both.
    check(
        "both read from the speaker, not the envelope",
        sorted(x["source_class"] for x in jio),
        ["administrator_statement", "administrator_statement"],
    )
