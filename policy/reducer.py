"""Combining evidence — SPEC §7.4 for links, §6.2.1 for the row.

r1 scored one source tuple but permitted many links per assessment and gave no
rule for combining them, so two engineers would produce different requirement
states from identical evidence. Both reducers live here, once, because three
representations of one rule is what caused two failed fixer cycles.

The severity order is `missing < insufficient < partial < sufficient`, and it is
a *local* ordering used only for reduction. It is deliberately not exposed on
`RequirementVerdict` itself: the enum is a `StrEnum` precisely so that no
comparison with `>` is possible anywhere else in the codebase (INV-2). A verdict
is a finding, not a score; the only place ranking is legitimate is here, where
the spec defines what "weakest" means.

`conflicting` is **not on that scale**. It dominates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from packages.contracts.enums import RequirementVerdict

#: Weakest first. `not_assessed` and `not_applicable` are absent on purpose —
#: they are outside the order and never reduce (§6.2.1). Asking for the rank of
#: either raises rather than returning a default position, which is how
#: `not_applicable` would otherwise sort as "worse than missing" and drag a whole
#: row down to it.
SEVERITY: tuple[RequirementVerdict, ...] = (
    RequirementVerdict.MISSING,
    RequirementVerdict.INSUFFICIENT,
    RequirementVerdict.PARTIAL,
    RequirementVerdict.SUFFICIENT,
)


class ReducerError(Exception):
    """A verdict was offered to the reducer that the spec says never reduces."""


def _rank(verdict: RequirementVerdict) -> int:
    try:
        return SEVERITY.index(verdict)
    except ValueError:
        raise ReducerError(
            f"{verdict.value!r} is outside the severity order and never reduces "
            f"(SPEC §6.2.1). Filter it out before reducing, or handle it as the "
            f"distinct state it is."
        ) from None


def worst(verdicts: Iterable[RequirementVerdict]) -> RequirementVerdict:
    """The weakest of several verdicts. Used across lots and across requirements."""
    ranked = sorted(verdicts, key=_rank)
    if not ranked:
        raise ReducerError("worst() of nothing has no answer; decide the empty case at the caller")
    return ranked[0]


def best(verdicts: Iterable[RequirementVerdict]) -> RequirementVerdict:
    """The strongest of several verdicts — §7.4 rule 2, across evidence links.

    This is also §7.4 rule 3, "two `partial` results never compose to
    `sufficient`", and it holds by construction: the strongest of two partials
    is a partial. The rule is stated separately in the spec because the
    tempting implementation is additive — count the partials, promote at two —
    and that is the arithmetic this function exists to not be.
    `tests/test_policy_reducer.py` asserts it directly, so a future rewrite that
    reintroduces composition goes red rather than reading as an optimisation.
    """
    ranked = sorted(verdicts, key=_rank)
    if not ranked:
        raise ReducerError("best() of nothing has no answer; decide the empty case at the caller")
    return ranked[-1]


def reduce_links(
    verdicts: Sequence[RequirementVerdict], *, contradicted: bool = False
) -> RequirementVerdict:
    """One requirement verdict from many evidence links. SPEC §7.4.

    Ordered, and the order is the rule:

    1. A material contradiction between claims yields `conflicting` regardless
       of everything else, and stays there until a recorded human resolution
       supersedes a specific claim. `contradicted` is that determination, made
       by the caller against the claims themselves — it is not something a
       verdict list can express, which is why it is a separate argument rather
       than a `conflicting` entry in `verdicts`.
    2. Otherwise the strongest verdict among the links, supersession having
       already removed the claims a later one replaced.
    3. Two `partial` never compose to `sufficient` — see `best`.
    """
    if contradicted:
        return RequirementVerdict.CONFLICTING
    if not verdicts:
        raise ReducerError(
            "reduce_links() of no links has no answer. A requirement with no evidence "
            "resolves through the gap rule, which is a different question."
        )
    return best(verdicts)


def reduce_row(verdicts: Iterable[RequirementVerdict]) -> RequirementVerdict:
    """One row verdict from its five requirement verdicts. SPEC §6.2.1.

    `conflicting` if any applicable requirement is conflicting; otherwise the
    weakest applicable verdict. `not_applicable` and `not_assessed` are dropped
    first — a row is not dragged down by a requirement that does not arise, and
    a row whose every requirement is inapplicable is `not_applicable` rather
    than an invented `missing`.

    A row where *nothing* applies cannot occur for a real position (R1 and R2
    always apply, §7.1) but is answered rather than crashed, because the
    reducer is also reachable from the anchors' injected cases.
    """
    seen = list(verdicts)
    if RequirementVerdict.CONFLICTING in seen:
        return RequirementVerdict.CONFLICTING
    applicable = [
        v
        for v in seen
        if v not in (RequirementVerdict.NOT_APPLICABLE, RequirementVerdict.NOT_ASSESSED)
    ]
    if not applicable:
        return RequirementVerdict.NOT_APPLICABLE
    return worst(applicable)
