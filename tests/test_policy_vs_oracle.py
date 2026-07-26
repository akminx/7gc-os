"""G2 and G7: the policy layer against the answer key, field by field.

**Verdicts are oracle-owned.** Every assertion here compares `policy/` against
`evals/oracle/derived.json`, read as JSON. Nothing in `policy/` imports
`evals/`, and `test_the_product_does_not_import_its_own_answer_key` says so, so
the two are independent derivations of one corpus rather than one derivation
checked against itself.

The comparison is the full cross-product — 35 rows × 5 requirements — with the
count asserted, so a row that quietly stops being compared fails rather than
reading clean. It covers every field the oracle publishes: verdict, reason
codes, next actions, the claims relied upon, per-lot detail, `cross_class`,
`pro_forma`, `subsequent_evidence`, R3's stale components and unchanged-since
date, R4's realised lots, and the reduced row verdict.
"""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path
from typing import Any

from packages.contracts.enums import RequirementCode
from policy.inputs import Ledger
from policy.requirements import RowAssessment, assess_row
from tests.oracle_map import CLAIM, HOLDING, LOT

ROOT = Path(__file__).resolve().parents[1]
DERIVED: dict[str, Any] = json.loads((ROOT / "evals/oracle/derived.json").read_text())

#: 35 rows, and every one carries all five requirements. Asserted rather than
#: counted at runtime: a comparison whose denominator comes from the data cannot
#: report that the data shrank.
EXPECTED_COMPARISONS = 175


def compare_row(ledger: Ledger, row: dict[str, Any]) -> tuple[list[str], int]:
    """Every published field of one oracle row against the policy layer."""
    holding, on = HOLDING[row["holding"]], date.fromisoformat(row["date"])
    got = assess_row(ledger, holding, on)
    where = f"{row['holding']}@{row['date']}"
    problems: list[str] = []

    if got.verdict.value != row["row_verdict"]:
        problems.append(f"{where} row verdict {got.verdict.value} != {row['row_verdict']}")

    checked = 0
    for code, want in row["requirements"].items():
        checked += 1
        problems += _compare_requirement(got, RequirementCode(code), want, where)
    return problems, checked


def _compare_requirement(
    got: RowAssessment, code: RequirementCode, want: dict[str, Any], where: str
) -> list[str]:
    outcome = got.outcomes[code]
    bad: list[str] = []

    def differs(label: str, mine: object, theirs: object) -> None:
        if mine != theirs:
            bad.append(f"{where} {code.value} {label}: {mine!r} != {theirs!r}")

    differs("verdict", outcome.verdict.value, want["verdict"])
    if "reasons" in want:
        differs("reasons", list(outcome.reasons), want["reasons"])
    if "next_actions" in want:
        differs("next_actions", list(outcome.next_actions), want["next_actions"])
    if "relied_on" in want:
        differs("relied_on", list(outcome.relied_on), [CLAIM[x] for x in want["relied_on"]])
    if "per_lot" in want:
        differs(
            "per_lot",
            {k: v.value for k, v in outcome.per_lot.items()},
            {LOT[k]: v for k, v in want["per_lot"].items()},
        )
    for flag in ("cross_class", "pro_forma", "subsequent_evidence"):
        if flag in want:
            differs(flag, getattr(outcome, flag), want[flag])
    if "stale_components" in want:
        differs(
            "stale_components",
            [
                {"component": s.component, "latest": s.latest.isoformat() if s.latest else None}
                for s in outcome.stale_components
            ],
            want["stale_components"],
        )
    if "unchanged_since" in want:
        differs(
            "unchanged_since",
            outcome.unchanged_since.isoformat() if outcome.unchanged_since else None,
            want["unchanged_since"],
        )
    for key in ("reason", "note"):
        if key in want:
            differs("note", outcome.note, want[key])
    if "events" in want:
        differs("events", list(outcome.realized_lots), [LOT[x] for x in want["events"]])
    return bad


def assert_reproduces(ledger: Ledger, source: str) -> None:
    problems: list[str] = []
    checked = 0
    for row in DERIVED["rows"]:
        found, n = compare_row(ledger, row)
        problems += found
        checked += n
    assert checked == EXPECTED_COMPARISONS, (
        f"compared {checked} requirements, expected {EXPECTED_COMPARISONS}. The oracle's "
        f"row set changed, so this gate now covers less than it reports."
    )
    assert not problems, f"{len(problems)} disagreement(s) with the oracle, from {source}:\n" + (
        "\n".join(problems[:25])
    )


def test_the_policy_layer_reproduces_the_oracle_from_the_ledger(policy_ledger: Ledger) -> None:
    """The gate that matters: verdicts derived from what the DATABASE holds.

    The other direction — running the rules over the oracle's own primitives —
    proves the rules. This proves the ledger actually carries what the rules
    need, which is a different claim and the one that failed first: every
    holding was `direct_equity` and every lot's security class was `unstated`,
    so three positions could not be looked up in the matrix at all and the rest
    read as cross-class.
    """
    assert_reproduces(policy_ledger, "the ledger")


def test_r3_fires_for_exactly_the_twelve_holding_dates_the_oracle_names(
    policy_ledger: Ledger,
) -> None:
    """SPEC §7.2 · calibration, the requirement defined wrong four times.

    Asserted as a SET rather than a count. A count passes when R3 fires twelve
    times for the wrong twelve positions, which is exactly what each of the four
    wrong definitions did — limb (a) reading "audit measurement date" let
    Roofstock escape at FY2023 while something else fired instead.
    """
    fired = {(HOLDING[x["holding"]], x["date"]) for x in DERIVED["r3_applicable"]}
    mine = set()
    for row in DERIVED["rows"]:
        holding, on = HOLDING[row["holding"]], date.fromisoformat(row["date"])
        outcome = assess_row(policy_ledger, holding, on).outcomes[RequirementCode.R3]
        if outcome.stale_components:
            mine.add((holding, row["date"]))
    assert mine == fired


def test_exactly_twelve_months_of_support_is_not_stale(policy_ledger: Ledger) -> None:
    """The boundary is strict, and it is one character.

    Capsule's FY2022 memo is dated 12/31/2022 and its FY2023 mark is unchanged.
    Read at 12/31/2023 the memo is exactly twelve months old, so R3 does NOT
    fire; read at 12/31/2024 it does. Both directions are asserted, because a
    `<=` passes the first alone and a rule that never fires passes the second.
    """
    capsule = HOLDING["capsule"]
    at_the_boundary = assess_row(policy_ledger, capsule, date(2023, 12, 31))
    past_it = assess_row(policy_ledger, capsule, date(2024, 12, 31))
    assert at_the_boundary.outcomes[RequirementCode.R3].stale_components == ()
    assert past_it.outcomes[RequirementCode.R3].stale_components != ()


def test_one_stale_component_is_enough_even_beside_a_fresh_one(policy_ledger: Ledger) -> None:
    """SPEC §7.2 limb (b) is **at least one**, not every.

    Moonfare's mark has two material components: the underlying EUR valuation
    (March 2023) and the FX rate (12/31/2024, exactly twelve months and
    therefore not stale). Under `every`, the fresh rate rescued the 33-month-old
    valuation and R3 did not fire at all.
    """
    outcome = assess_row(policy_ledger, HOLDING["moonfare"], date(2025, 12, 31)).outcomes[
        RequirementCode.R3
    ]
    stale = {s.component for s in outcome.stale_components}
    assert stale == {"underlying_valuation"}, "the FX rate is current and must not be listed"
    assert outcome.verdict.value == "missing"


def test_a_lineage_only_period_can_be_the_predecessor_observation(policy_ledger: Ledger) -> None:
    """Limb (a) is the immediately preceding MARK OBSERVATION, not packet date.

    Sway's 24Q4 predecessor is 24Q2, a lineage-only period. Reading only packet
    dates made R3 structurally unable to fire at a fund's first packet date.
    """
    outcome = assess_row(policy_ledger, HOLDING["sway"], date(2024, 12, 31)).outcomes[
        RequirementCode.R3
    ]
    assert outcome.unchanged_since == date(2024, 6, 30)


def test_the_product_does_not_import_its_own_answer_key() -> None:
    """G7, enforced rather than promised.

    Checked in the SYNTAX TREE, not by string search: the product discusses the
    oracle freely in comments — that is how a reader learns why a rule is what
    it is — and a grep for the word flags every one of those. What must never
    happen is an `import`, including a lazy one inside a function, which is
    exactly the form a string search over module-level lines would miss.
    """
    offenders = []
    for path in sorted(ROOT.glob("[apolicyngest]*/**/*.py")):
        if "__pycache__" in path.parts or path.parts[0] in {"tests", "evals", "scripts"}:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] == "evals":
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {name}")
    assert not offenders, "the product imports its own answer key:\n" + "\n".join(offenders)
