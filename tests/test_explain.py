"""The guard on the plain-English restatement.

Every test here runs without a network and without a database, because the
guard is the whole safety argument and a safety argument that only holds when
the model is reachable is not one. What the model actually writes is a
recall question; what it is ALLOWED to have written is this file.
"""

from __future__ import annotations

from typing import Any

import pytest

from evidence.explain import MAX_CHARS, Refused, accept, check, numerals
from packages.contracts.enums import RequirementVerdict

#: Lucra at FY2024, transcribed from the row the UI renders. The figures are
#: the ones the record actually holds, which is what makes the invented-figure
#: tests below mean anything.
LUCRA: dict[str, Any] = {
    "holding": "Lucra",
    "measurement_date": "2024-12-31",
    "requirement": "R2",
    "verdict": "insufficient",
    "reason_codes": ["NON_BINDING_TERM_SHEET"],
    "reasons": [
        {
            "code": "NON_BINDING_TERM_SHEET",
            "label": "a non-binding term sheet",
            "meaning": "Terms nobody is committed to.",
        }
    ],
    "next_actions": [],
    "asked_elsewhere": ["R1"],
    "evidence": [
        {
            "claim_key": "series_a1_price",
            "price_per_share": "2.00",
            "issued_date": "2024-05-20",
            "quote": "Series A-1 Preferred at $2.00 per share",
        }
    ],
}


def test_a_figure_the_record_does_not_hold_is_refused() -> None:
    """The failure this whole module exists for.

    $2.40 is not in the payload. It is close enough to $2.00 to read as
    correct, which is precisely why a reader would not catch it and the guard
    must.
    """
    with pytest.raises(Refused, match="2.40"):
        check("The term sheet prices the shares at $2.40, which nobody is committed to.", LUCRA)


def test_arithmetic_over_figures_that_are_in_the_record_is_still_refused() -> None:
    """Both inputs present, the result absent — the subtlest wrong number.

    A model that multiplies a price by a share count produces a figure that is
    arithmetically derivable from the payload and is not IN it. The record is
    the only thing entitled to state a total.
    """
    with pytest.raises(Refused, match="4"):
        check("Two lots at $2.00 each come to $4.00 in total.", LUCRA)


def test_a_figure_reformatted_is_not_a_figure_invented() -> None:
    """`1,250,000` and `1250000` are one number written two ways.

    Refusing this would make the guard fire on correct output, and a guard that
    cries wolf is one somebody eventually turns off.
    """
    payload = {"verdict": "partial", "amount": "1250000"}
    check("Support is partial. The record carries 1,250,000 against this position.", payload)


def test_a_figure_ending_a_sentence_keeps_its_full_stop_out_of_the_comparison() -> None:
    payload = {"verdict": "partial", "price": "3.00"}
    check("Support is partial. The email states a price per share of $3.00.", payload)


def test_a_verdict_the_row_did_not_reach_is_refused() -> None:
    """Wrong in a way no numeral check would catch.

    "Sufficient" is the sentence a fluent model writes when the reasons are
    complicated, and it inverts the finding while every figure stays correct.
    """
    with pytest.raises(Refused, match="sufficient"):
        check("The evidence here is sufficient for the year-end mark.", LUCRA)


def test_the_rows_own_verdict_may_be_named_even_though_it_contains_another() -> None:
    """`insufficient` contains `sufficient`, and the guard must not see it.

    Without a word boundary this refuses every correct restatement of an
    insufficient row — the single most common row in the packet — and the
    feature would look broken rather than careful.
    """
    check("The support is insufficient because the only document is unsigned.", LUCRA)


def test_a_restatement_longer_than_a_reader_will_check_is_refused() -> None:
    with pytest.raises(Refused, match="cap"):
        check("word " * MAX_CHARS, LUCRA)


def test_nothing_at_all_is_refused_rather_than_accepted_as_a_short_answer() -> None:
    with pytest.raises(Refused, match="nothing"):
        check("   \n  ", LUCRA)


def test_a_faithful_restatement_passes() -> None:
    """The case that must not be refused, or the feature ships as an empty box.

    Every figure and date here is lifted from the payload, and the only verdict
    word is the row's own.
    """
    check(
        "The support for this year-end value is insufficient. The only document on file is a "
        "term sheet from 2024-05-20 offering Series A-1 at $2.00 per share, and a term sheet "
        "records what was proposed rather than what was paid. Nothing is requested here because "
        "the request for the signed agreement is filed under R1.",
        LUCRA,
    )


def test_the_guard_reads_figures_nested_anywhere_in_the_payload() -> None:
    """$2.00 lives three levels down, inside `evidence[0]`.

    A guard that only compared top-level values would refuse the correct
    sentence above — and the fix a hurried reader would reach for is to loosen
    the guard rather than to deepen it.
    """
    assert LUCRA["evidence"][0]["price_per_share"] == "2.00", "the fixture stopped holding it"
    assert "2.00" not in numerals(str(LUCRA["verdict"])), "a top-level-only guard would see nothing"
    check("The support is insufficient: the term sheet offers $2.00 per share.", LUCRA)
    with pytest.raises(Refused):
        check("The support is insufficient: the term sheet offers $2.01 per share.", LUCRA)


def test_a_refusal_is_an_outcome_rather_than_an_exception_at_the_route() -> None:
    """`accept()` never raises: the pane renders the structured row regardless.

    The asymmetry is the point. A refused restatement costs the reader a
    paragraph they never saw; a raised exception costs them the page.
    """
    refused = accept(
        "The support is insufficient and the shares are worth $9.99.", LUCRA, model="m"
    )
    assert refused.accepted is False
    assert refused.text is None
    assert "9.99" in (refused.refusal or "")

    ok = accept("  The support is insufficient.  ", LUCRA, model="m")
    assert ok.accepted is True
    assert ok.text == "The support is insufficient."
    assert ok.refusal is None


@pytest.mark.parametrize(
    ("text", "bypass"),
    [
        ("Sufficient support exists for the year-end mark.", "capitalised"),
        ("This requirement is not applicable to the position.", "the two-word English form"),
        ("The record partially supports the mark.", "a derived form"),
        ("Two partials never compose to sufficiency here.", "a noun form"),
    ],
)
def test_the_verdict_guard_is_not_walked_through_by_case_or_word_form(
    text: str, bypass: str
) -> None:
    """Four ways an adversarial pass got a foreign verdict past the first version.

    It matched the enum value literally and case-sensitively, so "Sufficient" at
    the start of a sentence, "not applicable" with a space where the enum has an
    underscore, and every derived form walked straight through — each of them a
    finding inverted in the reader's own language while the row said the
    opposite.
    """
    with pytest.raises(Refused):
        check(text, LUCRA)


def test_every_verdict_the_enum_defines_can_be_checked_without_crashing() -> None:
    """A guard that raises on an unfamiliar value is a guard that stops running.

    `conflicting` had no entry in the forms table when the table was introduced,
    which would have been a KeyError inside `check` — turning the safety
    mechanism into the outage.
    """
    for verdict in RequirementVerdict:
        #: `Refused`, not `KeyError`. The restatement must NAME the row's
        #: finding, so a sentence naming none is now correctly rejected — the
        #: point of this test is that every enum value reaches a decision
        #: rather than crashing the guard on its way there.
        with pytest.raises(Refused):
            check("A sentence naming no verdict at all.", {"verdict": verdict.value})
