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


# ── INV-17 · cross-class pricing is derived, never declared ──────────────
def _price_series_c_off_series_b(conn: Conn, seed: dict[str, str], with_policy: bool) -> None:
    """Hold series_b, price the mark from a series_c claim, then approve it."""
    xclaim = f"{seed['cl']}_c"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, priced_class, price_per_share)"
        " values (%s, %s, %s, 'k', 'company_cap_table', 'executed',"
        " '2025-06-30', '2025-01-01', 'series_c', 9.0)",
        (xclaim, seed["dv"], seed["h"]),
    )
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 9000, 'USD', 9000, 'USD', 'derivable', 'priced off series_c')"
        " returning id",
        (seed["h"], seed["p"]),
    )
    aid = make_assessment(conn, seed, mid, "R2")
    conn.execute(
        "insert into evidence_link (assessment_id, claim_id) values (%s, %s)", (aid, xclaim)
    )
    if with_policy:
        conn.execute(
            "insert into valuation_policy_decision (holding_id, period_id, from_class,"
            " to_class, rationale, citation_quote, policy_version)"
            " values (%s, %s, 'series_c', 'series_a', 'pref stack equivalent', 'q', 'v1')",
            (seed["h"], seed["p"]),
        )
    did = returned_id(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, %s, 'v1', 'a') returning id",
        (str(mid), mid),
    )
    conn.execute(
        "insert into decision_evidence (decision_id, assessment_id, mark_id) values (%s, %s, %s)",
        (did, aid, mid),
    )
    # Fires the deferred constraint triggers without committing, so the
    # transaction still rolls back and no rows survive in append-only tables.
    conn.execute("set constraints all immediate")


def test_cross_class_pricing_without_a_cited_policy_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Derived from the evidence actually cited, not from a flag. An earlier fix
    gated this on `mark.cross_class`, which the writer could simply leave false
    — a guard the writer can decline to trip is not a guard."""
    with pytest.raises(psycopg.Error) as exc:
        _price_series_c_off_series_b(conn, seed, with_policy=False)
    conn.rollback()
    assert "INV-17" in str(exc.value)


def test_cross_class_pricing_with_a_cited_policy_is_allowed(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The positive path. Without it the trigger could reject everything and the
    negative test above would still pass."""
    _price_series_c_off_series_b(conn, seed, with_policy=True)


def test_a_claim_that_prices_without_stating_a_class_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The INV-17 gate filtered `priced_class is not null`, so a cap-table
    extract carrying a price with the class left implicit skipped it entirely.
    Unstated is not "same class" — it is unknowable, and unknowable must refuse.
    """
    noclass = f"{seed['cl']}_n"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, price_per_share)"
        " values (%s, %s, %s, 'k', 'company_cap_table', 'executed',"
        " '2025-06-30', '2025-01-01', 9.0)",
        (noclass, seed["dv"], seed["h"]),
    )
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 9000, 'USD', 9000, 'USD', 'derivable', 'x') returning id",
        (seed["h"], seed["p"]),
    )
    aid = make_assessment(conn, seed, mid, "R2")
    conn.execute(
        "insert into evidence_link (assessment_id, claim_id) values (%s, %s)", (aid, noclass)
    )
    did = returned_id(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, %s, 'v1', 'a') returning id",
        (str(mid), mid),
    )
    conn.execute(
        "insert into decision_evidence (decision_id, assessment_id, mark_id) values (%s, %s, %s)",
        (did, aid, mid),
    )
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("set constraints all immediate")
    conn.rollback()
    assert "states no priced_class" in str(exc.value)


def test_evidence_cannot_be_attached_after_the_decision_is_sealed(
    conn: Conn, seed: dict[str, str]
) -> None:
    """An approval that passed its gates could still grow evidence afterwards,
    because both deferred triggers fire on the decision insert only. New
    evidence is a new assertion about value and needs a new decision."""
    mid = make_mark(conn, seed)
    aid = make_assessment(conn, seed, mid)
    did = returned_id(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " mark_id, policy_version, actor_id)"
        " values ('valuation', 'approved', 'mark', %s, %s, 'v1', 'a') returning id",
        (str(mid), mid),
    )
    conn.execute(
        "insert into decision_evidence (decision_id, assessment_id, mark_id) values (%s, %s, %s)",
        (did, aid, mid),
    )
    conn.execute("set constraints all immediate")
    conn.commit()  # the decision's own transaction ends here

    later = make_assessment(conn, seed, mid, "R2")
    assert "is sealed" in rejects(
        conn,
        "insert into decision_evidence (decision_id, assessment_id, mark_id) values (%s, %s, %s)",
        (did, later, mid),
    )


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
