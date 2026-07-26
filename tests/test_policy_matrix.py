"""The matrix and the reducer, as rules — SPEC §7.3 and §7.4.

`test_policy_vs_oracle.py` proves the whole layer against the answer key on this
corpus. These prove the two rules the corpus cannot exercise: an unenumerated
tuple, and a contradiction. No document in the corpus contradicts another, so
`conflicting` is unreachable from the data — and a branch no test can reach is
the failure this project exists to avoid.
"""

from __future__ import annotations

from itertools import product

import pytest
import yaml

from packages.contracts.enums import (
    ExecutionStatus,
    GapKind,
    PositionType,
    RequirementCode,
    RequirementVerdict,
    SourceClass,
)
from policy.reducer import ReducerError, best, reduce_links, reduce_row, worst
from policy.valid_tuples import (
    GAP_VERDICTS,
    MATRIX,
    VALID_TUPLES,
    InvalidPolicyInput,
    lookup,
)
from tests.test_policy_vs_oracle import ROOT

PRIMITIVES = yaml.safe_load((ROOT / "evals/oracle/primitives.yaml").read_text())

SUFFICIENT = RequirementVerdict.SUFFICIENT
PARTIAL = RequirementVerdict.PARTIAL
INSUFFICIENT = RequirementVerdict.INSUFFICIENT
MISSING = RequirementVerdict.MISSING
CONFLICTING = RequirementVerdict.CONFLICTING
NOT_APPLICABLE = RequirementVerdict.NOT_APPLICABLE
NOT_ASSESSED = RequirementVerdict.NOT_ASSESSED


def test_the_matrix_is_cell_for_cell_the_oracles() -> None:
    """Two independent enumerations of one policy, compared as data.

    In BOTH directions. A cell the oracle has and the product does not makes the
    product refuse a document the corpus contains; a cell the product has and
    the oracle does not is a verdict nobody reviewed, which is the more
    dangerous direction because it fails open.
    """
    theirs = {
        (row["req"], row["source_class"], row["execution_status"], row["position_type"]): row[
            "verdict"
        ]
        for row in PRIMITIVES["policy_matrix"]
    }
    mine = {
        (req.value, source.value, execution.value, position.value): result.verdict.value
        for (req, source, execution, position), result in MATRIX.items()
    }
    assert mine == theirs


def test_the_gap_verdicts_are_cell_for_cell_the_oracles() -> None:
    """INV-12 · why a document is absent decides what the auditor does next."""
    theirs = {
        kind: (row["verdict"], row["next_action"])
        for kind, row in PRIMITIVES["gap_verdicts"].items()
    }
    mine = {
        (kind.value if kind else "none"): (
            result.verdict.value,
            result.next_actions[0],
        )
        for kind, result in GAP_VERDICTS.items()
    }
    assert mine == theirs


def test_every_enumerated_tuple_resolves_and_nothing_else_does() -> None:
    """The valid set is exactly `VALID_TUPLES`, derived from the production enums.

    Enumerated from the enums rather than from a hand-written list, and never as
    the raw Cartesian product — 5 × 9 × 5 × 4 is 900 combinations of which 14 are
    decided, and asserting over all 900 would be asserting mostly that the
    product refuses things nobody has thought about.
    """
    resolved = 0
    refused = 0
    for req, source, execution, position in product(
        RequirementCode, SourceClass, ExecutionStatus, PositionType
    ):
        key = (req, source, execution, position)
        if key in VALID_TUPLES:
            assert lookup(*key).verdict in tuple(RequirementVerdict)
            resolved += 1
        else:
            with pytest.raises(InvalidPolicyInput):
                lookup(*key)
            refused += 1
    assert resolved == len(MATRIX)
    assert resolved + refused == 5 * 9 * 5 * 4


def test_an_unenumerated_tuple_names_itself_and_says_what_to_do() -> None:
    """A refusal nobody can act on gets worked around rather than resolved."""
    with pytest.raises(InvalidPolicyInput) as raised:
        lookup(
            RequirementCode.R2,
            SourceClass.RUMOR,
            ExecutionStatus.NOT_APPLICABLE,
            PositionType.DIRECT_EQUITY,
        )
    message = str(raised.value)
    assert "rumor" in message
    assert "R2" in message
    assert "valid_tuples" in message


def test_a_verdict_short_of_sufficient_always_carries_a_reason() -> None:
    """A `partial` with no reason code is an assertion the auditor cannot act on."""
    for key, result in MATRIX.items():
        if result.verdict is not SUFFICIENT:
            assert result.reason_code, f"{key} is {result.verdict.value} with no reason"


# ── §7.4 · the multi-link reducer ────────────────────────────────────────


def test_two_partials_never_compose_to_sufficient() -> None:
    """SPEC §7.4 rule 3, stated separately because the tempting rule is additive.

    Dream is the live case: a pro forma cap table and an unexecuted closing
    notice, each `partial`. Counting them and promoting at two would report the
    Series B mark as fully supported on evidence that includes no executed
    document at all.
    """
    assert reduce_links([PARTIAL, PARTIAL]) is PARTIAL
    assert reduce_links([PARTIAL, PARTIAL, PARTIAL]) is PARTIAL
    assert best([PARTIAL, PARTIAL]) is PARTIAL


def test_the_strongest_link_wins_when_nothing_contradicts() -> None:
    assert reduce_links([INSUFFICIENT, SUFFICIENT]) is SUFFICIENT
    assert reduce_links([MISSING, PARTIAL, INSUFFICIENT]) is PARTIAL


def test_a_contradiction_dominates_every_other_link() -> None:
    """`conflicting` is not on the severity scale — it outranks it.

    Including a `sufficient` link. Two claims pricing one class differently do
    not become reliable because one of them came from an executed document.
    """
    assert reduce_links([SUFFICIENT, SUFFICIENT], contradicted=True) is CONFLICTING
    assert reduce_links([MISSING], contradicted=True) is CONFLICTING


def test_reducing_no_links_at_all_refuses_rather_than_guessing() -> None:
    """A requirement with no evidence resolves through the gap rule instead.

    Returning `missing` here would make the two paths indistinguishable, and the
    gap rule is where the auditor's next action is decided.
    """
    with pytest.raises(ReducerError):
        reduce_links([])


# ── §6.2.1 · the row reducer ─────────────────────────────────────────────


def test_the_row_takes_its_weakest_applicable_requirement() -> None:
    assert reduce_row([SUFFICIENT, PARTIAL, NOT_APPLICABLE]) is PARTIAL
    assert reduce_row([SUFFICIENT, SUFFICIENT]) is SUFFICIENT


def test_one_conflicting_requirement_makes_the_row_conflicting() -> None:
    assert reduce_row([SUFFICIENT, CONFLICTING, SUFFICIENT]) is CONFLICTING


def test_inapplicable_and_unassessed_requirements_never_drag_a_row_down() -> None:
    """INV-2 · `not_applicable` is not the weakest verdict; it is off the scale.

    A row whose R3, R4 and R5 do not arise is not therefore `missing`. Ordering
    `not_applicable` into the severity list is the cheapest way to make every
    clean row read as unsupported.
    """
    assert reduce_row([SUFFICIENT, NOT_APPLICABLE, NOT_ASSESSED]) is SUFFICIENT
    assert reduce_row([NOT_APPLICABLE, NOT_APPLICABLE]) is NOT_APPLICABLE


def test_the_severity_order_refuses_verdicts_that_never_reduce() -> None:
    """Asking for the rank of `not_applicable` raises rather than defaulting."""
    for verdict in (NOT_APPLICABLE, NOT_ASSESSED, CONFLICTING):
        with pytest.raises(ReducerError):
            worst([SUFFICIENT, verdict])


def test_every_gap_kind_the_contract_names_has_a_verdict() -> None:
    """A new `GapKind` must be decided, not defaulted."""
    assert set(GAP_VERDICTS) == set(GapKind) | {None}
