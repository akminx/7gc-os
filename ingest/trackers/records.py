"""What a mapping produced, and what it could not.

Split out so `to_lots.py` and `to_contracts.py` share one definition rather
than importing each other. Neither list is decoration:
`tests/test_real_data_end_to_end.py` asserts their contents, so a change that
stops recording a substitution fails rather than reading clean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.contracts.enums import PositionType
from packages.contracts.models import Lot, LotConversion, Mark, Packet, Period


@dataclass(frozen=True)
class Substitution:
    """A value the contract required and the workbooks do not state."""

    subject: str
    field_path: str
    value: str
    because: str


@dataclass(frozen=True)
class Refusal:
    """Something the source states that the contract cannot hold."""

    subject: str
    field_path: str
    detail: str


@dataclass(frozen=True)
class Holding:
    """The identity row a packet row implies but does not carry.

    `HoldingRow` names a holding and a company and stops there; the fund, the
    currency and the company's own identity live only in the database. They are
    materialised here so the persistence step has something to write.
    """

    id: str
    fund_id: str
    company_id: str
    company_name: str
    position_type: PositionType
    currency: str


@dataclass(frozen=True)
class Mapped:
    """Everything the workbooks became, and everything they could not."""

    holdings: list[Holding] = field(default_factory=list)
    lots: list[Lot] = field(default_factory=list)
    conversions: list[LotConversion] = field(default_factory=list)
    periods: list[Period] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    packets: list[Packet] = field(default_factory=list)
    substitutions: list[Substitution] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)

    def packet(self, fund_id: str, label: str) -> Packet:
        """One fund-period, by the label the tracker itself prints."""
        return next(p for p in self.packets if p.fund_id == fund_id and p.period.label == label)

    def substituted(self, field_path: str) -> list[Substitution]:
        return [s for s in self.substitutions if s.field_path == field_path]

    def refused(self, field_path: str) -> list[Refusal]:
        return [r for r in self.refusals if r.field_path == field_path]
