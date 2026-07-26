"""INV-17 in the schema: cross-class pricing is derived, never declared.

Split from `test_schema_approval.py` at the file-size budget, the same way that
file was split from `test_schema_invariants.py`. Everything here drives one
rule — the set of security classes a holding HELD at the measurement date must
equal the set its cited fair-value evidence PRICED — and the carve-out that
lets a recorded policy decision authorise a difference.

Every rejection is paired with the acceptance it must not take with it. An
over-strict cross-class rule makes a fully evidenced multi-class holding
unapprovable, and nobody files a bug saying the database refused something it
should have refused.
"""

from __future__ import annotations

import psycopg
import pytest

from tests.schema_helpers import DSN, Conn, cite_price, make_assessment, returned_id
from tests.test_schema_approval import approve_valuation, assess

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


# ── INV-17 · cross-class pricing is derived, never declared ──────────────
def _price_series_c_off_series_b(
    conn: Conn, seed: dict[str, str], with_policy: bool, decision_policy: str = "v1"
) -> None:
    """Hold series_b, price the mark from a series_c claim, then approve it."""
    xclaim = f"{seed['cl']}_c"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, priced_class, price_per_share)"
        " values (%s, %s, %s, 'k', 'company_cap_table', 'executed',"
        " '2025-06-30', '2025-01-01', 'series_c', 8.00)",
        (xclaim, seed["dv"], seed["h"]),
    )
    cite_price(conn, xclaim)
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 9000, 'USD', 9000, 'USD', 'derivable', 'priced off series_c')"
        " returning id",
        (seed["h"], seed["p"]),
    )
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    aid = assess(conn, seed, mid, "R2", claim=xclaim)
    if with_policy:
        conn.execute(
            "insert into valuation_policy_decision (holding_id, period_id, from_class,"
            " to_class, rationale, citation_quote, policy_version)"
            " values (%s, %s, 'series_c', 'series_a', 'pref stack equivalent', 'q', %s)",
            (seed["h"], seed["p"], decision_policy),
        )
    approve_valuation(conn, mid, [r1, aid])
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


def test_a_cross_class_decision_taken_under_a_superseded_policy_does_not_authorise(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-10 / SPEC §6.3 · an approval reads its inputs under its own policy.

    The carve-out looked `valuation_policy_decision` up by holding, period and
    class pair and never by `policy_version`, so a decision recorded under v0
    cleared a v1 approval exactly as a v1 decision did. 0003 already requires
    `ea.policy_version = new.policy_version` of every cited assessment, so the
    rule was enforced for assessments and not for decisions — one-side-only
    enforcement inside a single guard.

    The cross-class carve-out is a judgement that one class's price may stand
    for another's. That judgement belongs to the policy it was made under; a
    later policy is a different set of rules and has not made it.
    """
    with pytest.raises(psycopg.Error) as exc:
        _price_series_c_off_series_b(conn, seed, with_policy=True, decision_policy="v0")
    conn.rollback()
    assert "INV-17" in str(exc.value)


def test_only_the_fair_value_evidence_decides_which_classes_price_a_mark(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-17 · the priced set comes from R2, not from every cited claim.

    The trigger collected `priced_class` from every claim the approval cited,
    whatever requirement its assessment answered. An executed transaction
    document supporting R1 states the acquisition price per share, so it
    supplied a class the fair-value evidence never covered — and a holding whose
    R2 priced one of its two classes approved because R1 happened to mention the
    other. The series_a shares are still carried at the series_b price; INV-17
    exists for exactly that, and an acquisition price is not a mark.

    Held here: series_a (seeded lot) and series_b. R2 prices series_b only.
    """
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps, cost_amount,"
        " cost_currency, acquired_date) values (%s, %s, 'series_b', 1000, 2.00, 2000, 'USD',"
        " '2024-01-01')",
        (f"{seed['lot']}_b", seed["h"]),
    )
    for cid, cls, price in (
        (f"{seed['cl']}_r1", "series_a", 8.00),
        (f"{seed['cl']}_r2", "series_b", 8.00),
    ):
        conn.execute(
            "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
            " execution_status, issued_date, applicable_from, priced_class, price_per_share)"
            " values (%s, %s, %s, %s, 'company_cap_table', 'executed',"
            " '2025-06-30', '2025-01-01', %s, %s)",
            (cid, seed["dv"], seed["h"], cid, cls, price),
        )
        cite_price(conn, cid)
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 9000, 'USD', 9000, 'USD', 'derivable', 'priced off series_b')"
        " returning id",
        (seed["h"], seed["p"]),
    )
    r1 = assess(conn, seed, mid, "R1", claim=f"{seed['cl']}_r1")
    r2 = assess(conn, seed, mid, "R2", claim=f"{seed['cl']}_r2")
    approve_valuation(conn, mid, [r1, r2])
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("set constraints all immediate")
    conn.rollback()
    assert "holds class series_a which no cited claim prices" in str(exc.value)


def test_r2_evidence_covering_every_held_class_still_approves(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The direction the fix above must not take with it.

    Narrowing the priced set to R2 refuses more, so a position whose fair-value
    evidence genuinely prices every class it holds has to keep approving — one
    R2 assessment may cite several claims, and that is the ordinary shape of a
    cap table covering a multi-class position.
    """
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps, cost_amount,"
        " cost_currency, acquired_date) values (%s, %s, 'series_b', 1000, 2.00, 2000, 'USD',"
        " '2024-01-01')",
        (f"{seed['lot']}_b", seed["h"]),
    )
    for cid, cls in ((f"{seed['cl']}_pa", "series_a"), (f"{seed['cl']}_pb", "series_b")):
        conn.execute(
            "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
            " execution_status, issued_date, applicable_from, priced_class, price_per_share)"
            " values (%s, %s, %s, %s, 'company_cap_table', 'executed',"
            " '2025-06-30', '2025-01-01', %s, 8.00)",
            (cid, seed["dv"], seed["h"], cid, cls),
        )
        cite_price(conn, cid)
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 9000, 'USD', 9000, 'USD', 'derivable', 'priced per class')"
        " returning id",
        (seed["h"], seed["p"]),
    )
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=f"{seed['cl']}_pa")
    conn.execute(
        "insert into evidence_link (assessment_id, claim_id) values (%s, %s)",
        (r2, f"{seed['cl']}_pb"),
    )
    approve_valuation(conn, mid, [r1, r2])
    conn.execute("set constraints all immediate")
    conn.rollback()


def _class_claim(conn: Conn, seed: dict[str, str], cid: str, cls: str | None, price: float) -> str:
    """A cap-table claim pricing `cls`, or pricing nothing in particular."""
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, priced_class, price_per_share)"
        " values (%s, %s, %s, %s, 'company_cap_table', 'executed',"
        " '2025-06-30', '2025-01-01', %s, %s)",
        (cid, seed["dv"], seed["h"], cid, cls, price),
    )
    cite_price(conn, cid)
    return cid


def _priced_mark(conn: Conn, seed: dict[str, str]) -> int:
    return returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 9000, 'USD', 9000, 'USD', 'derivable', 'x') returning id",
        (seed["h"], seed["p"]),
    )


def _series_b_lot(conn: Conn, seed: dict[str, str]) -> None:
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps, cost_amount,"
        " cost_currency, acquired_date) values (%s, %s, 'series_b', 1000, 2.00, 2000, 'USD',"
        " '2024-01-01')",
        (f"{seed['lot']}_b", seed["h"]),
    )


def _approve_one_direction(
    conn: Conn, seed: dict[str, str], *, direction: int, decision_policy: str
) -> None:
    """Exercise exactly ONE arm of the INV-17 equality, then approve under v1.

    Both arms are asserted separately because each masks the other: with a stale
    decision, removing the policy-version filter from direction 1 alone still
    raises from direction 2 on the same facts, and the mutation reads as
    defended while the branch it names is not.
    """
    if direction == 1:
        # A class is PRICED that the holding does not hold; every held class is
        # priced, so direction 2 has nothing to say.
        r2_claims = [
            _class_claim(conn, seed, f"{seed['cl']}_pa", "series_a", 8.00),
            _class_claim(conn, seed, f"{seed['cl']}_pc", "series_c", 8.00),
        ]
        policy = ("series_c", "series_a")
    else:
        # A class is HELD that nothing prices; every priced class is held, so
        # direction 1 has nothing to say.
        _series_b_lot(conn, seed)
        r2_claims = [_class_claim(conn, seed, f"{seed['cl']}_pa", "series_a", 8.00)]
        policy = ("series_a", "series_b")
    mid = _priced_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=r2_claims[0])
    for extra in r2_claims[1:]:
        conn.execute(
            "insert into evidence_link (assessment_id, claim_id) values (%s, %s)", (r2, extra)
        )
    conn.execute(
        "insert into valuation_policy_decision (holding_id, period_id, from_class, to_class,"
        " rationale, citation_quote, policy_version) values (%s, %s, %s, %s, 'r', 'q', %s)",
        (seed["h"], seed["p"], *policy, decision_policy),
    )
    approve_valuation(conn, mid, [r1, r2])
    conn.execute("set constraints all immediate")


@pytest.mark.parametrize("direction", [1, 2])
def test_each_arm_of_the_cross_class_rule_reads_the_approvals_own_policy(
    conn: Conn, seed: dict[str, str], direction: int
) -> None:
    """A decision under a superseded policy authorises neither arm on its own."""
    with pytest.raises(psycopg.Error) as exc:
        _approve_one_direction(conn, seed, direction=direction, decision_policy="v0")
    conn.rollback()
    assert "INV-17" in str(exc.value)


@pytest.mark.parametrize("direction", [1, 2])
def test_each_arm_of_the_cross_class_rule_accepts_a_current_decision(
    conn: Conn, seed: dict[str, str], direction: int
) -> None:
    """And the same facts under the approval's own policy still approve —
    without this, a filter that rejected every decision would pass above."""
    _approve_one_direction(conn, seed, direction=direction, decision_policy="v1")
    conn.rollback()


def test_an_r1_claim_pricing_without_a_class_does_not_block_the_approval(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The unstated-class refusal is scoped to R2 like the rest of the rule.

    An executed transaction document supporting R1 states what was paid per
    share and routinely names no security class — that is the shape of the
    document, and it says nothing about how the MARK was priced. Refusing on it
    blocks a legitimate approval whose fair-value evidence is complete, which is
    the expensive direction of the same mistake and the harder one to notice.
    """
    _class_claim(conn, seed, f"{seed['cl']}_r1", None, 8.00)
    mid = _priced_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=f"{seed['cl']}_r1")
    r2 = assess(
        conn, seed, mid, "R2", claim=_class_claim(conn, seed, f"{seed['cl']}_pa", "series_a", 8.00)
    )
    approve_valuation(conn, mid, [r1, r2])
    conn.execute("set constraints all immediate")
    conn.rollback()


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
        " '2025-06-30', '2025-01-01', 8.00)",
        (noclass, seed["dv"], seed["h"]),
    )
    cite_price(conn, noclass)
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


def test_a_held_class_that_no_claim_prices_is_refused(conn: Conn, seed: dict[str, str]) -> None:
    """The half 0002 was missing, and the case INV-17 was written for.

    The seeded lot is `series_a`. Add a `series_c` lot, then price the mark from
    a `series_c` claim alone. The old guard asked only "is the priced class
    held?" — series_c is held, so it passed, while the series_a shares were
    carried at the series_c price. The Mom Project's term sheet says Series C is
    senior to Series B and Series Seed, so that is exactly the economic
    equivalence the document contradicts.
    """
    conn.execute(
        "insert into lot (id, holding_id, security_class, shares, entry_pps,"
        " cost_amount, cost_currency, acquired_date)"
        " values (%s, %s, 'series_c', 100, 9.00, 900, 'USD', '2024-01-01')",
        (f"{seed['lot']}_c", seed["h"]),
    )
    with pytest.raises(psycopg.Error) as exc:
        _price_series_c_off_series_b(conn, seed, with_policy=False)
    conn.rollback()
    assert "INV-17" in str(exc.value)
    assert "which no cited claim prices" in str(exc.value)


def test_every_held_class_priced_by_its_own_claim_is_allowed(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The counterweight, and the direction the oracle used to get wrong: a
    position whose every held class carries its own priced claim propagates
    nothing and needs no policy decision. An equality rule that rejected this
    would make a fully supported multi-class holding unapprovable."""
    own = f"{seed['cl']}_a"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from, priced_class, price_per_share)"
        " values (%s, %s, %s, 'k2', 'company_cap_table', 'executed',"
        " '2025-06-30', '2025-01-01', 'series_a', 8.00)",
        (own, seed["dv"], seed["h"]),
    )
    cite_price(conn, own)
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " validated_amount, validated_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 4000, 'USD', 4000, 'USD', 'derivable', 'own class')"
        " returning id",
        (seed["h"], seed["p"]),
    )
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=own)
    approve_valuation(conn, mid, [r1, r2])
    conn.execute("set constraints all immediate")
