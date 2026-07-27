"""The acceptance report's own guards, proved by breaking what each one watches.

`scripts/acceptance.py` exists because nothing measured this system against the
client's letter, and ¶1's third limb — "and settlement of funds" — went
unanswered until two reviewers found it from opposite directions. A report that
would not have caught that is worse than no report, because it would have said
the letter was answered.

So the first test here is that exact regression, run against the vocabulary the
ledger had before the settlement claims were bound. The rest defend the two
things that could quietly stop the report from checking anything: a quotation
that no longer appears in the letter, and a limb that asks for nothing.

No database. Every fixture below is a hand-built `Evidence`, because what is
under test is the report's reasoning rather than the corpus it reads.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Through `importlib` for the same reason `tests/test_gate_guards.py` does it:
# the path insert has to run first, and a module-level import after a statement
# is E402. The gate holds inline suppressions at zero.
acceptance = importlib.import_module("acceptance")

LIMBS = {limb.key: limb for limb in acceptance.LIMBS}

#: The letter's own words, as `scripts/acceptance.py` quotes them, so a test
#: that does not need the private PDF still checks against real sentences.
LETTER_ENOUGH = (
    "1. Existence and cost. Executed transaction documents supporting the Fund's "
    "acquisition of each position, including share counts, price per share, and "
    "settlement of funds."
)


def evidence(**vocabulary: frozenset[str]) -> object:
    """An `Evidence` carrying only the vocabularies a test is about."""
    ev = acceptance.Evidence()
    for name, value in vocabulary.items():
        setattr(ev, name, value)
    return ev


# ── the regression this file exists for ──────────────────────────────────
def test_the_settlement_limb_is_unanswerable_before_the_ledger_can_record_it() -> None:
    """¶1(d), against the field vocabulary as it stood when the limb went missing.

    Nothing wrote `settlement_amount_received`, so no position could answer
    "settlement of funds" and none ever would have — and R1 still read
    `sufficient`, because the document was there and the clause was not
    represented by anything that could be absent.

    A limb the ledger has no vocabulary for is the one state this report exits
    non-zero on, and this is why.
    """
    before = evidence(
        known_fields=frozenset({"fund_shares", "fund_price_per_share", "agreement_date"}),
        known_classes=frozenset({"executed_transaction_doc"}),
        known_decisions=frozenset({"valuation"}),
    )
    missing = acceptance.unspeakable(LIMBS["1d"], before)
    assert missing == ["settlement_amount_received", "settlement_date", "settlement_reference"], (
        "the settlement limb read as answerable against a ledger that could not record it"
    )


def test_the_settlement_limb_is_answerable_once_the_ledger_records_it() -> None:
    """The control. Without it the assertion above is satisfied by a check that
    calls every limb unanswerable, which is the other way to stop measuring."""
    after = evidence(
        known_fields=frozenset(LIMBS["1d"].fields),
        known_classes=frozenset(),
        known_decisions=frozenset(),
    )
    assert acceptance.unspeakable(LIMBS["1d"], after) == []


def test_a_management_assessment_is_a_decision_the_ledger_can_already_record() -> None:
    """¶3(b) is NOT a system gap, and the first version of this report said it was.

    A management assessment is not a source document — nobody sends it to the
    fund. It is a `review_decision` of type `management_assessment` bound to the
    mark it concerns, the schema has carried that since 0001, and the corpus
    holds none. "The fund has not written one" and "there is nowhere to put one"
    are different answers to the client, and only the second is ours to fix.
    """
    ledger_as_it_is = evidence(
        known_classes=frozenset({"executed_transaction_doc", "third_party_valuation_memo"}),
        known_fields=frozenset(),
        known_decisions=frozenset(
            {"transcription", "valuation", "management_assessment", "packet"}
        ),
    )
    for key in ("2d", "3b", "6"):
        assert acceptance.unspeakable(LIMBS[key], ledger_as_it_is) == [], (
            f"limb {key} reported as unrecordable; the ledger records it as a decision"
        )


# ── a quotation that drifted is not a quotation ──────────────────────────
def test_a_fragment_that_no_longer_appears_in_the_letter_refuses_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limb still checked, still printed, and no longer describing anything the
    client wrote. `ingest/policy_seed.py` refuses on the same condition."""
    drifted = acceptance.Limb(
        "1d",
        "settlement of funds",
        "and settlement of monies",
        acceptance.BY_POSITION,
        fields=frozenset({"settlement_date"}),
    )
    monkeypatch.setattr(acceptance, "LIMBS", (drifted,))
    with pytest.raises(acceptance.AcceptanceError, match="no longer resolve"):
        acceptance.resolve_fragments(LETTER_ENOUGH)


def test_a_fragment_matching_more_than_once_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguity is the other failure. A fragment matching two sentences pins
    neither, and the limb would survive the deletion of the one it meant."""
    ambiguous = acceptance.Limb(
        "1x", "cost", "cost", acceptance.BY_POSITION, fields=frozenset({"settlement_date"})
    )
    monkeypatch.setattr(acceptance, "LIMBS", (ambiguous,))
    with pytest.raises(acceptance.AcceptanceError, match="no longer resolve"):
        acceptance.resolve_fragments(LETTER_ENOUGH + " The cost is the cost.")


def test_the_letters_own_wrapping_does_not_drop_a_limb(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pdftotext` wraps the letter at the page width, so the clause this report
    was built for is split across two lines in the file. Compared as written it
    matches nothing, and every limb would refuse for a reason that is about
    typography."""
    monkeypatch.setattr(acceptance, "LIMBS", (LIMBS["1c"], LIMBS["1d"]))
    acceptance.resolve_fragments(
        "including share counts, price\nper share, and settlement of funds."
    )


# ── a limb that asks for nothing is answered by everything ───────────────
def test_a_limb_declaring_no_evidence_at_all_is_refused_at_construction() -> None:
    with pytest.raises(acceptance.AcceptanceError, match="declares no evidence"):
        acceptance.Limb("zz", "asks for nothing", "Existence and cost", acceptance.BY_POSITION)


def test_every_declared_limb_asks_for_something() -> None:
    """The real map, not a fixture. `__post_init__` enforces it at import, so
    this is the assertion that the enforcement is still wired to the real
    limbs rather than only to the ones a test builds."""
    assert acceptance.LIMBS
    for limb in acceptance.LIMBS:
        assert limb.classes or limb.fields or limb.decisions, limb.key


# ── the dimensions are a conjunction ─────────────────────────────────────
def test_a_pro_forma_table_without_a_price_per_share_does_not_answer_2b() -> None:
    """¶2 conditions the disjunct on "evidencing price per share", so the
    qualifier is load-bearing: the class alone is not the limb."""
    limb = LIMBS["2b"]
    ev = acceptance.Evidence()
    ev.classes_by_date[("h", "2025-12-31")] = set(limb.classes)
    assert not acceptance.answered(limb, ev, "h", "2025-12-31")
    ev.fields_by_date[("h", "2025-12-31")] = {next(iter(limb.fields))}
    assert acceptance.answered(limb, ev, "h", "2025-12-31")


def test_a_price_per_share_from_the_wrong_kind_of_document_does_not_answer_2b() -> None:
    """The other half of the conjunction, and the reason this is not a field
    check: a term sheet states a price per share and is not a cap table."""
    limb = LIMBS["2b"]
    ev = acceptance.Evidence()
    ev.classes_by_date[("h", "2025-12-31")] = {"company_communication"}
    ev.fields_by_date[("h", "2025-12-31")] = set(limb.fields)
    assert not acceptance.answered(limb, ev, "h", "2025-12-31")


# ── against the real letter, when it is here ─────────────────────────────
@pytest.mark.skipif(
    not acceptance.LETTER.exists(),
    reason="case-study document is not in the repository",
)
def test_every_fragment_resolves_against_the_letter_itself() -> None:
    """The whole map against the client's actual file. Everything above tests
    the machinery; this tests that the machinery is pointed at the letter."""
    acceptance.resolve_fragments(acceptance.letter_text())
