"""What a finding is, and how a label becomes a key.

The shared floor under `reconcile.py` and `marks.py`. It holds the closed
vocabulary of finding kinds, the record that carries one, the materiality rule,
and the two normalisations every check joins on — fund label to fund key, period
label to measurement date.

It exists as its own module so the two check modules can share a vocabulary
without importing each other. Nothing here reads a workbook or decides anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

#: A gap this small is rounding, not a finding. Two thresholds, and the SMALLER
#: one governs: a purely relative test scales with the position, so 0.1% of a
#: 60,000,000 mark silently swallowed a 40,000 gap — a number an auditor chases
#: on a named holding. The absolute floor stops the relative test growing
#: without limit; the relative test stops the absolute one drowning small
#: positions in cents. Named rather than inlined so both are reviewable.
_MATERIALITY_RELATIVE = Decimal("0.001")
_MATERIALITY_ABSOLUTE = Decimal("1000")


def _is_material(gap: Decimal, reference: Decimal) -> bool:
    """Is `gap` worth reporting against a figure of size `reference`?"""
    if gap == 0:
        return False
    threshold = min(abs(reference) * _MATERIALITY_RELATIVE, _MATERIALITY_ABSOLUTE)
    return abs(gap) >= threshold


class FindingKind(StrEnum):
    STATED_TOTAL_DISAGREES_WITH_CELLS = "stated_total_disagrees_with_cells"
    COST_TOTAL_DISAGREES_WITH_CELLS = "cost_total_disagrees_with_cells"
    TRANCHE_ARITHMETIC_DISAGREES = "tranche_arithmetic_disagrees"
    COST_BASIS_DISAGREES_ACROSS_WORKBOOKS = "cost_basis_disagrees_across_workbooks"
    UNRECOGNISED_TRANCHE_KIND = "unrecognised_tranche_kind"
    COST_BASIS_NEVER_COMPARED = "cost_basis_never_compared"
    NO_STATED_TOTAL_TO_CHECK = "no_stated_total_to_check"
    # A PURCHASE is not a ROUND. The fund's own last purchase price is evidence
    # about value; it is not proof that a round happened at that price, and the
    # kinds below say only what the workbooks actually support. The former
    # `mark_diverges_from_later_round` was removed rather than renamed: it was
    # never constructed anywhere, and a test asserted its absence — an assertion
    # that could not fail, in the test named for the anachronism guard.
    LATEST_PURCHASE_IS_AMBIGUOUS = "latest_purchase_is_ambiguous"
    PURCHASE_DATE_UNREADABLE = "purchase_date_unreadable"
    HOLDING_AT_DATE_UNDECIDABLE = "holding_at_date_undecidable"
    REALISATION_NOT_ALLOCATED_TO_LOTS = "realisation_not_allocated_to_lots"
    MARK_NEVER_COMPARED = "mark_never_compared"
    MARK_BASIS_NOT_IN_WORKBOOKS = "mark_basis_not_in_workbooks"
    # Distinguished from the above because the two ask the investors for
    # DIFFERENT things. "Not in the workbooks" means nothing here explains the
    # figure — send the valuation memo. "Only under an assumption" means the
    # arithmetic does work, but only by doing something no row states — confirm
    # that treatment. Reported as one kind, an auditor cannot tell which letter
    # to write.
    MARK_BASIS_ASSUMES_AN_UNSTATED_TREATMENT = "mark_basis_assumes_an_unstated_treatment"
    UNRECOGNISED_PERIOD_LABEL = "unrecognised_period_label"
    MARK_AT_COST_DISAGREES_WITH_PURCHASE_PRICES = "mark_at_cost_disagrees_with_purchase_prices"


#: SPEC §2, the closed packet date set: Fund II at the three measurement dates
#: the audit letter names, and Fund I at the same year ends. **Exactly these
#: six.** Fund I FY2021-FY2022 and Fund II 24Q2/25Q2/25Q3/26Q1 are ingested and
#: appear in the ledger, and are excluded from packet generation (INV-20).
#:
#: The reconciler read all twelve and marked none of them, so a finding about a
#: quarter the auditor never asked about was indistinguishable from one about a
#: measurement date. The database enforces this distinction on
#: `reporting_period.audit_scope`; enforcing it there and not here is the
#: one-side-only defect this project keeps producing.
PACKET_PERIODS: dict[str, frozenset[str]] = {
    "Fund II": frozenset({"23Q4", "24Q4", "25Q4"}),
    "Fund I": frozenset({"FY2023", "FY2024", "FY2025"}),
}


def _period_scope(fund: str | None, label: str) -> str:
    """`packet` when the auditor asked about this date, else `lineage_only`."""
    known = PACKET_PERIODS.get(fund or "")
    if known is None:
        return "lineage_only"
    return "packet" if label in known else "lineage_only"


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    subject: str
    detail: str
    stated: Decimal | None = None
    computed: Decimal | None = None
    #: `packet`, `lineage_only`, or None where no single period applies.
    scope: str | None = None

    @property
    def difference(self) -> Decimal | None:
        if self.stated is None or self.computed is None:
            return None
        return self.computed - self.stated


#: `Fund II Holdings by Quarter` and `Fund II` are one fund; `Fund III` is not.
#: The numeral must end at a word boundary. Matching by prefix collapsed every
#: fund numbered above II onto a lower one — `Fund III` onto `Fund II`, `Fund IV`
#: onto `Fund I` — which silently compared two funds' costs as if they were one.
_FUND_LABEL = re.compile(r"Fund\s+([IVXLCDM]+|\d+)(?![\w'])", re.IGNORECASE)

#: Two funds in one label, whether or not the word `Fund` is repeated.
#: `Fund I / Fund II Combined` and `Fund I & II Combined` are the same claim, and
#: counting occurrences of the full pattern saw only the first of the second one.
_MULTI_FUND = re.compile(
    r"Fund\s+(?:[IVXLCDM]+|\d+)(?![\w'])\s*(?:[/&,]|\band\b)\s*(?:Fund\s+)?(?:[IVXLCDM]+|\d+)"
    r"(?![\w'])",
    re.IGNORECASE,
)


def _fund_of(label: str | None) -> str | None:
    """Normalise `Fund II Holdings by Quarter` and `Fund II` to one key.

    A label naming more than one fund is not normalised to the first one. `Fund
    I / Fund II Combined` is not Fund I, and answering as though it were joins a
    combined figure against one fund's tranches and reports the difference as a
    discrepancy. It returns the raw label instead, which joins with nothing and
    surfaces as never-compared — loud, and true.
    """
    if not label:
        return None
    text = label.strip()
    if _MULTI_FUND.search(text):
        return text
    match = _FUND_LABEL.match(text)
    if match:
        return f"Fund {match.group(1).upper()}"
    return text


def _period_end(label: str) -> date | None:
    """The last day of a tracker period label — `25Q4`, `FY2024`.

    Returned rather than assumed so a label this reader does not understand
    disables the anachronism guard loudly (None) instead of quietly comparing
    against the wrong date.
    """
    text = label.strip().upper()
    if text.startswith("FY") and text[2:].isdigit():
        return date(int(text[2:]), 12, 31)
    # The quarter digit must be a real quarter. `25Q5` used to parse as a fifth
    # quarter ending 2026-03-31 and `25Q0` as one ending 2024-12-31, so a typo
    # in a header silently moved the measurement date across a year boundary and
    # compared a mark against purchases from the wrong year.
    if len(text) == 4 and text[2] == "Q" and text[:2].isdigit() and text[3] in "1234":
        year = 2000 + int(text[:2])
        month = int(text[3]) * 3
        return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return None
