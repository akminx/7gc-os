"""Packet approval, and identity agreement across fund, period and holding.

Every rejection here was a commit before `0003_approval_prerequisites.sql`, and
each one was proven by executing it against the live database rather than by
reading the migrations: a packet approved with an empty manifest and nothing
approved beneath it, manifest entries inserted after that approval, an approved
packet's `state` rewritten underneath it, and a Fund I packet pointing at a
Fund II period.

`assess` and `approve_valuation` are imported from the approval suite rather than
copied: a packet may only be approved over marks that are themselves approved, so
these tests need the same complete evidence set, and a second copy of it would be
a second thing to keep in step with the schema.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from packages.contracts.fixtures.dream import dream_packet
from tests.schema_helpers import DSN, Conn, make_mark, rejects, returned_id
from tests.test_schema_approval import approve_valuation, assess

#: Applied per test rather than to the module: the held-at-date total below is
#: a contract-level rule with no database to reach, and a DB skip would hide it.
requires_db = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


def _packet(conn: Conn, seed: dict[str, str], period: str | None = None, policy: str = "v1") -> str:
    pid = f"pk_{seed['fund']}"
    conn.execute(
        "insert into packet_version (id, fund_id, period_id, state, schema_version,"
        " policy_version, generator_ref) values (%s, %s, %s, 'draft', '1', %s, 'g')",
        (pid, seed["fund"], period or seed["p"], policy),
    )
    return pid


def _manifest(conn: Conn, packet_id: str, path: str = "packet.pdf", ordinal: int = 1) -> None:
    conn.execute(
        "insert into packet_manifest_entry (packet_id, path, content_hash, ordinal)"
        " values (%s, %s, 'h', %s)",
        (packet_id, path, ordinal),
    )


def _approved_mark(conn: Conn, seed: dict[str, str]) -> int:
    mid = make_mark(conn, seed)
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=seed["cl"])
    approve_valuation(conn, mid, [r1, r2])
    return mid


def _approve_packet(conn: Conn, packet_id: str, policy: str = "v1") -> int:
    return returned_id(
        conn,
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " packet_id, policy_version, actor_id)"
        " values ('packet', 'approved', 'packet', %s, %s, %s, 'a') returning id",
        (packet_id, packet_id, policy),
    )


def _other_fund_period(conn: Conn, seed: dict[str, str]) -> tuple[str, str]:
    """A second fund with its own packet-scope period at the same date."""
    fund, period = f"{seed['fund']}_2", f"{seed['p']}_2"
    conn.execute("insert into fund values (%s, 'Other Fund')", (fund,))
    conn.execute(
        "insert into reporting_period values (%s, %s, '2025-12-31', 'packet', 'FY2025')",
        (period, fund),
    )
    return fund, period


def _refused_at_commit(conn: Conn) -> str:
    with pytest.raises(psycopg.Error) as exc:
        conn.execute("set constraints all immediate")
    conn.rollback()
    return str(exc.value)


# ── INV-10 · a packet approval must rest on something ────────────────────
@requires_db
def test_packet_approval_with_an_empty_manifest_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Proven on the live database: an approved packet containing no files. The
    deliverable's only true statement was that it existed."""
    _approved_mark(conn, seed)
    pid = _packet(conn, seed)
    _approve_packet(conn, pid)
    err = _refused_at_commit(conn)
    assert "packet_approval_needs_lower_approvals" in err
    assert "empty manifest" in err


@requires_db
def test_packet_approval_over_no_marks_at_all_is_refused(conn: Conn, seed: dict[str, str]) -> None:
    """A manifest of files is not a valuation. With no mark in the period there
    is nothing beneath the approval to have been approved."""
    pid = _packet(conn, seed)
    _manifest(conn, pid)
    _approve_packet(conn, pid)
    assert "over no mark at all" in _refused_at_commit(conn)


@requires_db
def test_packet_approval_without_the_valuation_approval_beneath_it_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-18 · independent state machines never share authorization semantics.
    Approving the packet must not approve the marks inside it by implication."""
    make_mark(conn, seed)
    pid = _packet(conn, seed)
    _manifest(conn, pid)
    _approve_packet(conn, pid)
    err = _refused_at_commit(conn)
    assert "packet_approval_needs_lower_approvals" in err
    assert "carries no approved valuation" in err


@requires_db
def test_a_packet_over_approved_marks_with_a_manifest_is_allowed(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The positive path. Without it the trigger could refuse every packet and
    the three tests above would still pass."""
    _approved_mark(conn, seed)
    pid = _packet(conn, seed)
    _manifest(conn, pid)
    _approve_packet(conn, pid)
    conn.execute("set constraints all immediate")


@requires_db
def test_a_superseded_mark_revision_does_not_block_the_packet(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-5 · a correction is a new revision, never an edit. Requiring every
    revision to be approved would make a corrected mark unapprovable, which is
    the pressure that gets a guard deleted rather than fixed."""
    make_mark(conn, seed)  # revision 1, superseded and never approved
    mid = returned_id(
        conn,
        "insert into mark (holding_id, period_id, revision, reported_amount,"
        " reported_currency, derivation_status, derivation_reason)"
        " values (%s, %s, 2, 1000000, 'USD', 'not_derivable', 'x') returning id",
        (seed["h"], seed["p"]),
    )
    r1 = assess(conn, seed, mid, "R1", claim=seed["cl"])
    r2 = assess(conn, seed, mid, "R2", claim=seed["cl"])
    approve_valuation(conn, mid, [r1, r2])
    pid = _packet(conn, seed)
    _manifest(conn, pid)
    _approve_packet(conn, pid)
    conn.execute("set constraints all immediate")


@requires_db
def test_a_packet_approved_over_a_gapped_manifest_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Proven on the live database: a packet whose only manifest entry sat at
    ordinal 99 approved cleanly. A non-empty manifest is not a complete one — a
    lone entry at 99 says ninety-eight documents belong here and are absent, and
    append-only means they can never arrive."""
    _approved_mark(conn, seed)
    pid = _packet(conn, seed)
    _manifest(conn, pid, "attacker.txt", ordinal=99)
    _approve_packet(conn, pid)
    err = _refused_at_commit(conn)
    assert "packet_approval_needs_lower_approvals" in err
    assert "numbered 99 to 99" in err


@requires_db
def test_two_manifest_entries_cannot_share_an_ordinal(conn: Conn, seed: dict[str, str]) -> None:
    """The primary key is (packet_id, path), so position was unconstrained and
    two documents could claim the same one — a manifest that counts 1..n while
    describing no order at all."""
    pid = _packet(conn, seed)
    _manifest(conn, pid, "a.pdf", ordinal=1)
    assert "packet_manifest_ordinal_unique" in rejects(
        conn,
        "insert into packet_manifest_entry (packet_id, path, content_hash, ordinal)"
        " values (%s, 'b.pdf', 'h', 1)",
        (pid,),
    )


@requires_db
def test_a_manifest_entry_may_still_be_added_while_the_decision_is_a_draft(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The seal is `approved`, not "any packet decision". Sealing on a draft would
    make a packet unassemblable the moment a reviewer opened it."""
    pid = _packet(conn, seed)
    _manifest(conn, pid, "a.pdf", ordinal=1)
    conn.execute(
        "insert into review_decision (decision_type, status, subject_kind, subject_id,"
        " packet_id, policy_version, actor_id)"
        " values ('packet', 'draft', 'packet', %s, %s, 'v1', 'a')",
        (pid, pid),
    )
    _manifest(conn, pid, "b.pdf", ordinal=2)


# ── INV-10 · the approval binds a policy snapshot, not only a packet ─────
@requires_db
def test_a_packet_approved_over_another_policy_versions_valuations_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Proven on the live database: a v2 packet approved on the strength of v1
    valuation approvals. The deliverable then exports judgements made under a
    policy it does not claim, and a sufficiency change is invisible in it."""
    _approved_mark(conn, seed)  # approved at v1
    pid = _packet(conn, seed, policy="v2")
    _manifest(conn, pid)
    _approve_packet(conn, pid, policy="v2")
    err = _refused_at_commit(conn)
    assert "packet_approval_needs_lower_approvals" in err
    assert "at policy version v2" in err


@requires_db
def test_a_packet_approval_at_another_version_than_the_packet_itself_is_refused(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The other half of the same disagreement: matching the lower approvals is
    not enough if the decision and the packet version name different policies."""
    _approved_mark(conn, seed)
    pid = _packet(conn, seed, policy="v1")
    _manifest(conn, pid)
    _approve_packet(conn, pid, policy="v2")
    assert "recorded at policy version v1" in _refused_at_commit(conn)


# ── INV-10 · an approved packet is sealed and immutable ──────────────────
@requires_db
def test_a_manifest_entry_cannot_be_added_after_the_packet_is_approved(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Append-only blocked UPDATE and DELETE, not INSERT, so a blessed packet
    could grow contents nobody approved — proven on the live database."""
    _approved_mark(conn, seed)
    pid = _packet(conn, seed)
    _manifest(conn, pid)
    _approve_packet(conn, pid)
    err = rejects(
        conn,
        "insert into packet_manifest_entry (packet_id, path, content_hash, ordinal)"
        " values (%s, 'smuggled.pdf', 'h', 2)",
        (pid,),
    )
    assert "packet_manifest_sealed" in err
    assert "requires a new packet version" in err


@requires_db
def test_an_approved_packets_state_cannot_be_rewritten(conn: Conn, seed: dict[str, str]) -> None:
    """`packet_version` was absent from 0002's append-only list, so `state` and
    `policy_version` could be rewritten under the approval that named them —
    exactly the defect that made the mark fingerprint decorative in r1."""
    pid = _packet(conn, seed)
    assert "append-only" in rejects(
        conn, "update packet_version set state = 'released' where id = %s", (pid,)
    )


@requires_db
def test_an_approved_packet_cannot_be_deleted(conn: Conn, seed: dict[str, str]) -> None:
    pid = _packet(conn, seed)
    assert "append-only" in rejects(conn, "delete from packet_version where id = %s", (pid,))


# ── Identity agreement · fund, period, holding, packet ───────────────────
@requires_db
def test_a_packet_cannot_reference_another_funds_period(conn: Conn, seed: dict[str, str]) -> None:
    """Proven on the live database: fund_id and period_id were independent
    foreign keys, so a Fund I packet could be assembled over Fund II's period and
    report its holdings under the wrong fund's name."""
    _, period = _other_fund_period(conn, seed)
    assert "packet_period_same_fund" in rejects(
        conn,
        "insert into packet_version (id, fund_id, period_id, state, schema_version,"
        " policy_version, generator_ref) values ('pk_x', %s, %s, 'draft', '1', 'v1', 'g')",
        (seed["fund"], period),
    )


@requires_db
def test_a_mark_cannot_bind_a_holding_to_another_funds_period(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The same disagreement one level down: the mark reaches its fund through
    the holding and its date through the period, and nothing required the two to
    name the same fund."""
    _, period = _other_fund_period(conn, seed)
    err = rejects(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 1000, 'USD', 'not_derivable', 'x')",
        (seed["h"], period),
    )
    assert "mark_same_fund" in err
    assert "belongs to fund" in err


@requires_db
def test_a_requirement_cannot_bind_a_holding_to_another_funds_period(
    conn: Conn, seed: dict[str, str]
) -> None:
    """A requirement raised against another fund's period would make that fund's
    completeness depend on evidence assembled for a different fund."""
    _, period = _other_fund_period(conn, seed)
    assert "pbc_requirement_same_fund" in rejects(
        conn,
        "insert into pbc_requirement (holding_id, period_id, requirement, applicable)"
        " values (%s, %s, 'R1', true)",
        (seed["h"], period),
    )


@requires_db
def test_a_cross_class_policy_cannot_be_cited_from_another_funds_period(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-17 · the policy act is scoped to a holding at a date. Citing one
    recorded under another fund's period would satisfy the cross-class gate with
    a decision nobody made about this fund."""
    _, period = _other_fund_period(conn, seed)
    assert "valuation_policy_decision_same_fund" in rejects(
        conn,
        "insert into valuation_policy_decision (holding_id, period_id, from_class,"
        " to_class, rationale, citation_quote, policy_version)"
        " values (%s, %s, 'series_c', 'series_a', 'r', 'q', 'v1')",
        (seed["h"], period),
    )


@requires_db
def test_a_workflow_run_cannot_bind_a_holding_to_another_funds_period(
    conn: Conn, seed: dict[str, str]
) -> None:
    """The fourth table `require_same_fund` guards, and the only one no test
    named: dropping `workflow_run_same_fund` left the whole suite green. A run
    recorded against another fund's period attributes its steps, and whatever it
    produced, to the wrong fund."""
    _, period = _other_fund_period(conn, seed)
    assert "workflow_run_same_fund" in rejects(
        conn,
        "insert into workflow_run (id, holding_id, period_id, state)"
        " values ('wf_x', %s, %s, 'running')",
        (seed["h"], period),
    )


@requires_db
def test_a_workflow_run_cannot_be_moved_onto_another_funds_period(
    conn: Conn, seed: dict[str, str]
) -> None:
    """Proven on the live database: the identity triggers fired on INSERT only,
    and `workflow_run` is the one guarded table that is not append-only — a run
    legitimately changes `state` — so a valid run could simply be UPDATEd across
    funds afterwards."""
    _, period = _other_fund_period(conn, seed)
    conn.execute(
        "insert into workflow_run (id, holding_id, period_id, state)"
        " values ('wf_y', %s, %s, 'running')",
        (seed["h"], seed["p"]),
    )
    assert "workflow_run_same_fund" in rejects(
        conn, "update workflow_run set period_id = %s where id = 'wf_y'", (period,)
    )


@requires_db
def test_a_workflow_run_that_names_no_period_is_allowed(conn: Conn, seed: dict[str, str]) -> None:
    """`holding_id` and `period_id` are nullable on this table alone, and two
    identities cannot disagree when only one is named. Without this the early
    return could be deleted and every negative test above would still pass."""
    conn.execute(
        "insert into workflow_run (id, holding_id, state) values ('wf_z', %s, 'running')",
        (seed["h"],),
    )
    conn.execute("update workflow_run set state = 'done' where id = 'wf_z'")


# ── The whole path, committed ────────────────────────────────────────────
@requires_db
def test_a_complete_legitimate_approval_commits(conn: Conn, seed: dict[str, str]) -> None:
    """Every other positive test stops at `set constraints all immediate` so the
    append-only tables stay clean. This one commits, because an over-strict
    constraint that refuses a real approval is as damaging as a missing one and
    far harder to notice: R1-R5 all applicable, all `sufficient`, all linked to a
    claim, all at the approval's own policy version, and a packet over them."""
    mid = make_mark(conn, seed)
    cited = [assess(conn, seed, mid, c, claim=seed["cl"]) for c in ("R1", "R2", "R3", "R4", "R5")]
    approve_valuation(conn, mid, cited)
    pid = _packet(conn, seed)
    _manifest(conn, pid)
    _approve_packet(conn, pid)
    conn.commit()


# ── INV-7 · held-at-date ≠ in the packet ─────────────────────────────────
# No database to reach: the packet total is assembled in the contract layer, and
# that is the side the rule was missing from.
def test_a_realisation_only_row_stays_outside_the_held_at_date_total() -> None:
    """The oracle has always excluded rows not held at the measurement date;
    `HoldingRow` had no way to say so and `Packet.totals()` summed every row, so
    the two sides produced different totals from the same facts — this project's
    recurring one-side-only defect.

    The realised row is still a packet gap: it disappears from the total and
    stays in `packet_gap_positions`, because dropping it from both would trade
    one silent error for another.
    """
    packet = dream_packet()
    held = packet.rows[0]
    realised = held.model_copy(update={"holding_id": "exited", "held_at_date": False})
    totals = packet.model_copy(update={"rows": [held, realised]}).totals()

    assert totals.amount.amount == Decimal("5000000")
    assert totals.unsupported_amount.amount == Decimal("5000000")
    assert totals.unsupported_positions == 1
    assert totals.packet_gap_positions == 2


def test_a_row_is_held_at_the_measurement_date_unless_it_says_otherwise() -> None:
    """The field is additive: every existing construction of a HoldingRow means
    what it did before, so the default cannot quietly drop a live position out of
    a fund total."""
    assert dream_packet().rows[0].held_at_date is True
