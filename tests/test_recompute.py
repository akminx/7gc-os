"""SPEC §8's V2, on the way to a served response.

The finding this exists for: nothing in `api/` imported `v2_mark`, `v1_all` or
`Outcome`, and all 72 `mark` rows carry `validated_amount = null` because
`ingest/trackers/to_contracts.py` writes it as a literal. So the validators ran
in the test suite and in the oracle and NONE of their output reached the
product — including the two rows where the evidence and the tracker disagree:

    Lucra FY2025        reported 2,250,000    derived 1,500,000
    Fluidstack 25Q4     reported 6,000,000    derived 2,500,000

`tests/test_packet_export.py` compares the packet against `derived.json` over
the fields the packet CARRIES, so a packet carrying no derivation at all agreed
with the oracle vacuously about it. These assertions are the ones that could not
pass vacuously: they check the served figure against the answer key row by row,
and they name the two disagreements out loud so that dropping either one is a
red test rather than a quieter page.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from api.serialize import PACKET_RECOMPUTATION_KEY, packet_json, recomputation_json
from packages.contracts.base import MONEY_SCALE, Money
from packages.contracts.enums import (
    DerivationStatus,
    PositionType,
    RequirementCode,
    RequirementVerdict,
)
from packages.contracts.models import HoldingRow, Mark, Packet, RequirementAssessment
from packet.recompute import _at_scale, _from_result, disagreeing, for_packet
from policy.inputs import Ledger
from policy.validators import LotAmount, Outcome, Result

ROOT = Path(__file__).resolve().parents[1]

#: R1 and R2 apply to every position held at the measurement date (SPEC §7.1),
#: and `HoldingRow` refuses to be built without them. Present so the synthetic
#: row below is a legal one rather than a shape the contract would reject.
_ALWAYS_APPLICABLE = tuple(
    RequirementAssessment(
        requirement=code,
        verdict=RequirementVerdict.MISSING,
        reason_codes=["NO_APPLICABLE_SUPPORT_NOT_LOCATED"],
        next_actions=[],
        evidence=[],
        pro_forma=False,
        policy_version="v1",
    )
    for code in (RequirementCode.R1, RequirementCode.R2)
)

#: The oracle's own answer key. Read HERE and never by the product —
#: `tests/test_gate_guards.py` refuses any reference to this path from
#: `policy/`, `api/` or `packet/`, which is what makes this comparison mean
#: something rather than being the code agreeing with itself.
ORACLE = ROOT / "evals" / "oracle" / "derived.json"

#: `derived.json` names holdings its own way, and two of the fourteen are not a
#: prefix away from the ledger's id: the oracle says `jio` and `mom_project`
#: where the ledger says `fund_i_jio_indirect` and `fund_i_the_mom_project`.
#:
#: Written out rather than pattern-matched, and checked TOTAL in both directions
#: below, because the failure to avoid is not a wrong pair — it is a missing one.
#: A join that quietly matched thirty rows out of thirty-five would report the
#: five it skipped as agreement, which is the shape of a comparison that passes
#: because it never ran.
HOLDING = {
    "anthropic": "fund_ii_anthropic",
    "because_market": "fund_ii_because_market",
    "dream": "fund_ii_dream",
    "fluidstack": "fund_ii_fluidstack",
    "jackpocket": "fund_ii_jackpocket",
    "lucra": "fund_ii_lucra",
    "moonfare": "fund_ii_moonfare",
    "poolside": "fund_ii_poolside",
    "sway": "fund_ii_sway",
    "banzai": "fund_i_banzai",
    "capsule": "fund_i_capsule",
    "jio": "fund_i_jio_indirect",
    "mom_project": "fund_i_the_mom_project",
    "roofstock": "fund_i_roofstock",
}


def _holding_ids(packets: dict[tuple[str, str], Packet]) -> set[str]:
    return {row.holding_id for packet in packets.values() for row in packet.rows}


def _oracle_marks(packets: dict[tuple[str, str], Packet]) -> dict[tuple[str, str], dict[str, Any]]:
    """The answer key's 35 holding-dates, keyed the way the ledger keys them.

    `rows` and not `concluded_value_checks`: the latter is two documents, while
    `rows` is every holding at every measurement date and carries the three
    fields this comparison turns on — `validated_amount`, `carried_amount` and
    `validated_matches_reported`.
    """
    rows = json.loads(ORACLE.read_text())["rows"]
    named = {r["holding"] for r in rows}
    assert named == set(HOLDING), f"the answer key names {sorted(named ^ set(HOLDING))}"
    assert set(HOLDING.values()) == _holding_ids(packets), (
        f"the ledger holds {sorted(_holding_ids(packets) ^ set(HOLDING.values()))}"
    )
    return {(HOLDING[r["holding"]], r["date"]): r for r in rows}


def _packets(policy_packets: object) -> dict[tuple[str, str], Packet]:
    assert isinstance(policy_packets, dict)
    return {key: value for key, value in policy_packets.items() if value is not None}


def _ledger(policy_ledger: object) -> Ledger:
    assert isinstance(policy_ledger, Ledger)
    return policy_ledger


def test_the_recomputation_agrees_with_the_oracle_row_for_row(
    policy_ledger: object, policy_packets: object
) -> None:
    """Every derived figure the API will serve, against the independent derivation.

    The oracle publishes three fields and they are three different findings:
    `validated_amount` is a figure that CONFIRMS, `carried_amount` is a real
    cited figure that confirms nothing because the fund wrote the document it
    came from, and both being null means the evidence is silent. The
    recomputation has to reproduce all three, and the outcome it reports has to
    say which one it is.
    """
    packets = _packets(policy_packets)
    oracle = _oracle_marks(packets)
    checked = 0
    for packet in packets.values():
        for holding_id, got in for_packet(_ledger(policy_ledger), packet).items():
            key = (holding_id, packet.period.period_date.isoformat())
            expected = oracle.get(key)
            if expected is None:
                continue
            checked += 1
            confirmed = expected["validated_amount"]
            carried = expected["carried_amount"]
            derived = None if got.derived is None else got.derived.amount
            assert derived == (
                None
                if confirmed is None and carried is None
                else Decimal(confirmed if confirmed is not None else carried)
            ), f"{key}: derived {derived}, oracle says {confirmed or carried}"
            if carried is not None:
                # The fund is the author of both figures. `pass` is what that
                # circularity produces if nothing stops it, so the outcome must
                # be the one that says the evidence spoke in the voice under
                # audit — not a pass, and not "the evidence does not say".
                assert got.outcome is Outcome.NOT_COMPARABLE, key
            elif confirmed is not None:
                matches = expected["validated_matches_reported"]
                assert got.outcome is (Outcome.PASS if matches else Outcome.FAIL), key
    assert checked >= 30, f"only {checked} rows compared — the oracle join is not landing"


def test_the_two_disagreements_are_reported_as_disagreements(
    policy_ledger: object, policy_packets: object
) -> None:
    """Named, not counted.

    A count would stay green if one finding were lost and another appeared; the
    whole value of this pair is that these two specific marks are wrong by these
    two specific amounts, and both were invisible until the recomputation was
    served.
    """
    packets = _packets(policy_packets)
    found = {
        (r.holding_id, key[1]): r
        for key, packet in packets.items()
        for r in disagreeing(for_packet(_ledger(policy_ledger), packet))
    }
    fluidstack = found[("fund_ii_fluidstack", "fund_ii_25q4")]
    assert fluidstack.derived is not None and fluidstack.reported is not None
    assert fluidstack.derived.amount == Decimal("2500000")
    assert fluidstack.reported.amount == Decimal("6000000")
    assert fluidstack.difference is not None
    assert fluidstack.difference.amount == Decimal("3500000")
    # 100,000 Series A at $10.00 plus 100,000 Series A-2 at $15.00. The reported
    # figure is 200,000 shares at the $30.00 Series B price applied to every
    # class, and the per-class working is what makes that legible.
    assert {(p.security_class, p.price_per_share) for p in fluidstack.per_class} == {
        ("series_a", Decimal("10.00")),
        ("series_a2", Decimal("15.00")),
    }

    lucra = found[("fund_ii_lucra", "fund_ii_25q4")]
    assert lucra.derived is not None and lucra.reported is not None
    assert lucra.derived.amount == Decimal("1500000")
    assert lucra.reported.amount == Decimal("2250000")


def test_the_currency_is_the_reported_marks_and_never_a_guess(
    policy_ledger: object, policy_packets: object
) -> None:
    """INV-11 · a figure labelled with a currency nobody stated has already been
    breached here once, on `validated_currency`. The validators carry bare
    Decimals, so the currency has exactly one source and no fallback."""
    for packet in _packets(policy_packets).values():
        for row in packet.rows:
            got = for_packet(_ledger(policy_ledger), packet)[row.holding_id]
            if row.mark is None:
                assert got.derived is None, f"{row.holding_id} has no mark to take a currency from"
                assert got.difference is None
            elif got.derived is not None:
                assert got.derived.currency == row.mark.reported.currency


def test_a_figure_derived_for_a_row_with_no_mark_is_withheld_not_labelled() -> None:
    """The same rule, on the case this corpus does not contain.

    Written against `_from_result` rather than against the fixture because the
    branch is UNREACHABLE here: the only row with no mark is Jackpocket at 24Q4,
    where V2 answers `not_applicable` and derives nothing, so the assertion above
    passes whatever the code does with a currency it cannot name. Mutating
    `currency` to a literal `"USD"` left that test green, which is the whole
    reason this one exists — an assertion no input can falsify is not a guard.

    The figure is withheld rather than published under a guessed currency, and
    the REASON still travels, so the pane says what was derived and why there is
    no amount beside it.
    """
    row = HoldingRow(
        holding_id="h",
        company_name="H",
        position_type=PositionType.DIRECT_EQUITY,
        held_at_date=True,
        mark=None,
        assessments=list(_ALWAYS_APPLICABLE),
        gaps=[],
        approval=None,
    )
    derived_but_unnameable = Result(
        validator="V2",
        subject="h@2025-12-31",
        outcome=Outcome.BLOCKED_INCOMPLETE,
        reason="NO_STATED_FIGURE_TO_COMPARE",
        computed=Decimal("1234"),
    )
    got = _from_result(derived_but_unnameable, row, "v1")
    assert got.derived is None
    assert got.difference is None
    assert got.reason == "NO_STATED_FIGURE_TO_COMPARE"
    assert got.outcome is Outcome.BLOCKED_INCOMPLETE


#: A row with a mark, so `_from_result` has a currency and publishes figures.
#: Everything below is written against `_from_result` rather than the corpus for
#: the reason `test_a_figure_derived_for_a_row_with_no_mark_is_withheld_not_labelled`
#: gives: the corpus does not contain these cases, so an assertion over it
#: passes whatever the code does, and an assertion no input can falsify is not
#: a guard. These are DB-free and corpus-free, so they hold under `--ci` too.
def _row_with_mark(reported: str = "5000") -> HoldingRow:
    return HoldingRow(
        holding_id="h",
        company_name="H",
        position_type=PositionType.DIRECT_EQUITY,
        held_at_date=True,
        mark=Mark(
            id=1,
            holding_id="h",
            period_id="p",
            reported=Money(amount=Decimal(reported), currency="USD"),
            derivation_status=DerivationStatus.NOT_DERIVABLE,
            derivation_reason="NO_APPLICABLE_EVIDENCE",
        ),
        assessments=list(_ALWAYS_APPLICABLE),
        gaps=[],
        approval=None,
    )


def _priced(cross_class: bool, pps: str = "10.000000") -> Result:
    lot = LotAmount(
        lot_id="lot_1",
        security_class="series_a1",
        shares=500,
        price_per_share=Decimal(pps),
        amount=Decimal(500) * Decimal(pps),
        cross_class=cross_class,
    )
    return Result(
        validator="V2",
        subject="h@2025-12-31",
        outcome=Outcome.PASS,
        reason="PER_CLASS_SHARES_X_PPS",
        computed=lot.amount,
        evidence=("h:some_cap_table",),
        lineage=(lot,),
    )


def test_the_cross_class_flag_survives_into_the_served_recomputation() -> None:
    """INV-17 · pricing one class off another's evidence is a policy act.

    Nothing read `Recomputation.per_class[*].cross_class`. Replacing it with a
    literal `False` left all 822 tests green: the `cross_class` assertions that
    exist are on the validator lineage, never on the copy `packet/recompute.py`
    makes, and the browser renders it off a hand-written fixture that sets it
    false on both lots — so vitest could not catch a Python-side change either.

    Latent today: no lot in this corpus is currently cross-class, so the flag
    is the mechanism rather than a visible number. That is precisely why it
    needs a test written against a constructed lot.
    """
    got = _from_result(_priced(cross_class=True), _row_with_mark(), "v1")
    assert [c.cross_class for c in got.per_class] == [True]
    assert (
        _from_result(_priced(cross_class=False), _row_with_mark(), "v1").per_class[0].cross_class
        is False
    )


def test_the_claims_a_derived_figure_came_from_travel_with_it() -> None:
    """The citation trail, which is the product's whole reason for existing.

    Blanking `evidence_claim_ids` left every test green while emptying the
    "which claims support this figure" column on 18 of 35 recomputations across
    14 distinct claim ids — on both the served response and the exported packet
    table. For a system whose purpose is tracing every figure to an exact
    source passage, a green suite over that is the worst kind of false green.
    """
    got = _from_result(_priced(cross_class=False), _row_with_mark(), "v1")
    assert got.evidence_claim_ids == ("h:some_cap_table",)


def test_a_price_per_share_keeps_its_own_scale_on_the_wire() -> None:
    """Asserted on the STRING, because Decimal equality cannot see this.

    `Decimal("10.0000") == Decimal("10.000000")` is True, so quantising a price
    at the money scale instead of the price scale passed every comparison in
    the suite — while `api/serialize.py` sends `str(...)`, so an auditor read
    `10.0000` where the source states six places. All nine distinct prices in
    the corpus ship at six today and would all have shifted.
    """
    got = _from_result(_priced(cross_class=False, pps="10.000000"), _row_with_mark(), "v1")
    assert str(got.per_class[0].price_per_share) == "10.000000"


def test_a_figure_carrying_more_places_than_its_scale_is_refused_not_rounded() -> None:
    """Deleting this raise is silent re-quantisation on the read path.

    No test referenced `_at_scale` or its ValueError, and the branch never fires
    on this corpus — every derived figure is a whole number — so removing the
    refusal was invisible. Rounding here is exactly what the decimal policy
    exists to prevent, in the one place nobody looks.
    """
    with pytest.raises(ValueError, match="more than"):
        _at_scale(Decimal("10.00000005"), MONEY_SCALE)
    assert _at_scale(Decimal("10.5000"), MONEY_SCALE) == Decimal("10.5")


def test_a_difference_is_null_and_never_zero_when_a_side_is_missing(
    policy_ledger: object, policy_packets: object
) -> None:
    """The distance between a figure that exists and one that does not is not
    nothing, and zero is the reading that says the two agree."""
    for packet in _packets(policy_packets).values():
        for got in for_packet(_ledger(policy_ledger), packet).values():
            if got.derived is None or got.reported is None:
                assert got.difference is None, got.holding_id


def test_every_row_carries_a_recomputation_including_the_ones_it_could_not_run_for(
    policy_ledger: object, policy_packets: object
) -> None:
    """`unconfirmable · Because Market has no document of any kind` is an answer
    to "what did you check". Serving only the rows where the check succeeded
    would report the system's successes as its coverage."""
    for packet in _packets(policy_packets).values():
        computed = for_packet(_ledger(policy_ledger), packet)
        assert set(computed) == {row.holding_id for row in packet.rows}
        sent = packet_json(packet, computed)
        assert set(sent[PACKET_RECOMPUTATION_KEY]) == set(computed)


def test_the_packet_says_no_derivation_ran_rather_than_sending_an_empty_one() -> None:
    """`null` and `{}` are different facts. The fixture branch has no ledger to
    derive from; an empty object would say the derivation ran and had nothing to
    report about any row."""
    from packages.contracts.fixtures.dream import dream_packet

    assert packet_json(dream_packet())[PACKET_RECOMPUTATION_KEY] is None
    assert packet_json(dream_packet(), {})[PACKET_RECOMPUTATION_KEY] == {}


def test_the_wire_carries_the_outcome_and_never_a_boolean(
    policy_ledger: object, policy_packets: object
) -> None:
    """SPEC §8's six values, unordered. A boolean would collapse `not_comparable`
    into a soft fail and `unconfirmable` into a weak pass, which are the two
    readings this whole surface exists to prevent.

    The reason names the DERIVATION and not the verdict —
    `PER_CLASS_SHARES_X_PPS` reads the same whether the figures matched or not —
    so pass/fail cannot be read out of it by accident.
    """
    seen: set[str] = set()
    for packet in _packets(policy_packets).values():
        for got in for_packet(_ledger(policy_ledger), packet).values():
            sent = recomputation_json(got)
            assert sent["outcome"] in {o.value for o in Outcome}
            assert not isinstance(sent["outcome"], bool)
            seen.add(sent["outcome"])
            if got.outcome is Outcome.FAIL:
                assert sent["reason"] == "PER_CLASS_SHARES_X_PPS"
    # And the vocabulary is actually exercised, rather than one value repeated.
    assert {"pass", "fail", "not_comparable", "unconfirmable"} <= seen


@pytest.mark.parametrize("field", ["derived", "reported", "difference"])
def test_every_money_field_on_the_wire_carries_its_currency(
    field: str, policy_ledger: object, policy_packets: object
) -> None:
    """INV-11 · money is never a bare number, including on the way out."""
    for packet in _packets(policy_packets).values():
        for got in for_packet(_ledger(policy_ledger), packet).values():
            value = recomputation_json(got)[field]
            if value is not None:
                assert set(value) == {"amount", "currency"}


def test_nothing_here_writes_a_derived_figure_into_the_stored_mark(
    policy_ledger: object, policy_packets: object
) -> None:
    """The design decision, asserted rather than described.

    SPEC §6.3 binds an approval to `(mark_revision, evidence_set_hash,
    policy_version)` precisely so an approved total cannot follow a moving
    figure. A read-time derivation written into `mark.validated_amount` reopens
    that question, so the recomputation travels beside the mark and the mark is
    left exactly as the ledger holds it.
    """
    for packet in _packets(policy_packets).values():
        computed = for_packet(_ledger(policy_ledger), packet)
        assert computed
        for row in packet.rows:
            if row.mark is not None:
                assert row.mark.validated is None, (
                    f"{row.holding_id}: the recomputation has written to the stored mark"
                )


def test_the_derivation_is_recomputed_and_not_read_from_a_date_it_was_stored_at(
    policy_ledger: object, policy_packets: object
) -> None:
    """Asking twice gives the same answer, and asking about a different date
    gives a different one. A cached figure would pass the first and fail the
    second."""
    packets = _packets(policy_packets)
    ledger = _ledger(policy_ledger)
    at_25q4 = for_packet(ledger, packets[("fund_ii", "fund_ii_25q4")])
    again = for_packet(ledger, packets[("fund_ii", "fund_ii_25q4")])
    assert at_25q4 == again
    at_24q4 = for_packet(ledger, packets[("fund_ii", "fund_ii_24q4")])
    # Fluidstack derives 1,000,000 at 24Q4 and 2,500,000 at 25Q4 — the A-2 lot
    # is acquired in between, and the recomputation follows the date.
    assert at_24q4["fund_ii_fluidstack"].derived != at_25q4["fund_ii_fluidstack"].derived


def test_the_measurement_date_the_recomputation_uses_is_the_packets_own(
    policy_packets: object,
) -> None:
    """Guarding the join rather than the arithmetic: a recomputation keyed to the
    wrong date is a correct figure about the wrong day."""
    for (_, period_id), packet in _packets(policy_packets).items():
        assert packet.period.id == period_id
        assert isinstance(packet.period.period_date, date)
