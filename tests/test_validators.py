"""SPEC §8's validators against the answer key, and against constructed negatives.

Two kinds of gate, and both are needed:

**Against the oracle.** `evals/oracle/derived.json` is an independent derivation
of this corpus, read here as JSON — never imported, because a product that could
import its own answer key would agree with itself at every step. It carries five
of the eight: `entry_costs` (V1), `rows[].validated_amount` with its five refusal
reasons (V2), `concluded_value_checks` (V8), `realization_checks` (V9) and
`recap_checks` (V13). Where the oracle publishes a figure, that figure decides.

**Against constructed negatives.** The corpus contains no fractional exchange
ratio, no quote dated after its measurement date and no realisation with fees, so
the branches that reject those would ship unexercised. A guard that has never
been seen to fail is prose.

Five rows disagree with the oracle on purpose and the disagreement is asserted
rather than tolerated: Moonfare FY2023/FY2024 and Jio FY2023–25 derive from a
concluded value and an administrator NAV that the *documents state* and
`policy.inputs.Ledger` does not carry — `claim.stated_amount` is NULL for every
claim the document ingest writes. `test_v2_is_blocked_on_exactly_the_five_rows…`
names them, asserts the oracle does derive them, and will fail the day the ledger
grows the field, which is the day this exception should stop existing.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from packages.contracts.enums import (
    AuditScope,
    ExecutionStatus,
    PositionType,
    RequirementCode,
    SourceClass,
)
from policy import validators
from policy.inputs import Conversion, EvidenceClaim, Holding, Ledger, Lot, MarkObservation, Period
from policy.valid_tuples import InvalidPolicyInput
from policy.validators import (
    FxRate,
    Outcome,
    RealizationTerms,
    Result,
    RoundStatement,
    realization_from_ledger,
    stated_value,
    v1_all,
    v1_entry_cost,
    v2_mark,
    v4_fully_diluted_shares,
    v7_fx_rate_present,
    v8_fx_recomputation,
    v9_net_reconciliation,
    v9_realization,
    v10_quoted_value,
    v13_recap,
)
from tests.oracle_map import CLAIM, HOLDING, LOT

ROOT = Path(__file__).resolve().parents[1]
DERIVED: dict[str, Any] = json.loads((ROOT / "evals/oracle/derived.json").read_text())

#: Asserted, not counted at runtime. A comparison whose denominator comes from
#: the data it compares cannot report that the data shrank.
EXPECTED_LOTS = 17
EXPECTED_ROWS = 35

#: Moonfare FY2023/FY2024 and Jio FY2023–25 were exempted here, as the five
#: rows whose derived value is a figure the source states and the ledger did not
#: carry. The ledger carries them now: `extracted_fact` is loaded into
#: `EvidenceClaim.facts`, and `policy.validators.stated_value` reads the one
#: field declared as a holding value. All five compare against the oracle like
#: every other row, so the exemption is deleted rather than emptied — an empty
#: allowlist beside a live branch is the shape that reads as coverage and
#: provides none.


def _money(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


# ── V1 · entry cost ──────────────────────────────────────────────────────


def test_v1_reproduces_the_oracles_entry_cost_check(policy_ledger: Ledger) -> None:
    """All seventeen lots, every published field."""
    mine = {r.subject: r for r in v1_all(policy_ledger)}
    problems: list[str] = []
    checked = 0
    for want in DERIVED["entry_costs"]:
        checked += 1
        got = mine[LOT[want["lot"]]]
        where = want["lot"]
        if got.outcome.value != want["check"]:
            problems.append(f"{where}: {got.outcome.value} != {want['check']}")
        if want["check"] == "pass":
            if got.computed != Decimal(want["computed"]):
                problems.append(f"{where}: computed {got.computed} != {want['computed']}")
            if got.stated != Decimal(want["stated"]):
                problems.append(f"{where}: stated {got.stated} != {want['stated']}")
        else:
            if got.computed is not None:
                problems.append(f"{where}: not_applicable but carries a computed {got.computed}")
            if got.stated != Decimal(want["cost"]):
                problems.append(f"{where}: cost {got.stated} != {want['cost']}")
    assert checked == EXPECTED_LOTS, f"compared {checked} lots, expected {EXPECTED_LOTS}"
    assert not problems, "V1 disagrees with the oracle:\n" + "\n".join(problems)


def test_v1_never_passes_a_lot_with_no_share_count(policy_ledger: Ledger) -> None:
    """Moonfare's fund interest, the Mom Project's note and Jio's LP interest.

    Each has a real cost that reconciles to nothing per-share. `pass` would
    report three checks that never ran, and `fail` would report a defect in
    three costs that are correct.
    """
    mine = {r.subject: r for r in v1_all(policy_ledger)}
    for short in ("mf_1", "mom_3", "jio_1"):
        got = mine[LOT[short]]
        assert got.outcome is Outcome.NOT_APPLICABLE, short
        assert got.reason == "NO_SHARE_COUNT", short
        assert got.computed is None, short


# ── V2 · the mark against the evidence ───────────────────────────────────


def _lineage_as_oracle(got: Result) -> list[dict[str, Any]]:
    return [
        {
            "lot": x.lot_id,
            "class": x.security_class,
            "pps": x.price_per_share,
            "shares": x.shares,
            "amount": x.amount,
            "cross_class": x.cross_class,
        }
        for x in got.lineage
    ]


def _oracle_lineage(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "lot": LOT[x["lot"]],
            "class": x["class"],
            "pps": Decimal(x["pps"]),
            "shares": x["shares"],
            "amount": Decimal(x["amount"]),
            "cross_class": x["cross_class"],
        }
        for x in row["derivation_lineage"]
    ]


def _compare_row(policy_ledger: Ledger, row: dict[str, Any]) -> list[str]:
    where = f"{row['holding']}@{row['date']}"
    got = v2_mark(policy_ledger, HOLDING[row["holding"]], date.fromisoformat(row["date"]))
    bad: list[str] = []

    if not row["held_at_date"]:
        if got.outcome is not Outcome.NOT_APPLICABLE:
            bad.append(f"{where}: not held, but {got.outcome.value}")
        if got.reason != "NOT_HELD_AT_MEASUREMENT_DATE":
            bad.append(f"{where}: not held, but reason {got.reason}")
        return bad

    if got.reason != row["derivation_reason"]:
        bad.append(f"{where}: reason {got.reason} != {row['derivation_reason']}")
    # `Result.computed` is what the derivation PRODUCED. The oracle splits that
    # across two keys by what the figure is good for: `validated_amount` when it
    # confirms the mark, `carried_amount` when it is real, cited and confirms
    # nothing because the audited party is its author.
    #
    # This compared `computed` against `validated_amount` alone, which read the
    # two implementations as disagreeing about Moonfare FY2024 when they agreed
    # about every fact of it — both say the figure is 1,048,515 and both say it
    # validates nothing. They differed over which field holds it, and comparing
    # one field to one field could not express that.
    expected_amount = row[
        "carried_amount" if row["carried_amount"] is not None else "validated_amount"
    ]
    if got.computed != _money(expected_amount):
        bad.append(f"{where}: validated {got.computed} != {expected_amount}")
    if got.stated != _money(row["reported_amount"]):
        bad.append(f"{where}: reported {got.stated} != {row['reported_amount']}")

    if row["derivation_status"] == "derivable":
        want = Outcome.PASS if row["validated_matches_reported"] else Outcome.FAIL
        if got.outcome is not want:
            bad.append(f"{where}: {got.outcome.value}, expected {want.value}")
        if _lineage_as_oracle(got) != _oracle_lineage(row):
            bad.append(f"{where}: lineage {_lineage_as_oracle(got)} != {_oracle_lineage(row)}")
    elif row["derivation_status"] == "management_carrying_value":
        # Its own arm. Folding it into the `not derivable` arm below would let
        # `unconfirmable` — "the evidence is silent" — satisfy a row whose whole
        # finding is that the evidence SPOKE, in the voice under audit.
        if got.outcome is not Outcome.NOT_COMPARABLE:
            bad.append(f"{where}: carried figure, but {got.outcome.value}")
    elif got.outcome not in (Outcome.UNCONFIRMABLE, Outcome.BLOCKED_INCOMPLETE):
        bad.append(f"{where}: not derivable, but {got.outcome.value}")
    return bad


def test_v2_reproduces_the_oracle_row_by_row(policy_ledger: Ledger) -> None:
    """Every row, every published field: value, reason, and the per-lot lineage.

    The lineage is compared and not just the total, because Lucra's total is
    reachable from the wrong price and the right number of shares as easily as
    from the right price — and the packet prints the lineage.
    """
    problems: list[str] = []
    checked = 0
    for row in DERIVED["rows"]:
        checked += 1
        problems += _compare_row(policy_ledger, row)
    assert checked == EXPECTED_ROWS, f"compared {checked} rows, expected {EXPECTED_ROWS}"
    assert not problems, f"{len(problems)} disagreement(s) with the oracle:\n" + "\n".join(
        problems[:25]
    )


def test_v2_reports_lucras_finding_at_the_lot_that_causes_it(policy_ledger: Ledger) -> None:
    """The real finding: 2,250,000 reported, 1,500,000 derived.

    The fund holds 750,000 Series A-1 at $2.00 from the term sheet; the mark
    uses the Series A-2 price of $3.00 from a CEO email. Pricing the lot from
    its own class is what makes the difference visible, so the lot's class and
    price are asserted here and not only the total — a holding-level price
    would derive 2,250,000 and report the mark as supported.
    """
    got = v2_mark(policy_ledger, HOLDING["lucra"], date(2025, 12, 31))
    assert got.outcome is Outcome.FAIL
    assert got.reason == "PER_CLASS_SHARES_X_PPS"
    assert got.computed == Decimal("1500000")
    assert got.stated == Decimal("2250000")
    assert got.delta == Decimal("750000")
    assert len(got.lineage) == 1
    (lot,) = got.lineage
    assert (lot.lot_id, lot.security_class, lot.shares) == (LOT["lucra_1"], "series_a1", 750000)
    assert lot.price_per_share == Decimal("2.00")
    assert lot.cross_class is False


@pytest.mark.parametrize(
    ("holding", "on", "field_name", "amount", "reason"),
    [
        ("moonfare", "2023-12-31", "concluded_fair_value_usd", "1000000", "THIRD_PARTY_CONCLUSION"),
        # Moonfare FY2024 was here, asserting THIRD_PARTY_CONCLUSION and `pass`.
        # It is not a third party's conclusion and it does not pass; it has its
        # own case below. It is moved rather than deleted because the half of
        # this test it still exercises — that the figure is read from the
        # DECLARED field name and not the first amount on the claim — is exactly
        # what that claim was chosen to prove.
        ("jio", "2023-12-31", "net_asset_value", "1000000", "ADMINISTRATOR_NAV"),
        ("jio", "2024-12-31", "net_asset_value", "1000000", "ADMINISTRATOR_NAV"),
        ("jio", "2025-12-31", "net_asset_value", "1000000", "ADMINISTRATOR_NAV"),
    ],
)
def test_v2_derives_these_four_rows_from_a_named_cited_figure(
    policy_ledger: Ledger, holding: str, on: str, field_name: str, amount: str, reason: str
) -> None:
    """Four of the five rows that were `blocked_incomplete`, now derived — and
    derived from a figure named rather than found.

    Moonfare's memos state a concluded value and Jio's statements state a net
    asset value. Both were cited facts in `extracted_fact` that reached nothing:
    the ingest never writes `claim.stated_amount` and nothing loaded the facts.

    The assertion is on the FIELD NAME as much as the number, because Moonfare's
    FY2024 remeasurement cites two amounts — `usd_carrying_value` 1,048,515 and
    `prior_usd_carrying_value` 1,000,000 — and a rule that took the first
    amount-bearing fact would mark the position at last year's figure and
    reconcile perfectly to itself. Only the declared name separates them.
    """
    at = date.fromisoformat(on)
    got = v2_mark(policy_ledger, HOLDING[holding], at)
    assert got.outcome is Outcome.PASS
    assert got.reason == reason
    assert got.computed == Decimal(amount)

    (claim_id,) = got.evidence
    claim = next(c for c in policy_ledger.claims if c.id == claim_id)
    assert claim.facts[field_name] == Decimal(amount)
    assert stated_value(claim) == Decimal(amount)


def test_v2_will_not_let_the_fund_validate_its_own_mark(policy_ledger: Ledger) -> None:
    """The fifth row, and the reason it is no longer beside the other four.

    Moonfare's FY2024 memo states `usd_carrying_value` 1,048,515 and the tracker
    reports 1,048,515, so V2 derived the mark, matched it, and reported `pass` —
    citing the memo as a `THIRD_PARTY_CONCLUSION`. The memo says who wrote it:
    "Prepared by Fund Operations; reviewed by the CFO." It is the fund's own
    paperwork about the fund's own position.

    `derive_mark` preferred any amount-bearing claim that was not an
    administrator statement and named the result a third party's conclusion, so
    management's memo validated management's mark and the row reconciled
    perfectly to itself. That is the shape this project exists to refuse: not a
    number that looks wrong, a number that looks right for a reason nobody
    checked.

    `not_comparable`, not `fail`. Nothing here says 1,048,515 is the wrong
    figure — it may well be right. What is being reported is that the only
    evidence for it is the audited party's own assertion, which is a question
    for the auditor rather than an arithmetic error. The requirement layer said
    so all along: `r2` returns `insufficient` /
    `MANAGEMENT_ASSERTION_WITHOUT_PRIMARY_SOURCE` for this same claim, and for
    175 comparisons the two layers disagreed about one document while the oracle
    — sharing the authorship — agreed with the wrong one.
    """
    got = v2_mark(policy_ledger, HOLDING["moonfare"], date(2024, 12, 31))
    assert got.outcome is Outcome.NOT_COMPARABLE
    assert got.reason == "MANAGEMENT_CARRYING_VALUE"
    # The figure IS carried, and the outcome is what withholds confirmation.
    # Dropping it would leave the packet unable to show that the fund's own memo
    # and the reported mark are the same number — which is the finding, not a
    # detail. The oracle publishes it as `carried_amount` for the same reason.
    assert got.computed == Decimal("1048515")
    assert got.stated == Decimal("1048515")

    (claim_id,) = got.evidence
    claim = next(c for c in policy_ledger.claims if c.id == claim_id)
    assert claim.source_class is SourceClass.FUND_INTERNAL_RECORD
    # The figure is still cited and still readable. It is the AUTHORITY that
    # disqualifies it, not an absence — so a future change that made this
    # `unconfirmable` ("the evidence says nothing") would be wrong in a way this
    # assertion catches.
    assert claim.facts["usd_carrying_value"] == Decimal("1048515")


def test_a_claim_naming_two_holding_values_refuses_rather_than_choosing(
    policy_ledger: Ledger,
) -> None:
    """The guard on the ambiguity above, exercised on the real claim.

    Widening `VALUE_FIELDS` to include `prior_usd_carrying_value` — the cheapest
    way to make a future Moonfare-shaped document "work" — makes this claim
    state two holding values, and `stated_value` refuses instead of letting sort
    order decide which year the fund is marked at.
    """
    claim = next(c for c in policy_ledger.claims if "fy2024_fx_remeasurement" in c.id)
    assert {"usd_carrying_value", "prior_usd_carrying_value"} <= set(claim.facts)
    widened = validators.VALUE_FIELDS | {"prior_usd_carrying_value"}
    with (
        mock.patch.object(validators, "VALUE_FIELDS", widened),
        pytest.raises(InvalidPolicyInput, match="declared as a holding value"),
    ):
        stated_value(claim)


def test_the_v2_census_over_the_corpus_is_what_the_oracle_implies(policy_ledger: Ledger) -> None:
    """Thirty-five rows, six outcomes, counted.

    15 pass and 2 fail are the seventeen rows the ledger can value; 1
    not_comparable is Moonfare FY2024; 13 unconfirmable are the rows whose
    evidence says nothing; 3 blocked are the Mom Project's three dates, where a
    convertible note with no share count sits beside two priced equity lots; 1
    not_applicable is Jackpocket after its May 2024 realisation.

    `pass` was 11 and `blocked_incomplete` was 8 until `extracted_fact` reached
    the policy inputs. The five that moved are Moonfare FY2023/24 and Jio
    FY2023–25, and they moved because the ledger began carrying a figure it
    already held — not because a rule was relaxed.

    Two cells moved again, and neither by relaxing anything:

    * **Moonfare FY2024 left `pass` for `not_comparable`**, which is why this
      census has a sixth outcome. `derive_mark` preferred any amount-bearing
      claim that was not an administrator statement and called the result a
      third party's conclusion — so the fund's OWN FX memo ("Prepared by Fund
      Operations; reviewed by the CFO") validated the fund's own mark, and V2
      reported `pass` on 1,048,515 against a stated 1,048,515. It reconciled
      perfectly to itself. Only FY2024 moves: FY2023's memo is Clearwater's and
      is a third party's conclusion in fact as well as in name.
    * **Fluidstack 25Q4 left `unconfirmable` for `fail`.** It was
      `NO_PRICE_FOR_CLASS:series_a2` while the corpus held that price, cited, on
      a claim relied upon for nothing. Reachable, V2 derives 100,000×$10 +
      100,000×$15 = 2,500,000 against a reported 6,000,000. The count went UP by
      one failure because a check that could not run now can.

    So `fail` is 2, and the pair is named rather than counted: a census that
    only counted would read the same if these two swapped places with any other
    two rows.
    """
    census: dict[str, int] = {}
    failing: list[str] = []
    for row in DERIVED["rows"]:
        got = v2_mark(policy_ledger, HOLDING[row["holding"]], date.fromisoformat(row["date"]))
        census[got.outcome.value] = census.get(got.outcome.value, 0) + 1
        if got.outcome is Outcome.FAIL:
            failing.append(f"{row['holding']}@{row['date']}")
    assert census == {
        "pass": 15,
        "fail": 2,
        "not_comparable": 1,
        "unconfirmable": 13,
        "blocked_incomplete": 3,
        "not_applicable": 1,
    }
    assert sorted(failing) == ["fluidstack@2025-12-31", "lucra@2025-12-31"]


# ── V8 · FX recomputation ────────────────────────────────────────────────

#: Transcribed from the two Moonfare memos, which is where the oracle's
#: primitives come from too. The ledger carries neither figure (see the module
#: docstring), so the recomputation is exercised over the source facts and its
#: RESULT is compared against the oracle's independent derivation.
MOONFARE_EUR = Decimal("950000")


def _moonfare_rate(document: str, rate: str, on: date) -> FxRate:
    return FxRate(
        base="EUR",
        quote="USD",
        rate=Decimal(rate),
        observed_date=on,
        effective_for=on,
        source_claim_id=CLAIM[document],
        source_document_version_id=f"dv_{document}",
    )


def test_v8_reproduces_both_of_the_oracles_concluded_value_checks() -> None:
    """FY2023 is a 30-dollar rounding variance and PASSES; FY2024 is exact.

    950,000 × 1.0526 = 999,970 against a concluded 1,000,000 the memo itself
    labels rounded. A validator that asserted equality would go red on a
    correct number, and the repair someone reaches for next is writing 999,970
    back over an audited third party's conclusion (INV-1).
    """
    rates = {
        "moonfare_memo_23": _moonfare_rate("moonfare_memo_23", "1.0526", date(2023, 12, 31)),
        "moonfare_fx_24": _moonfare_rate("moonfare_fx_24", "1.1037", date(2024, 12, 31)),
    }
    checked = 0
    for want in DERIVED["concluded_value_checks"]:
        checked += 1
        got = v8_fx_recomputation(
            subject=want["document"],
            concluded=Decimal(want["concluded_value"]),
            foreign_amount=MOONFARE_EUR,
            rate=rates[want["document"]],
            rounding_unit=Decimal("1000"),
        )
        assert got.computed == Decimal(want["recomputed"]), want["document"]
        assert got.delta == Decimal(want["variance"]), want["document"]
        assert got.reason == want["classification"], want["document"]
        assert got.outcome.value == want["check"], want["document"]
        assert got.evidence == (CLAIM[want["document"]],), want["document"]
    assert checked == 2


def test_v8_stores_both_figures_and_writes_neither_over_the_other() -> None:
    """INV-1 · the concluded value is authoritative; the recomputation is a
    cross-check. Both survive the call, and the delta is derived from the pair
    rather than stored beside it."""
    got = v8_fx_recomputation(
        subject="moonfare_memo_23",
        concluded=Decimal("1000000"),
        foreign_amount=MOONFARE_EUR,
        rate=_moonfare_rate("moonfare_memo_23", "1.0526", date(2023, 12, 31)),
        rounding_unit=Decimal("1000"),
    )
    assert (got.stated, got.computed, got.delta) == (
        Decimal("1000000"),
        Decimal("999970"),
        Decimal("30"),
    )


def test_v8_routes_an_unexplained_variance_to_a_person_instead_of_a_tolerance() -> None:
    """A variance nobody declared a rounding rule for is a finding.

    Without a stated rounding unit the same 30 dollars is not a rounding
    variance, because nothing in the source says the figure was rounded. SPEC
    §15 cut V8 to explicit classification only for exactly this reason: a
    tolerance inferred from the number it is checking grows to fit whatever it
    finds.
    """
    got = v8_fx_recomputation(
        subject="moonfare_memo_23",
        concluded=Decimal("1000000"),
        foreign_amount=MOONFARE_EUR,
        rate=_moonfare_rate("moonfare_memo_23", "1.0526", date(2023, 12, 31)),
    )
    assert got.outcome is Outcome.FAIL
    assert got.reason == "UNRECOGNISED_VARIANCE"
    assert got.computed == Decimal("999970")
    assert got.stated == Decimal("1000000")


# ── V7 · an FX rate observed for THIS measurement date ───────────────────


def test_v7_goes_red_on_moonfare_fy2025_which_has_no_rate(policy_ledger: Ledger) -> None:
    """INV-6 · the guard that must fail on the real data.

    Both memos close their own reliance window at their measurement date, so
    at 12/31/2025 nothing is in scope and there is no rate to be had. Carrying
    1,048,515 forward is the failure this exists to make visible, and it is a
    failure that reconciles to itself perfectly.
    """
    got = v7_fx_rate_present(policy_ledger, HOLDING["moonfare"], date(2025, 12, 31))
    assert got.outcome is Outcome.FAIL
    assert got.reason == "unsupported_missing_fx"


def test_v7_separates_a_missing_rate_from_an_unloaded_one(policy_ledger: Ledger) -> None:
    """FY2023 and FY2024 have a cited rate in the file and none in the ledger."""
    for on in (date(2023, 12, 31), date(2024, 12, 31)):
        got = v7_fx_rate_present(policy_ledger, HOLDING["moonfare"], on)
        assert got.outcome is Outcome.BLOCKED_INCOMPLETE, on
        assert got.reason == "FX_RATE_NOT_IN_LEDGER", on
        assert got.evidence, on


def test_v7_passes_on_a_rate_observed_for_the_date(policy_ledger: Ledger) -> None:
    on = date(2023, 12, 31)
    got = v7_fx_rate_present(
        policy_ledger,
        HOLDING["moonfare"],
        on,
        [_moonfare_rate("moonfare_memo_23", "1.0526", on)],
    )
    assert got.outcome is Outcome.PASS
    assert got.computed == Decimal("1.0526")


def test_v7_never_reuses_a_prior_periods_rate(policy_ledger: Ledger) -> None:
    """The 12/31/2023 rate is not evidence about 12/31/2024, however present."""
    got = v7_fx_rate_present(
        policy_ledger,
        HOLDING["moonfare"],
        date(2024, 12, 31),
        [_moonfare_rate("moonfare_memo_23", "1.0526", date(2023, 12, 31))],
    )
    assert got.outcome is Outcome.FAIL
    assert got.reason == "unsupported_missing_fx"


def test_v7_rejects_a_stale_rate_relabelled_with_a_new_effective_date(
    policy_ledger: Ledger,
) -> None:
    """The collapse the invariant sweep named: copy the value, change the date.

    A rate observed on 12/31/2023 and marked effective for 12/31/2024 satisfies
    every date-equality check and is still the prior period's number.
    """
    relabelled = FxRate(
        base="EUR",
        quote="USD",
        rate=Decimal("1.0526"),
        observed_date=date(2023, 12, 31),
        effective_for=date(2024, 12, 31),
        source_claim_id=CLAIM["moonfare_memo_23"],
        source_document_version_id="dv_moonfare_memo_23",
    )
    got = v7_fx_rate_present(policy_ledger, HOLDING["moonfare"], date(2024, 12, 31), [relabelled])
    assert got.outcome is Outcome.FAIL
    assert got.reason == "FX_RATE_NOT_OBSERVED_FOR_DATE"


def test_v7_does_not_arise_for_a_position_that_is_not_fx_denominated(
    policy_ledger: Ledger,
) -> None:
    got = v7_fx_rate_present(policy_ledger, HOLDING["poolside"], date(2025, 12, 31))
    assert got.outcome is Outcome.NOT_APPLICABLE
    assert got.reason == "NOT_AN_FX_DENOMINATED_POSITION"


def test_v7_will_not_read_an_open_reliance_window_as_a_rate_for_this_date() -> None:
    """The distinction the corpus cannot exhibit, because its dates coincide.

    Every FX memo here is dated at its own measurement date, so "this claim is
    in scope at `on`" and "this claim cites a rate FOR `on`" agree on every
    holding-date in the corpus. A V7 that confuses them therefore stays green
    on real data — which is exactly what happened when Moonfare's FY2024 window
    was briefly opened and the only thing that went red was a test pinning a
    verdict, one layer away from the defect.

    So the case is built rather than found: one claim, window deliberately
    OPEN, citing a rate effective for the PRIOR year end. `blocked_incomplete`
    here would assert that a 12/31/2025 rate exists and has not been loaded.
    None exists. Reporting the gap is the whole of INV-6.
    """
    stale = _claim(
        "c_stale",
        SourceClass.FUND_INTERNAL_RECORD,
        date(2025, 1, 1),
        applicable_to=None,
        facts={"fx_rate": Decimal("1.1037")},
        fact_dates={"fx_rate_effective_date": date(2024, 12, 31)},
    )
    ledger = _one_holding_ledger(
        stale,
        position_type=PositionType.FX_DENOMINATED_INTEREST,
        mark=Decimal("1048515"),
    )
    got = v7_fx_rate_present(ledger, "h", date(2025, 12, 31))
    assert got.outcome is Outcome.FAIL
    assert got.reason == "unsupported_missing_fx"


def test_v7_reports_an_unloaded_rate_only_when_one_is_cited_for_the_date() -> None:
    """The twin of the case above, and the half of the pair that must NOT move.

    Identical in every field but the cited effective date. The pair is the
    guard: under "in scope is enough" both are `blocked_incomplete`, and under
    the rule INV-6 asks for they differ. Either test alone can be satisfied by
    the wrong rule, so neither is dropped without the other.
    """
    for_this_date = _claim(
        "c_current",
        SourceClass.FUND_INTERNAL_RECORD,
        date(2025, 1, 1),
        applicable_to=None,
        facts={"fx_rate": Decimal("1.1500")},
        fact_dates={"fx_rate_effective_date": date(2025, 12, 31)},
    )
    ledger = _one_holding_ledger(
        for_this_date,
        position_type=PositionType.FX_DENOMINATED_INTEREST,
        mark=Decimal("1048515"),
    )
    got = v7_fx_rate_present(ledger, "h", date(2025, 12, 31))
    assert got.outcome is Outcome.BLOCKED_INCOMPLETE
    assert got.reason == "FX_RATE_NOT_IN_LEDGER"
    assert got.evidence == ("c_current",)


# ── V9 · realisation ─────────────────────────────────────────────────────


def test_v9_reproduces_the_oracles_realization_check(policy_ledger: Ledger) -> None:
    """Jackpocket: 500,000 × $6.20 = $3,100,000, computed from the ledger.

    The stated gross is a cited fact on the merger notice and is not in the
    ledger, so the ledger-driven result is `blocked_incomplete` carrying the
    computed figure — which is still the number an auditor checks the wire
    against, and is not the same as silence.
    """
    (want,) = DERIVED["realization_checks"]
    results = {
        r.subject: r
        for r in realization_from_ledger(policy_ledger, HOLDING["jackpocket"], date(2024, 12, 31))
    }
    got = results[LOT[want["lot"]]]
    assert got.computed == Decimal(want["gross"])
    assert got.outcome is Outcome.BLOCKED_INCOMPLETE
    assert got.reason == "NO_STATED_GROSS_IN_LEDGER"
    assert got.evidence == (CLAIM["jackpocket_merger"],)

    supplied = v9_realization(
        RealizationTerms(
            lot_id=LOT[want["lot"]],
            realized_on=date.fromisoformat(want["realized"]),
            realized_shares=want["shares"],
            cash_per_share=Decimal(want["cash_per_share"]),
            stated_gross=Decimal(want["stated_gross"]),
        )
    )
    assert supplied.outcome.value == want["check"]
    assert supplied.computed == Decimal(want["gross"])


def test_v9_never_nets_fees_against_the_gross_formula() -> None:
    """Gross is shares × cash per share. Fees reconcile on their own line.

    A gross check that quietly became a net check would agree with a wire that
    is short by the escrow, and the two figures would never be compared again.
    """
    terms = RealizationTerms(
        lot_id="probe",
        realized_on=date(2024, 5, 20),
        realized_shares=500000,
        cash_per_share=Decimal("6.20"),
        stated_gross=Decimal("3000000"),
        stated_net=Decimal("3000000"),
        fees=Decimal("40000"),
        escrow=Decimal("50000"),
        earnout=Decimal("10000"),
    )
    gross = v9_realization(terms)
    assert gross.outcome is Outcome.FAIL
    assert gross.computed == Decimal("3100000")
    assert gross.delta == Decimal("-100000")

    net = v9_net_reconciliation(terms)
    assert net.outcome is Outcome.PASS
    assert net.computed == Decimal("3000000")


# ── V13 · recapitalisation ───────────────────────────────────────────────


def test_v13_reproduces_the_oracles_recap_check(policy_ledger: Ledger) -> None:
    """Sway: 800,000 × 1.09375 = 875,000, exactly."""
    (want,) = DERIVED["recap_checks"]
    (got,) = [v13_recap(x) for x in policy_ledger.lots if x.id == LOT[want["lot"]]]
    assert got.outcome.value == want["check"]
    assert got.reason == "PRIOR_SHARES_X_EXCHANGE_RATIO"
    assert got.computed == Decimal(want["computed"])
    assert got.stated == Decimal(str(want["stated"]))


def test_v13_rejects_a_ratio_that_produces_a_fractional_share() -> None:
    """INV-11 · cash-in-lieu is out of scope, so this is a rejection.

    Rounding 875,000.5 to 875,001 would put a share count in the ledger that
    no document states, and the rounding rule would then be the only place the
    fund's holding is defined.
    """
    lot = Lot(
        id="probe",
        holding_id="h",
        security_class="series_a",
        shares=800001,
        entry_pps=Decimal("2.50"),
        cost_amount=Decimal("2000002.50"),
        cost_currency="USD",
        acquired_date=date(2023, 10, 18),
        conversion=Conversion(
            effective_date=date(2025, 9, 30),
            security_class="series_a3",
            shares=875001,
            exchange_ratio=Decimal("1.09375"),
        ),
    )
    got = v13_recap(lot)
    assert got.outcome is Outcome.FAIL
    assert got.reason == "FRACTIONAL_SHARE_UNSUPPORTED"
    assert got.computed == Decimal("875001.09375")


def test_v13_does_not_arise_for_a_lot_that_never_converted(policy_ledger: Ledger) -> None:
    (got,) = [v13_recap(x) for x in policy_ledger.lots if x.id == LOT["pool_1"]]
    assert got.outcome is Outcome.NOT_APPLICABLE
    assert got.reason == "NO_RECORDED_CONVERSION"


# ── V10 · quoted value ───────────────────────────────────────────────────


def test_v10_takes_the_last_completed_session_on_or_before_the_measurement_date(
    policy_ledger: Ledger,
) -> None:
    """Banzai FY2023 closes on 12/29/2023 — the year ended on a Sunday.

    A check demanding a quote dated exactly at the measurement date reports a
    correct figure as missing; a check taking the most recent quote in the file
    uses the 12/31/2024 close for FY2023. Both directions are asserted: the
    chosen claim's own date, and the value it derives.
    """
    quotes = {c.id: c for c in policy_ledger.claims}
    expected = {
        date(2023, 12, 31): (date(2023, 12, 29), "banzai_quote_23", Decimal("120000")),
        date(2024, 12, 31): (date(2024, 12, 31), "banzai_quote_24", Decimal("55000")),
        date(2025, 12, 31): (date(2025, 12, 31), "banzai_quote_25", Decimal("31000")),
    }
    for on, (quoted_on, short, value) in expected.items():
        got = v10_quoted_value(policy_ledger, HOLDING["banzai"], on)
        assert got.outcome is Outcome.PASS, on
        assert got.reason == "QUOTED_CLOSE_X_SHARES", on
        assert got.computed == value, on
        assert got.stated == value, on
        assert got.evidence == (CLAIM[short],), (on, got.evidence)
        assert quotes[got.evidence[0]].issued_date == quoted_on, on


def test_v10_does_not_arise_for_a_position_that_is_not_listed(policy_ledger: Ledger) -> None:
    got = v10_quoted_value(policy_ledger, HOLDING["poolside"], date(2025, 12, 31))
    assert got.outcome is Outcome.NOT_APPLICABLE
    assert got.reason == "NOT_A_LISTED_POSITION"


def _claim(claim_id: str, source_class: SourceClass, issued: date, **figures: Any) -> EvidenceClaim:
    return EvidenceClaim(
        id=claim_id,
        holding_id="h",
        source_class=source_class,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=issued,
        applicable_from=date(2025, 1, 1),
        requirements=frozenset({RequirementCode.R2}),
        **figures,
    )


def _one_holding_ledger(
    *claims: EvidenceClaim, position_type: PositionType, mark: Decimal
) -> Ledger:
    """One holding, one 50,000-share lot, and whatever the case needs to say.

    For the branches the corpus does not contain. Built from the real input
    types rather than from stubs, so a case that only exists here is still
    reading the same `Ledger` the ledger-driven paths read.
    """
    return Ledger(
        holdings={"h": Holding(id="h", fund_id="f", position_type=position_type)},
        periods={"p": Period("p", "f", date(2025, 12, 31), AuditScope.PACKET)},
        lots=(
            Lot(
                id="lot",
                holding_id="h",
                security_class="common",
                shares=50000,
                entry_pps=Decimal("10.00"),
                cost_amount=Decimal("500000"),
                cost_currency="USD",
                acquired_date=date(2021, 3, 4),
            ),
        ),
        claims=claims,
        gaps=(),
        marks=(MarkObservation("h", "p", mark),),
    )


def test_v10_refuses_a_quote_dated_after_the_measurement_date() -> None:
    """A session that had not closed yet is not evidence about the year end."""
    ledger = _one_holding_ledger(
        _claim(
            "quote",
            SourceClass.PUBLIC_MARKET_QUOTE,
            date(2026, 1, 5),
            priced_class="common",
            price_per_share=Decimal("0.62"),
        ),
        position_type=PositionType.PUBLIC_LISTED,
        mark=Decimal("31000"),
    )
    got = v10_quoted_value(ledger, "h", date(2025, 12, 31))
    assert got.outcome is Outcome.FAIL
    assert got.reason == "QUOTE_AFTER_MEASUREMENT_DATE"
    assert got.evidence == ("quote",)


# ── V2's two authority branches, which this corpus cannot reach ──────────
#
# Both need `claim.stated_amount`, which the document ingest never writes. They
# are exercised here on constructed inputs so that the priority order is a rule
# something proved, rather than an ordering nobody has run.

_MEMO = SourceClass.THIRD_PARTY_VALUATION_MEMO
_ADMIN = SourceClass.ADMINISTRATOR_STATEMENT


def test_v2_takes_a_third_partys_conclusion_over_an_administrators_nav() -> None:
    """INV-1 · the concluded value stands as concluded.

    The NAV states a different figure and the shares state a third. Priority is
    authority, not recency and not whichever the loop reached first.
    """
    ledger = _one_holding_ledger(
        _claim(
            "nav",
            _ADMIN,
            date(2025, 12, 31),
            stated_amount=Decimal("900000"),
            stated_currency="USD",
        ),
        _claim(
            "memo",
            _MEMO,
            date(2025, 6, 30),
            stated_amount=Decimal("750000"),
            stated_currency="USD",
        ),
        _claim(
            "price",
            SourceClass.COMPANY_CAP_TABLE,
            date(2025, 3, 31),
            priced_class="common",
            price_per_share=Decimal("20.00"),
        ),
        position_type=PositionType.DIRECT_EQUITY,
        mark=Decimal("750000"),
    )
    got = v2_mark(ledger, "h", date(2025, 12, 31))
    assert got.outcome is Outcome.PASS
    assert got.reason == "THIRD_PARTY_CONCLUSION"
    assert got.computed == Decimal("750000")
    assert got.evidence == ("memo",)


def test_v2_takes_an_administrators_nav_when_that_is_the_authority_present() -> None:
    ledger = _one_holding_ledger(
        _claim(
            "nav",
            _ADMIN,
            date(2025, 12, 31),
            stated_amount=Decimal("900000"),
            stated_currency="USD",
        ),
        position_type=PositionType.INDIRECT_FEEDER,
        mark=Decimal("900000"),
    )
    got = v2_mark(ledger, "h", date(2025, 12, 31))
    assert got.outcome is Outcome.PASS
    assert got.reason == "ADMINISTRATOR_NAV"
    assert got.computed == Decimal("900000")


# ── V4 · post-money ÷ price per share ────────────────────────────────────

DREAM_ROUND = RoundStatement(
    claim_id=CLAIM["dream_b_cap"],
    company="dream",
    round_name="series_b",
    effective_date=date(2025, 11, 14),
    currency="USD",
    capitalization_scope="fully_diluted",
)


def test_v4_reconciles_dreams_stated_fully_diluted_count() -> None:
    """$800,000,000 ÷ $8.00 = 100,000,000, and the cap table says 100,000,000."""
    got = v4_fully_diluted_shares(
        post_money=Decimal("800000000"),
        price_per_share=Decimal("8.00"),
        stated_shares=Decimal("100000000"),
        source=DREAM_ROUND,
    )
    assert got.outcome is Outcome.PASS
    assert got.reason == "POST_MONEY_OVER_PRICE_PER_SHARE"
    assert got.computed == Decimal("100000000")


def test_v4_reports_a_mismatch_as_not_comparable_and_stores_the_delta() -> None:
    """SPEC §15 · exact Decimal equality, and a mismatch is `not_comparable`.

    A source that states a rounded post-money cannot be made to reconcile by a
    tolerance, and calling the difference a failure would put a defect on the
    fund for a number the document rounded on purpose. The delta is stored so
    the size of the gap is on the record either way.
    """
    got = v4_fully_diluted_shares(
        post_money=Decimal("800000000"),
        price_per_share=Decimal("8.00"),
        stated_shares=Decimal("99000000"),
        source=DREAM_ROUND,
    )
    assert got.outcome is Outcome.NOT_COMPARABLE
    assert got.delta == Decimal("-1000000")


def test_v4_will_not_join_figures_from_different_rounds() -> None:
    """Two post-money valuations of one company on different bases are not two
    readings of one number."""
    other = RoundStatement(
        claim_id=CLAIM["fluidstack_b_cap"],
        company="dream",
        round_name="series_a1",
        effective_date=date(2025, 8, 1),
        currency="USD",
        capitalization_scope="fully_diluted",
    )
    got = v4_fully_diluted_shares(
        post_money=Decimal("800000000"),
        price_per_share=Decimal("8.00"),
        stated_shares=Decimal("100000000"),
        source=DREAM_ROUND,
        shares_source=other,
    )
    assert got.outcome is Outcome.NOT_COMPARABLE
    assert got.reason == "JOIN_KEYS_DIFFER"
    assert got.computed is None


# ── The vocabulary itself ────────────────────────────────────────────────


def test_no_validator_returns_a_result_without_a_reason(policy_ledger: Ledger) -> None:
    """Every outcome carries a reason code, including `pass`.

    A `not_applicable` with no reason and a `pass` with no reason render the
    same way in a packet, which is the failure SPEC §8's vocabulary exists to
    prevent.
    """
    results: list[Result] = list(v1_all(policy_ledger))
    for row in DERIVED["rows"]:
        holding, on = HOLDING[row["holding"]], date.fromisoformat(row["date"])
        results.append(v2_mark(policy_ledger, holding, on))
        results.append(v7_fx_rate_present(policy_ledger, holding, on))
        results.append(v10_quoted_value(policy_ledger, holding, on))
        results += realization_from_ledger(policy_ledger, holding, on)
    assert results
    #: The comparison validators. V7 asks whether a rate exists at all, so its
    #: `fail` is the absence itself and there is no pair of figures to carry —
    #: which is a different shape of finding, not a missing field.
    comparisons = {"V1", "V2", "V9", "V10", "V13"}
    for got in results:
        assert isinstance(got.outcome, Outcome), got
        assert got.reason, got
        if got.validator in comparisons and got.outcome in (Outcome.PASS, Outcome.FAIL):
            assert got.computed is not None and got.stated is not None, got


def test_a_lot_with_no_share_count_is_not_a_pass_anywhere(policy_ledger: Ledger) -> None:
    """The one collapse that would make three positions look checked."""
    for short in ("mf_1", "mom_3", "jio_1"):
        (lot,) = [x for x in policy_ledger.lots if x.id == LOT[short]]
        assert v1_entry_cost(lot).outcome is not Outcome.PASS
        assert v13_recap(lot).outcome is not Outcome.PASS
