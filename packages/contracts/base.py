"""The two primitives every other contract is built from.

Split out of `models.py` at the file-size budget, not for tidiness: `Contract`
and `Money` have no dependencies of their own, so they are the one part of the
contract layer that can move without a cycle. Everything `models.py` exported
before, it still exports — the split is a fact about files, not about the
interface, and `from packages.contracts.models import Money` continues to work.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    """Frozen and strict: unknown fields are an error, not a silent drop.

    A tolerant parser is how a renamed field becomes a null downstream and then
    a zero in a total.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Any:
        """Re-validate when fields are replaced.

        Pydantic's `model_copy(update=...)` writes straight past every validator,
        so a guard that only runs at construction is not a guard at all: a float
        could be posted into `Money.amount`, and an `approved_fair_value` total
        could acquire unsupported positions, both bypassing the exact rules those
        models exist to enforce.
        """
        if not update:
            return super().model_copy(deep=deep)
        merged = {**{f: getattr(self, f) for f in type(self).model_fields}, **update}
        return type(self)(**merged)


#: Declared money scale, matching the `trunc(x, 4)` checks in the migration.
MONEY_SCALE = 4
#: Price per share is quoted to six places.
PPS_SCALE = 6


class Money(Contract):
    """An amount that knows its currency. INV-11.

    `Decimal` throughout — a float amount is wrong before anyone reads it.
    """

    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("amount", mode="before")
    @classmethod
    def _refuse_float(cls, v: object) -> object:
        """A float has already lost precision by the time it reaches here.

        `Money(amount=0.1 + 0.2)` coerces to Decimal('0.30000000000000004') and
        then freezes that binary residue as if it were exact money. Accepting
        the input silently is what makes INV-11's guard decorative — the type
        must refuse the one value that breaks it.
        """
        if isinstance(v, float):
            raise ValueError(
                f"money must not be constructed from a float ({v!r}); "
                "pass a Decimal or a string — the precision is already gone by here"
            )
        return v

    @model_validator(mode="after")
    def _amount_fits_its_declared_scale(self) -> Money:
        """Mirrors the database scale checks. INV-11.

        The database was taught to reject `1109.999889`; this model still built
        it happily, and `Packet.totals()` would have carried the residue into an
        auditor-facing figure without ever touching a column. An invariant
        enforced on one side only is not enforced — `Lot.shares` already mirrors
        its DB check, and money did not.
        """
        exponent = self.amount.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > MONEY_SCALE:
            raise ValueError(
                f"money carries more than {MONEY_SCALE} decimal places ({self.amount}); "
                "quantise deliberately before constructing it"
            )
        return self

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(
                f"refusing to add {self.currency} to {other.currency}: "
                "a cross-currency sum needs a rate observed at the measurement date"
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)
