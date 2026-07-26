"""What the workbooks say about *kind* — position type and security class.

Both were recorded as assumptions in Step 1 and both were wrong for it. Every
holding took `direct_equity` and every lot `security_class = 'unstated'`, which
was honest at the time — the alternative was inventing `series_a`, and that
would make INV-17's cross-class rule read as satisfied, which is the one failure
it exists to catch.

But the workbooks were not silent. They state these in prose lines the tranche
reader drops, because a documentation line carries no number in the
"Investment ($)" column and so is not a tranche. `read_master_notes` now returns
them, and this module decides what they mean — once, beside the evidence, so a
reviewer can read the rule and the source line together.

Two rules govern everything here:

* **Nothing is guessed.** Where no line states a class, the value stays
  `UNSTATED` and travels as a recorded substitution. Anthropic is the case: no
  line in either workbook, and no passage in the one document the fund holds,
  names the class of its position. The oracle asserts `preferred`; nothing in
  the corpus supports it.
* **Ambiguity raises.** Two lines claiming different position types for one
  company is a contradiction in the source, not something to resolve by
  ordering. It stops the load.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ingest.trackers.read import SheetNote, Tranche
from packages.contracts.enums import PositionType

#: `Lot.security_class` is required and non-null, so an unknown class needs a
#: value. A sentinel, never a plausible guess.
UNSTATED = "unstated"


class ClassificationError(Exception):
    """The source says two contradictory things, or says something unhandled."""


@dataclass(frozen=True)
class Reading:
    """A value the workbook states, and the line that states it."""

    value: str
    source_text: str
    source_sheet: str


#: Position type, as the workbook signals it. Each pattern is matched against
#: the tranche `Type` cells and the prose lines of one company sheet together,
#: because the signal sits in different columns for different positions: Jio's
#: is a `Type` cell reading "Indirect Fund", Banzai's is a "De-SPAC" row plus a
#: note about quoted prices, Moonfare's is a note about a EUR-denominated
#: interest and nothing in the grid at all.
_POSITION_SIGNALS: tuple[tuple[PositionType, re.Pattern[str]], ...] = (
    (PositionType.INDIRECT_FEEDER, re.compile(r"indirect (?:fund|exposure)|feeder", re.I)),
    (PositionType.PUBLIC_LISTED, re.compile(r"de-spac|public listing|quoted closing price", re.I)),
    (
        PositionType.FX_DENOMINATED_INTEREST,
        re.compile(r"\b(?!USD\b)[A-Z]{3}-denominated\b"),
    ),
)

#: A named security class inside a documentation line: "Series B-1", "Series C".
#: Anchored on the word so "Series B Purchasers" in a table heading and
#: "the Series A-2 tranche" both resolve, and a bare "B" never does.
_SERIES = re.compile(r"\bSeries\s+([A-Z](?:-\d+)?)\b")

#: Instruments named by the `Type` cell rather than by a series letter.
_INSTRUMENT_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("conv_note", re.compile(r"conv\.?\s*note|convertible note", re.I)),
    ("lp_interest", re.compile(r"indirect fund", re.I)),
)

#: An instrument a prose line names without a series letter.
_INSTRUMENT_NOTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("fund_interest", re.compile(r"\b[A-Z]{3}-denominated fund interest", re.I)),
    ("lp_interest", re.compile(r"capital account statement|feeder", re.I)),
)

#: What a listed position's quoted security IS. Applied only when the sheet has
#: already been read as `public_listed`: a de-SPACked position's marked security
#: is the listed common stock, which is what a ticker and a "quoted closing
#: price ... (Level 1)" line both name. Banzai's own pre-listing SPA line names
#: no class, so without this its class stays unstated and R2 reports an
#: uncovered security class against a quote that covers the whole position.
_LISTED_CLASS = "common"

#: A year, or a month and year, inside a documentation line. Used to bind a line
#: to the tranche it describes — see `security_class`.
_MONTH_YEAR = re.compile(
    r"(?:(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"|(\d{1,2}))[\s./]*(\d{4})",
    re.I,
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

#: Lines that describe the sheet rather than the position.
_CHROME = re.compile(r"^(supporting documentation|case study material)", re.I)


def _dated(text: str) -> tuple[int | None, int | None]:
    """`(year, month)` a documentation line names, month `None` if only a year."""
    found = _MONTH_YEAR.search(text)
    if found:
        name, number, year = found.groups()
        month = _MONTHS[name.lower()] if name else int(number)
        if 1 <= month <= 12:
            return int(year), month
    bare = _YEAR.search(text)
    return (int(bare.group(0)), None) if bare else (None, None)


def position_type(notes: list[SheetNote], tranches: list[Tranche]) -> Reading:
    """The position type this company's sheet states, or `direct_equity`.

    `direct_equity` is the *default* here and nowhere else, and that is
    deliberate rather than the fail-closed rule being relaxed: a direct equity
    position is what a venture fund holds unless the sheet says otherwise, and
    saying otherwise is exactly what these lines do. The fail-closed half is
    that two signals disagreeing raises instead of picking one.
    """
    lines = [(n.text, n.source_sheet) for n in notes]
    lines += [(t.kind, t.source_sheet or "") for t in tranches]

    hits: dict[PositionType, Reading] = {}
    for kind, pattern in _POSITION_SIGNALS:
        for text, sheet in lines:
            if pattern.search(text):
                hits.setdefault(kind, Reading(kind.value, text, sheet))
                break
    if len(hits) > 1:
        found = ", ".join(f"{k.value} from {v.source_text!r}" for k, v in hits.items())
        raise ClassificationError(
            f"the sheet signals more than one position type ({found}). A position is "
            f"one kind; two signals is a contradiction in the source, not a precedence "
            f"question."
        )
    if hits:
        return next(iter(hits.values()))
    return Reading(
        PositionType.DIRECT_EQUITY.value,
        "no line names a feeder, a listing or a foreign denomination",
        tranches[0].source_sheet or "" if tranches else "",
    )


def security_class(
    tranche: Tranche,
    notes: list[SheetNote],
    position: PositionType = PositionType.DIRECT_EQUITY,
    from_documents: dict[str, str] | None = None,
) -> Reading:
    """The security class this tranche's own supporting line names.

    A sheet carries several documentation lines and several tranches, so the two
    are bound by DATE: a line is about this tranche when it names the tranche's
    acquisition month and year, and failing that its year alone. Fluidstack is
    why the month matters — its 2025 lines are a Series B cap table (December)
    and a Series A-2 tranche (May), and the fund's second lot was acquired in
    May. Binding on year alone would make both candidates and the answer
    arbitrary.

    `from_documents` supplies classes the workbooks do not state but an executed
    transaction document does — Jackpocket's merger notice names "Series B
    Preferred Stock" as the security being cashed out. It is keyed by lot and
    supplied by the caller rather than read here, so this module stays a reader
    of the workbooks alone.

    Where nothing states it, `UNSTATED`. Dream and Anthropic end there: Dream's
    lines name Series B, which is the round the cap table PRICES and not the
    Series A-1 the fund HOLDS, and taking it would collapse INV-17 in the one
    position that exists to demonstrate it.
    """
    for value, pattern in _INSTRUMENT_KINDS:
        if pattern.search(tranche.kind):
            return Reading(value, tranche.kind, tranche.source_sheet or "")

    if from_documents and tranche.company in from_documents:
        return Reading(from_documents[tranche.company], "executed transaction document", "")

    acquired = tranche.acquired_range[0] if tranche.acquired_range else None
    candidates = [n for n in notes if not _CHROME.match(n.text)]

    dated = _class_named_on(candidates, acquired)
    if dated is not None:
        return dated

    for value, pattern in _INSTRUMENT_NOTES:
        for note in candidates:
            if pattern.search(note.text):
                return Reading(value, note.text, note.source_sheet)

    if position is PositionType.PUBLIC_LISTED:
        listing = next(
            (n for n in candidates if _POSITION_SIGNALS[1][1].search(n.text)),
            None,
        )
        return Reading(
            _LISTED_CLASS,
            listing.text if listing else "the sheet reads this position as publicly listed",
            listing.source_sheet if listing else "",
        )

    return Reading(UNSTATED, "no documentation line names this tranche's security class", "")


def _class_named_on(notes: list[SheetNote], when: date | None) -> Reading | None:
    """The security class a documentation line names for an event on `when`.

    Month and year first, then year alone. Fluidstack is why the month matters:
    its 2025 lines are a Series B cap table (December) and a Series A-2 tranche
    (May), and the fund's second lot was acquired in May — binding on year alone
    would make both candidates and the answer arbitrary.

    Two lines naming two classes at the same precision returns `None` rather
    than the first. Picking one would be a coin flip recorded as a fact.
    """
    if when is None:
        return None
    exact = [n for n in notes if _dated(n.text) == (when.year, when.month)]
    same_year = [n for n in notes if _dated(n.text)[0] == when.year]
    for pool in (exact, same_year):
        named = [(n, m) for n, m in ((n, _SERIES.search(n.text)) for n in pool) if m]
        if len(named) == 1:
            note, match = named[0]
            return Reading(_slug_class(match.group(1)), note.text, note.source_sheet)
        if len(named) > 1:
            return None
    return None


def _slug_class(series: str) -> str:
    """ "B-1" -> "series_b1", matching the class names the claims already use."""
    return "series_" + series.replace("-", "").lower()


@dataclass(frozen=True)
class Recapitalisation:
    """A security-class conversion the breakdown records as its own row.

    Sway's is the corpus case: `Post-Recap | | $10M | 0.4 | 875000 | 9/30/2025`.
    It carries no investment, so it is not a tranche and the tranche reader
    drops it — yet it is the event that changes which class the fund holds, and
    INV-17 turns on the class held AT A DATE. Without it, Sway reads as holding
    Series A forever, which makes the recap cap table's Series A-3 price look
    like cross-class pricing when post-recap the two are the same class.
    """

    security_class: str
    shares: int
    price_per_share: Decimal
    effective_date: date
    source_text: str


#: A row whose `Type` cell announces a conversion rather than a purchase.
_RECAP_KIND = re.compile(r"post-recap|recapitali[sz]ation|conversion", re.I)


def recapitalisation(notes: list[SheetNote]) -> Recapitalisation | None:
    """The conversion this sheet records, if it records one.

    The row itself states a share count, a price and a date, and not the class
    they belong to — so the class is read from the documentation line bearing
    the same date, by the same rule that binds a line to a tranche. Sway's row
    reads `Post-Recap | | $10M | 0.4 | 875000 | 9/30/2025` and its line reads
    "Sway - Series A-3 Recapitalization - Pro Forma Capitalization Table
    (September 30, 2025)".

    A conversion that cannot say into what class raises. Recording the share
    count without the class would leave the fund holding 875,000 of something
    unnamed, and INV-17 compares held class against priced class — an unnamed
    one makes the comparison read as cross-class forever.
    """
    for note in notes:
        if not _RECAP_KIND.search(note.text):
            continue
        cells = note.cells
        if len(cells) < 6:
            continue
        shares, pps, when = _int(cells[4]), _decimal(cells[3]), _as_day(cells[5])
        if shares is None or pps is None or when is None:
            raise ClassificationError(
                f"{note.company}: a recapitalisation row states {note.cells!r}, which does "
                f"not carry a share count, a price and a date together. A conversion that "
                f"cannot say how many shares, at what, and when, is not recordable."
            )
        into = _class_named_on([n for n in notes if not _CHROME.match(n.text)], when)
        if into is None:
            raise ClassificationError(
                f"{note.company}: a recapitalisation is recorded effective {when} and no "
                f"documentation line dated then names the class converted into. The shares "
                f"would reach the ledger as a class nobody named, and INV-17 compares the "
                f"class HELD against the class PRICED."
            )
        return Recapitalisation(into.value, shares, pps, when, f"{note.text} · {into.source_text}")
    return None


def _int(value: object) -> int | None:
    number = _decimal(value)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip().replace(",", "").replace("$", ""))
        except InvalidOperation:
            return None
    return None


def _as_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None
    return None
