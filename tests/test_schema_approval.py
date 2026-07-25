"""Approval, promotion and cross-class guards.

Split from `test_schema_invariants.py` at the file-size budget. These are the
paths a cross-family review defeated after the first fix: a composite foreign
key is MATCH SIMPLE by default, so leaving any discriminator NULL skipped the
reference entirely, and a CHECK that evaluates to NULL passes — NULL is not
FALSE. Each test drives the exact defeat and asserts the database now refuses it.
"""

from __future__ import annotations

import psycopg
import pytest

from tests.schema_helpers import (
    DSN,
    Conn,
    make_assessment,
    make_fact,
    make_mark,
    rejects,
    returned_id,
)

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


def assess(
    conn: Conn,
    seed: dict[str, str],
    mark_id: int,
    code: str = "R1",
    verdict: str = "sufficient",
    policy: str = "v1",
    claim: str | None = None,
) -> int:
    """A requirement, its assessment, and the claim the assessment rests on.

    `make_assessment` in the shared helpers hard-codes `sufficient` at `v1` and
    links nothing — which is precisely the shape 0003 refuses for R1 and R2, so
    the verdict, the policy version and the link have to be reachable from a
    test to drive the rejections.
    """
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, %s, true) returning id",
        (seed["h"], seed["p"], code),
    )
    aid = returned_id(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, %s, %s) returning id",
        (req, mark_id, seed["h"], seed["p"], verdict, policy),
    )
    if claim is not None:
        conn.execute(
            "insert into evidence_link (assessment_id, claim_id) values (%s, %s)", (aid, claim)
        )
    return aid


def approve_valuation(conn: Conn, mark_id: int, cited: list[int], policy: str = "v1") -> int:
    """Approve a mark and cite an evidence set. The deferred triggers do not fire
    here — the caller decides when, with `set constraints all immediate`."""
    did = returned_id(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, %s, %s, 'a') returning id",
        (str(mark_id), mark_id, policy),
    )
    for aid in cited:
        conn.execute(
            "insert into decision_evidence (decision_id, assessment_id, mark_id)"
            " values (%s, %s, %s)",
            (did, aid, mark_id),
        )
    return did


def realise_a_lot(conn: Conn, seed: dict[str, str], on: str = "2025-05-20") -> None:
    """A second lot, realised at `on`. The seeded lot is never realised, so every
    other test in this file stays outside R4's applicability window."""
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps, cost_amount,"
        " cost_currency, acquired_date, realized_date)"
        " values (%s, %s, 'series_a', 500, 2.00, 1000, 'USD', '2024-01-01', %s)",
        (f"{seed['lot']}_r", seed["h"], on),
    )


def refused_at_commit(conn: Conn) -> str:
    """Fire the deferred triggers without committing, and return the refusal."""
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("set constraints all immediate")
    conn.rollback()
    return str(exc.value)


def test_null_discriminators_cannot_smuggle_a_promotion(conn: Conn, seed: dict[str, str]) -> None:
    """MATCH SIMPLE: a composite FK is skipped entirely when ANY column is NULL,
    and `type = NULL and status = NULL` makes the approved-transcription CHECK
    evaluate to NULL rather than FALSE. Both let this insert through until
    fact_promoter_all_or_nothing and MATCH FULL closed it — with `promoted_by`
    pointing at a decision id that does not even exist."""
    assert "fact_promoter_all_or_nothing" in rejects(
        conn,
        "insert into extracted_fact (claim_id, state, field_name, value_text,"
        " citation_quote, span_start, span_end, promoted_by)"
        " values (%s, 'canonical', 'pps', '8.00', 'q', 0, 1, 999999)",
        (seed["cl"],),
    )


def test_null_fact_state_cannot_smuggle_a_candidate_into_a_figure(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The same MATCH SIMPLE defeat on the derived-figure path: omit fact_state
    and a candidate fact feeds a figure that can become a validated amount."""
    fid = make_fact(conn, seed)
    conn.execute(
        "insert into derived_figure (id, label, operator, amount, currency, unit)"
        " values (9500, 'total', 'sum', 10, 'USD', 'money')"
    )
    assert "input_fact_state_present" in rejects(
        conn,
        "insert into derived_figure_input (figure_id, fact_id, ordinal) values (9500, %s, 1)",
        (fid,),
    )


def test_approval_cannot_cite_evidence_belonging_to_another_mark(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Requiring merely that *some* evidence row exists let an approval of one
    mark cite assessments belonging to a different mark."""
    m1 = make_mark(conn, seed)
    other = returned_id(
        conn,
        "insert into reporting_period values (%s, %s, '2024-12-31', 'packet', 'FY2024')"
        " returning 1",
        (f"{seed['p']}_x", seed["fund"]),
    )
    assert other == 1
    m2 = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 500, 'USD', 'not_derivable', 'x') returning id",
        (seed["h"], f"{seed['p']}_x"),
    )
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true) returning id",
        (seed["h"], f"{seed['p']}_x"),
    )
    a2 = returned_id(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, 'sufficient', 'v1') returning id",
        (req, m2, seed["h"], f"{seed['p']}_x"),
    )
    dec = returned_id(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, %s, 'v1', 'a') returning id",
        (str(m1), m1),
    )
    assert "decision_evidence" in rejects(
        conn,
        "insert into decision_evidence (decision_id, assessment_id, mark_id) values (%s, %s, %s)",
        (dec, a2, m2),
    )


# ── INV-16 / INV-3 · a link must be applicable, and labelled honestly ────
def test_claim_cannot_be_linked_outside_its_applicability_window(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Capsule's memo forbids later reliance. Every date field can be correct
    and the link still invalid."""
    mid = make_mark(conn, seed)
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true) returning id",
        (seed["h"], seed["p"]),
    )
    aid = returned_id(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, 'sufficient', 'v1') returning id",
        (req, mid, seed["h"], seed["p"]),
    )
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, applicable_to)"
        " values ('expired', %s, %s, 'k', 'third_party_valuation_memo', 'executed',"
        " '2022-01-01', '2022-01-01', '2022-12-31')",
        (seed["dv"], seed["h"]),
    )
    assert "INV-16" in rejects(
        conn,
        "insert into evidence_link (assessment_id, claim_id) values (%s, 'expired')",
        (aid,),
    )


def test_is_subsequent_must_agree_with_the_dates(conn: Conn, seed: dict[str, str]) -> None:
    """The seeded claim is issued 2025-06-30, before the 2025-12-31 measurement
    date, so asserting is_subsequent is a lie the database must refuse."""
    mid = make_mark(conn, seed)
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true) returning id",
        (seed["h"], seed["p"]),
    )
    aid = returned_id(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, 'sufficient', 'v1') returning id",
        (req, mid, seed["h"], seed["p"]),
    )
    assert "INV-3" in rejects(
        conn,
        "insert into evidence_link (assessment_id, claim_id, is_subsequent) values (%s, %s, true)",
        (aid, seed["cl"]),
    )


def _link_target(conn: Conn, seed: dict[str, str]) -> int:
    """An R1 assessment on a fresh mark, ready to have a claim linked to it."""
    mid = make_mark(conn, seed)
    req = returned_id(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true) returning id",
        (seed["h"], seed["p"]),
    )
    return returned_id(
        conn,
        "insert into evidence_assessment (requirement_id, mark_id, holding_id, period_id,"
        " verdict, policy_version) values (%s, %s, %s, %s, 'sufficient', 'v1') returning id",
        (req, mid, seed["h"], seed["p"]),
    )


def _delivered_late_claim(conn: Conn, seed: dict[str, str]) -> str:
    """Issued before the measurement date, delivered to the fund after it.

    The live shape 0004 was written for: Jio's FY2025 support carries a document
    date inside the year and reached the fund on 30 January 2026.
    """
    cid = f"{seed['cl']}_late"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, received_date, applicable_from)"
        " values (%s, %s, %s, 'k', 'third_party_valuation_memo', 'executed',"
        " '2025-11-30', '2026-01-30', '2025-01-01')",
        (cid, seed["dv"], seed["h"]),
    )
    return cid


def test_subsequent_evidence_is_decided_by_delivery_not_by_the_issue_date(
    conn: Conn, seed: dict[str, str]
) -> None:
    """SPEC V11 / INV-3 · `coalesce(received_date, issued_date)`, migration 0004.

    Nothing in this repository set `received_date` on any claim, so every claim
    fell through to the issue date and the coalesce was never evaluated with two
    different dates in it. Reverting 0004's predicate to `issued_date` alone —
    deleting the whole migration's effect — left all 53 schema tests green:
    coverage that reads as coverage and defends nothing.

    A document written inside the year and delivered after it IS subsequent
    evidence. Claiming otherwise on the strength of its letterhead date is how a
    post-period-end fact gets presented as contemporaneous support.
    """
    cid = _delivered_late_claim(conn, seed)
    # issued 2025-11-30 <= 2025-12-31, but delivered 2026-01-30 > 2025-12-31.
    assert "INV-3" in rejects(
        conn,
        "insert into evidence_link (assessment_id, claim_id, is_subsequent) values (%s, %s, false)",
        (_link_target(conn, seed), cid),
    )


def test_a_claim_delivered_after_the_measurement_date_may_be_marked_subsequent(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The direction that must survive it.

    A rule reading only `issued_date` refuses this exact row — the claim looks
    contemporaneous — so without this assertion the guard above could be
    satisfied by a predicate that rejects both answers.
    """
    conn.execute(
        "insert into evidence_link (assessment_id, claim_id, is_subsequent) values (%s, %s, true)",
        (_link_target(conn, seed), _delivered_late_claim(conn, seed)),
    )
    conn.rollback()


def test_evidence_cannot_be_attached_after_the_decision_is_sealed(
    conn: Conn, seed: dict[str, str]
) -> None:
    """An approval that passed its gates could still grow evidence afterwards,
    because both deferred triggers fire on the decision insert only. New
    evidence is a new assertion about value and needs a new decision."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=seed["cl"])
    did = approve_valuation(conn, mid, [r1, r2])
    conn.execute("set constraints all immediate")
    conn.commit()  # the decision's own transaction ends here

    later = make_assessment(conn, seed, mid, "R3")
    assert "is sealed" in rejects(
        conn,
        "insert into decision_evidence (decision_id, assessment_id, mark_id) values (%s, %s, %s)",
        (did, later, mid),
    )


# ── INV-10 / SPEC 7.1 · the evidence set must be COMPLETE ────────────────
# Every one of these committed against the live database before 0003: requiring
# that *an* evidence row exists is satisfied by a single row, whatever it says.
def test_approval_without_an_r1_requirement_at_all_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The proven defect: one R2 assessment, no R1 anywhere, and the approval
    committed. Completeness is measured against `pbc_requirement`, so a holding
    whose R1 row was never created cannot pass vacuously."""
    mid = make_mark(conn, seed)
    r2 = assess(conn, seed, mid, "R2", claim=seed["cl"])
    approve_valuation(conn, mid, [r2])
    err = refused_at_commit(conn)
    assert "valuation_approval_needs_complete_evidence" in err
    assert "carries no R1 requirement row" in err


def test_approval_citing_an_insufficient_assessment_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """`insufficient` is a verdict the packet reports as unsupported. An approval
    resting on one asserts support the assessment itself denies."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", verdict="insufficient", claim=seed["cl"])
    approve_valuation(conn, mid, [r1, r2])
    err = refused_at_commit(conn)
    assert "valuation_approval_needs_complete_evidence" in err
    assert "cites no sufficient R2 assessment" in err


def test_approval_citing_an_assessment_from_an_older_policy_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-10 · an approval binds an immutable input AND a policy snapshot. A v1
    decision resting on v0 judgements binds two different policies and reports
    only one of them."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", policy="v0", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", policy="v0", claim=seed["cl"])
    approve_valuation(conn, mid, [r1, r2], policy="v1")
    err = refused_at_commit(conn)
    assert "valuation_approval_needs_complete_evidence" in err
    assert "at policy version v1" in err


def test_an_assessment_the_approval_does_not_cite_does_not_complete_the_set(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A sufficient R2 sitting in the table is not part of what was approved.
    Without this the completeness check could be satisfied by rows the decision
    never named, which is the hole `decision_evidence` exists to close."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    assess(conn, seed, mid, "R2", claim=seed["cl"])
    approve_valuation(conn, mid, [r1])
    assert "cites no sufficient R2 assessment" in refused_at_commit(conn)


def test_a_sufficient_requirement_that_links_no_claim_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """`sufficient` with nothing linked is support asserted against no document.
    The probe that proved this finding cited exactly such an assessment."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2")
    approve_valuation(conn, mid, [r1, r2])
    err = refused_at_commit(conn)
    assert "valuation_approval_needs_complete_evidence" in err
    assert "links no claim" in err


def test_an_inapplicable_requirement_needs_no_assessment(conn: Conn, seed: dict[str, str]) -> None:
    """The positive path, and the one that keeps the guard honest: a trigger that
    refused every approval would pass every test above. R3 is applicable=false
    here, so a complete R1/R2 set approves."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=seed["cl"])
    conn.execute(
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R3', false)",
        (seed["h"], seed["p"]),
    )
    approve_valuation(conn, mid, [r1, r2])
    conn.execute("set constraints all immediate")


def test_an_applicable_r4_left_unassessed_blocks_the_approval(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Completeness is not "R1 and R2": a conditional requirement someone marked
    applicable must be closed too, or the approval covers less than the packet
    reports."""
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=seed["cl"])
    conn.execute(
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R4', true)",
        (seed["h"], seed["p"]),
    )
    approve_valuation(conn, mid, [r1, r2])
    assert "cites no sufficient R4 assessment" in refused_at_commit(conn)


# ── SPEC 7.1 · R4 applicability is a fact about the lots ─────────────────
# Measuring completeness against the `pbc_requirement` rows that happen to exist
# made R4 optional in the one case it exists for. Proven on the live database: a
# realised lot approved on sufficient R1/R2 with no R4 row anywhere.
def test_a_realised_lot_approved_without_an_r4_requirement_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    mid = make_mark(conn, seed)
    realise_a_lot(conn, seed)
    cited = [assess(conn, seed, mid, c, claim=seed["cl"]) for c in ("R1", "R2")]
    approve_valuation(conn, mid, cited)
    err = refused_at_commit(conn)
    assert "valuation_approval_needs_complete_evidence" in err
    assert "no applicable R4 requirement row" in err


def test_an_r4_marked_inapplicable_does_not_close_a_realisation(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The row-exists form of the rule would be satisfied by the assertion it
    exists to refuse: `applicable = false` is skipped by the completeness query,
    so an R4 nobody intends to answer would complete the set."""
    mid = make_mark(conn, seed)
    realise_a_lot(conn, seed)
    conn.execute(
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R4', false)",
        (seed["h"], seed["p"]),
    )
    cited = [assess(conn, seed, mid, c, claim=seed["cl"]) for c in ("R1", "R2")]
    approve_valuation(conn, mid, cited)
    assert "no applicable R4 requirement row" in refused_at_commit(conn)


def test_a_realised_lot_with_a_sufficient_r4_approves(conn: Conn, seed: dict[str, str]) -> None:
    """The positive path. Without it the R4 rule could refuse every realisation."""
    mid = make_mark(conn, seed)
    realise_a_lot(conn, seed)
    cited = [assess(conn, seed, mid, c, claim=seed["cl"]) for c in ("R1", "R2", "R4")]
    approve_valuation(conn, mid, cited)
    conn.execute("set constraints all immediate")


def test_a_lot_realised_before_the_previous_packet_date_needs_no_r4(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The window is the oracle's: the realisation belongs to whichever packet
    period it fell in. Demanding R4 again at every later date would refuse a
    legitimate approval forever — the over-strict direction, which is as damaging
    as the permissive one and much harder to notice."""
    conn.execute(
        "insert into reporting_period values (%s, %s, '2024-12-31', 'packet', 'FY2024')",
        (f"{seed['p']}_prior", seed["fund"]),
    )
    realise_a_lot(conn, seed, on="2024-05-20")
    mid = make_mark(conn, seed)
    cited = [assess(conn, seed, mid, c, claim=seed["cl"]) for c in ("R1", "R2")]
    approve_valuation(conn, mid, cited)
    conn.execute("set constraints all immediate")


def test_management_assessment_approval_must_name_its_evidence_set(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Only the valuation limb was tested, so dropping `management_assessment`
    from the trigger's IN list would have left the suite green — a guard whose
    test cannot fail."""
    mid = make_mark(conn, seed)
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('management_assessment', 'approved', 'assessment', %s, %s, 'v1', 'a')",
        (str(mid), mid),
    )
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("set constraints all immediate")
    conn.rollback()
    assert "names no evidence set" in str(exc.value)
