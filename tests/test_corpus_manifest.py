"""The corpus manifest against the extractors: is this the RIGHT passage?

Everything else in this system proves a citation is internally consistent.
`packages/contracts/citations.py` computes the span from the quote so the two
cannot disagree, `0008_citations_resolve.sql` re-checks the same equality inside
the database, and `supports_value` proves the figure is really in the passage.
All of that holds just as well when the passage is the wrong one. A citation
pointing at the FY2024 Jio statement for a FY2023 NAV resolves verbatim, matches
its offsets, satisfies both triggers and exports cleanly.

`evals/oracle/corpus_manifest.yaml` is the artefact that can catch that. It was
transcribed from the PDFs by someone who deliberately read nothing under
`ingest/documents/`, so it is a second, independent reading of the same corpus —
104 figures, each with the window a correct citation must fall inside, and 56
`distractors`: real passages, in real documents, that state the same number
meaning something else. This file joins the two and reports where they differ.

## Three departures from `comparison_contract`, each because the contract as
## written is wrong on this corpus

**The passage check is POSITIONAL, not substring.** The contract asks that the
system's quote be a substring of the manifest's `passage`. It is not, seven
times, on citations that are correct. `locate_pattern` deliberately captures
more context than the manifest's window — Poolside's settlement citation opens
`7GC Fund II, L.P.: $2,000,000.00 received August 1, 2024` where the window
opens at `$2,000,000.00`, because a quote that identifies itself is what an
auditor can check. Rejecting those would be five false failures on the
settlement limb of the audit letter's first request and two more on term-sheet
valuation rows. So the manifest's `passage` is resolved to a character range in
the document it names, and the rule is that the figure's own span sits inside
that range. Anyone tempted to "restore" the substring rule should read
`test_the_substring_rule_the_contract_asks_for_would_reject_correct_citations`
first — it names the seven.

**A range is keyed on (document, offset), never on offset alone.** The three Jio
capital account statements are byte-identical apart from one line, so the same
offsets exist in all three and mean different years. `Window.holds` compares the
document before it compares anything else, which makes that structural rather
than remembered.

**A distractor is checked only against the ONE figure the map binds to that
fact.** Read as "does any extracted figure cite this distractor" it fails 44 of
56 times — because 44 of the distractor passages are the correct citation of
some OTHER manifest fact. Sway's `Conversion of 800,000 Series A at 1.09375 : 1`
is a distractor for the post-recapitalisation share count and the right passage
for the pre-recapitalisation one. A check wrong in that direction goes red
everywhere at once, which reads as "the extractors are broken" and means "the
check is broken" — the exact shape `join` in the manifest warns about.

## What is deliberately silent

Seven of the fourteen `absences` name a missing DOCUMENT — `executed_entry_
documents`, `executed_a2_documents` — not a missing figure. `extracted_fact`
holds no row shaped like "the executed Series A-1 purchase agreement", so
querying it for their absence returns empty whether the document is missing or
the query is wrong. Those belong against `document_gap`, which is populated from
the trackers. They are excluded by name rather than allowed to pad a count.

## The corpus is private, so half of this runs nowhere

The case-study documents are gitignored and will never be in CI. Every check
against them therefore skips there, and a guard proved only where the private
material lives has not been proved. So each rule this file depends on — window
resolution, positional containment, document identity, distractor scoping, the
shared-window obligation — is also exercised against synthetic text at the
bottom of the file, where it runs everywhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from ingest.documents.claims import FactDraft
from ingest.documents.load import SOURCES
from ingest.documents.parse import parse
from packages.contracts.citations import cited_numeral, supports_value
from tests.corpus_map import DOCUMENT_GAP_ABSENCES, FIELD, HOLDING, UNMATCHED

ROOT = Path(__file__).resolve().parents[1]
MANIFEST: dict[str, Any] = yaml.safe_load(
    (ROOT / "evals/oracle/corpus_manifest.yaml").read_text(encoding="utf-8")
)
FACTS: list[dict[str, Any]] = MANIFEST["facts"]
ABSENCES: list[dict[str, Any]] = MANIFEST["absences"]
SOURCE_PATH: dict[str, Path] = {entry["id"]: Path(entry["path"]) for entry in MANIFEST["sources"]}

CORPUS_PRESENT = all(source.path.exists() for source in SOURCES)
NO_CORPUS = "case-study documents are not in the repository"

#: Denominators, asserted rather than counted, for the reason
#: `tests/test_policy_vs_oracle.py` states about its own 175: a check whose
#: denominator comes from the data cannot report that the data shrank. Every one
#: of these was read off the manifest and confirmed against the extractors.
EXPECTED_FACTS = 104
EXPECTED_DISTRACTORS = 56
EXPECTED_ALSO_STATED = 5
EXPECTED_PASSAGES = EXPECTED_FACTS + EXPECTED_DISTRACTORS + EXPECTED_ALSO_STATED
EXPECTED_BOUND_FACTS = 95
EXPECTED_UNMATCHED_FACTS = 9
#: 95 bound facts, one of which — Banzai's position size — is cited onto three
#: year-end claims and so is checked three times.
EXPECTED_FIGURES = 97
EXPECTED_SHARED_WINDOWS = 11
EXPECTED_FIGURE_ABSENCES = 6
EXPECTED_DOCUMENT_GAP_ABSENCES = 7
#: What the contract's substring rule would reject, all of them correct.
EXPECTED_SUBSTRING_REJECTS = 7
#: What an unscoped distractor check would report, all of them false.
EXPECTED_UNSCOPED_DISTRACTOR_HITS = 44


class WindowError(AssertionError):
    """A manifest passage does not name exactly one place in its document."""


@dataclass(frozen=True)
class Place:
    """Where one figure sits: a document, and a range within its canonical text."""

    document: str
    start: int
    end: int


@dataclass(frozen=True)
class Window:
    """The range a correct citation of one manifest fact must fall inside."""

    document: str
    start: int
    end: int

    def holds(self, place: Place) -> bool:
        """Is that figure inside this window?

        The document is compared FIRST and unconditionally. Three Jio statements
        are identical apart from their as-of line, so offset 805 exists in all
        three and means a different year in each; a containment test taking two
        integers would accept the 2024 statement for a 2023 figure and there is
        nothing else in the data to tell them apart.
        """
        return (
            self.document == place.document and self.start <= place.start <= place.end <= self.end
        )


@dataclass(frozen=True)
class Bound:
    """One manifest fact, and the extracted figure this map says it is about."""

    fact_id: str
    source_id: str
    claim_key: str
    field_name: str
    value_text: str
    place: Place


_WHITESPACE = re.compile(r"\s+")


@lru_cache(maxsize=64)
def _flattened(text: str) -> tuple[str, tuple[int, ...]]:
    """`text` with whitespace runs collapsed, and where each character came from.

    The manifest asks for whitespace normalisation on both sides before
    comparing, and it is right to: these documents are `pdftotext -layout`
    output, so a cap-table row carries thirty-odd spaces between a label and its
    figure and a sentence wraps mid-phrase. What the contract does not say is
    that the comparison still has to produce an ANSWER IN THE ORIGINAL TEXT,
    because that is where the citation's offsets live. So the origin of every
    surviving character is carried alongside.
    """
    kept: list[str] = []
    origin: list[int] = []
    at = 0
    for run in _WHITESPACE.finditer(text):
        for index in range(at, run.start()):
            kept.append(text[index])
            origin.append(index)
        kept.append(" ")
        origin.append(run.start())
        at = run.end()
    for index in range(at, len(text)):
        kept.append(text[index])
        origin.append(index)
    lo, hi = 0, len(kept)
    while lo < hi and kept[lo] == " ":
        lo += 1
    while hi > lo and kept[hi - 1] == " ":
        hi -= 1
    return "".join(kept[lo:hi]), tuple(origin[lo:hi])


def resolve_window(document: str, canonical_text: str, passage: str) -> Window:
    """The one place `passage` occurs, as a range in the untouched text.

    Exactly one. A passage occurring twice names no window, and taking the first
    match would silently pick a row — which is the same objection `locate()`
    makes to an ambiguous quote, made from the answer key's side.
    """
    want = _WHITESPACE.sub(" ", passage).strip()
    if not want:
        raise WindowError(f"{document}: an empty passage names no window")
    flat, origin = _flattened(canonical_text)
    hits = [match.start() for match in re.finditer(re.escape(want), flat)]
    if len(hits) != 1:
        raise WindowError(
            f"{document}: the passage occurs {len(hits)} time(s), so it names no "
            f"single window: {want[:90]!r}"
        )
    at = hits[0]
    return Window(document, origin[at], origin[at + len(want) - 1] + 1)


def figure_place(document: str, quote: str, span_start: int, value_text: str) -> Place:
    """Where the figure itself sits, rather than where its quote starts.

    This is the whole of the departure from the contract's substring rule. A
    correct citation may quote a whole schedule row to say WHICH row it means;
    the figure it is cited for is a few characters inside that row, and it is
    the figure's position that has to fall in the manifest's window.
    """
    if not supports_value(quote, value_text):
        raise WindowError(
            f"{document}: the cited passage does not state {value_text!r} as a figure "
            "in its own right, exactly once"
        )
    if quote.count(value_text) != 1:
        raise WindowError(
            f"{document}: {value_text!r} appears {quote.count(value_text)} times in its "
            "own quote, so its position is not decided"
        )
    at = quote.index(value_text)
    return Place(document, span_start + at, span_start + at + len(value_text))


@lru_cache(maxsize=1)
def _extracted() -> dict[str, tuple[tuple[str, FactDraft], ...]]:
    """Every figure the corpus produces, keyed by manifest source id.

    Read from the extractors rather than from `extracted_fact`, for the reason
    `tests/test_field_requirements.py` gives: a census taken against the
    database measures whichever corpus somebody last loaded. `store_claim`
    writes each `FactDraft` verbatim, so a round trip through Postgres would add
    a dependency and prove nothing extra.
    """
    by_path = {source.path: source for source in SOURCES}
    out: dict[str, tuple[tuple[str, FactDraft], ...]] = {}
    for source_id, path in SOURCE_PATH.items():
        source = by_path.get(path)
        if source is None:
            continue
        parsed = parse(source.path)
        rows: list[tuple[str, FactDraft]] = []
        for draft in source.build(f"dv_{parsed.text_hash[:24]}", parsed, source.holding_id):
            rows += [(draft.claim_key, fact) for fact in draft.facts]
        out[source_id] = tuple(rows)
    return out


def _text(source_id: str) -> str:
    return parse(SOURCE_PATH[source_id]).canonical_text


def _window(source_id: str, passage: str) -> Window:
    return resolve_window(source_id, _text(source_id), passage)


def _figures(fact: dict[str, Any]) -> list[Bound]:
    """The extracted figures this map binds to one manifest fact.

    A claim key of `None` means every claim the document makes, which is not the
    same as any one of them: Banzai's saved quote record states the position
    size once and the extractor cites it onto all three year-end claims, so all
    three have to agree.
    """
    claim_key, field_name = FIELD[fact["id"]]
    source_id = fact["source"]
    document_text = _text(source_id)
    found: list[Bound] = []
    for key, draft in _extracted()[source_id]:
        if draft.field_name != field_name or (claim_key is not None and key != claim_key):
            continue
        assert (
            draft.citation.quote
            == document_text[draft.citation.span_start : draft.citation.span_end]
        )
        found.append(
            Bound(
                fact_id=fact["id"],
                source_id=source_id,
                claim_key=key,
                field_name=field_name,
                value_text=draft.value_text,
                place=figure_place(
                    source_id,
                    draft.citation.quote,
                    draft.citation.span_start,
                    draft.value_text,
                ),
            )
        )
    return found


def _bindings() -> list[Bound]:
    return [row for fact in FACTS if fact["id"] in FIELD for row in _figures(fact)]


def _flat(passage: str) -> str:
    return _WHITESPACE.sub(" ", passage).strip()


# ── The join ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_every_manifest_fact_is_either_bound_to_a_figure_or_recorded_as_unbound() -> None:
    """No fact may fall out of the comparison by not being mentioned.

    The failure this guards is the quiet one: a map that covers eighty of the
    hundred and four, passes every other check in this file, and reports
    coverage of a corpus it is looking at four fifths of. Both directions are
    asserted, so a map entry for a fact the manifest has dropped is a failure
    too.
    """
    ids = [fact["id"] for fact in FACTS]
    assert len(ids) == len(set(ids)) == EXPECTED_FACTS
    assert not set(FIELD) & set(UNMATCHED), "a fact cannot be both bound and unbound"
    assert set(FIELD) | set(UNMATCHED) == set(ids), (
        f"unaccounted for: {sorted(set(ids) - set(FIELD) - set(UNMATCHED))[:5]}; "
        f"named but not in the manifest: {sorted((set(FIELD) | set(UNMATCHED)) - set(ids))[:5]}"
    )
    assert len(FIELD) == EXPECTED_BOUND_FACTS
    assert len(UNMATCHED) == EXPECTED_UNMATCHED_FACTS
    assert all(len(reason) > 80 for reason in UNMATCHED.values()), (
        "an unbound fact is a finding; each one carries the reason a person recorded"
    )


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_each_bound_fact_names_exactly_one_extracted_figure_per_claim() -> None:
    """A map entry matching two figures would compare whichever came first.

    Banzai's position size is the deliberate exception and it is stated as one:
    three claims, three figures, all three checked. Everything else is one.
    """
    census = {fact["id"]: len(_figures(fact)) for fact in FACTS if fact["id"] in FIELD}
    empty = sorted(name for name, count in census.items() if count == 0)
    assert not empty, f"{len(empty)} bound fact(s) match no extracted figure: {empty[:5]}"
    plural = {name: count for name, count in census.items() if count > 1}
    assert plural == {"banzai.fund_shares": 3}, f"unexpectedly ambiguous bindings: {plural}"
    assert sum(census.values()) == EXPECTED_FIGURES


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_every_passage_the_manifest_names_resolves_to_exactly_one_place() -> None:
    """The precondition for every other check here, asserted on its own.

    A window that cannot be resolved is not a disagreement about a figure; it is
    a manifest passage that has drifted from the text layer, and reporting it as
    a wrong citation would send someone to read the wrong document. Counting the
    resolvable passages separately is also how a shrinking manifest shows up:
    165 is 104 facts, 56 distractors and 5 second statements of a figure.
    """
    facts = distractors = also = 0
    for fact in FACTS:
        _window(fact["source"], fact["passage"])
        facts += 1
        for entry in fact.get("distractors") or []:
            _window(entry["source"], entry["passage"])
            distractors += 1
        for entry in fact.get("also_stated_in") or []:
            _window(entry["source"], entry["passage"])
            also += 1
    assert (facts, distractors, also) == (
        EXPECTED_FACTS,
        EXPECTED_DISTRACTORS,
        EXPECTED_ALSO_STATED,
    )
    assert facts + distractors + also == EXPECTED_PASSAGES


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_every_figure_is_cited_to_the_document_and_holding_the_manifest_names() -> None:
    """Wrong-source citation, which no internal check can see.

    The Jio statements exist in this corpus to exercise exactly this: a NAV
    quote for 2023 pointing at the 2024 statement resolves, matches its offsets
    and exports cleanly. Only source identity separates right from wrong.

    The holding limb is checked here too because `ingest/documents/load.py` is
    the single place a document is bound to a holding, and nothing else in the
    suite compares that binding against an independent reading of the corpus —
    a guard on the fund prefix alone accepts Roofstock's agreement filed under
    Poolside.
    """
    by_path = {source.path: source for source in SOURCES}
    problems: list[str] = []
    for fact in FACTS:
        if fact["id"] not in FIELD:
            continue
        path = SOURCE_PATH[fact["source"]]
        wanted = HOLDING.get(fact["holding_id"], fact["holding_id"])
        loaded = by_path[path].holding_id
        if loaded != wanted:
            problems.append(f"{fact['id']}: {fact['source']} is loaded as {loaded}, not {wanted}")
        for row in _figures(fact):
            if row.place.document != fact["source"]:
                problems.append(f"{fact['id']}: cited to {row.place.document}")
    assert not problems, f"{len(problems)} wrong-source citation(s):\n" + "\n".join(problems[:10])


# ── The passage check ────────────────────────────────────────────────────


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_every_cited_figure_sits_inside_the_passage_the_manifest_names() -> None:
    """The substantive check: is this the right passage, not merely a real one?

    A quote verbatim in the document but outside the window is precisely the
    defect the manifest exists to detect. Problems are collected rather than
    asserted one at a time, because the shape of the failure carries the
    diagnosis: two or three rows is a defect in an extractor, and ninety-seven
    is a defect in the join.
    """
    problems: list[str] = []
    checked = 0
    for fact in FACTS:
        if fact["id"] not in FIELD:
            continue
        window = _window(fact["source"], fact["passage"])
        for row in _figures(fact):
            checked += 1
            if not window.holds(row.place):
                problems.append(
                    f"{fact['id']} ({row.claim_key}.{row.field_name} = {row.value_text!r}) "
                    f"cites [{row.place.start}, {row.place.end}) in {row.source_id}; the "
                    f"manifest's window is [{window.start}, {window.end})"
                )
    assert checked == EXPECTED_FIGURES, (
        f"checked {checked} figures, expected {EXPECTED_FIGURES}. The join shrank, so "
        "this gate now covers less than it reports."
    )
    assert not problems, f"{len(problems)} figure(s) outside their window:\n" + "\n".join(
        problems[:10]
    )


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_the_substring_rule_the_contract_asks_for_would_reject_correct_citations() -> None:
    """Why the check above is positional, kept as a check rather than a comment.

    `comparison_contract.passage_check` asks that the system's quote be a
    substring of the manifest's passage. Seven correct citations are not, and
    they are not by design: `locate()` refuses an ambiguous quote, so an
    extractor quotes the holder row rather than the figure alone. Five of the
    seven are the settlement limb of the audit letter's first request — the part
    that says the money actually moved — so the substring rule would report the
    strongest evidence in the corpus as a wrong-passage defect.

    Naming them here means the next person to propose the substring rule finds
    the counter-example instead of the argument, and that if `locate()` is ever
    narrowed to quote less, this test goes red and says so.
    """
    rejected: list[str] = []
    for fact in FACTS:
        if fact["id"] not in FIELD:
            continue
        allowed = [_flat(fact["passage"])] + [
            _flat(entry["passage"]) for entry in fact.get("also_stated_in") or []
        ]
        for row in _figures(fact):
            quote = next(
                _flat(draft.citation.quote)
                for key, draft in _extracted()[row.source_id]
                if key == row.claim_key and draft.field_name == row.field_name
            )
            if not any(quote in window for window in allowed):
                rejected.append(row.fact_id)
    assert sorted(rejected) == [
        "fluidstack.series_a.settlement_reference",
        "lucra.series_a1.pre_money_valuation",
        "mom_project.series_c.pre_money_valuation",
        "poolside.series_b.settlement_date",
        "poolside.series_b.settlement_reference",
        "roofstock.series_e.settlement_date",
        "roofstock.series_e.settlement_reference",
    ]
    assert len(rejected) == EXPECTED_SUBSTRING_REJECTS


# ── Distractors ──────────────────────────────────────────────────────────


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_no_figure_lands_in_a_passage_the_manifest_marks_as_the_wrong_one() -> None:
    """The 56 passages that state the right number for the wrong reason.

    Jackpocket states $3,100,000.00 twice, as gross consideration and as net
    payment; each Jio statement states $1,000,000.00 three times, as commitment,
    contributed capital and NAV. In every one of those cases the value check
    cannot separate right from wrong and the passage is the only thing standing.

    The distractor's own `why_wrong` is put in the failure message because it
    names what went wrong rather than that something did.
    """
    problems: list[str] = []
    checked = 0
    for fact in FACTS:
        for entry in fact.get("distractors") or []:
            checked += 1
            if fact["id"] not in FIELD:
                continue
            window = _window(entry["source"], entry["passage"])
            for row in _figures(fact):
                if window.holds(row.place):
                    problems.append(f"{fact['id']} cites its distractor: {entry['why_wrong']}")
    assert checked == EXPECTED_DISTRACTORS
    assert not problems, "\n".join(problems[:10])


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_a_distractor_belongs_to_one_fact_and_not_to_the_corpus() -> None:
    """Why the check above is scoped, kept as a check for the same reason.

    Asked as "does ANY extracted figure cite this distractor", 44 of the 56 come
    back positive — because a distractor is a real passage stating a real
    figure, and 44 of them are the correct citation of some other manifest fact.
    Sway's `Conversion of 800,000 Series A at 1.09375 : 1` is the wrong passage
    for the post-recapitalisation share count and the right one for the
    pre-recapitalisation count, and the corpus is full of that pattern.

    A check failing 44 times out of 56 does not read as a broken check. It reads
    as a broken system, which is the most expensive way to be wrong.
    """
    unscoped = 0
    for fact in FACTS:
        for entry in fact.get("distractors") or []:
            window = _window(entry["source"], entry["passage"])
            for _key, draft in _extracted()[entry["source"]]:
                place = figure_place(
                    entry["source"],
                    draft.citation.quote,
                    draft.citation.span_start,
                    draft.value_text,
                )
                if window.holds(place):
                    unscoped += 1
                    break
    assert unscoped == EXPECTED_UNSCOPED_DISTRACTOR_HITS
    assert unscoped > EXPECTED_DISTRACTORS // 2, (
        "the unscoped rule is not a stricter version of the scoped one; it is a "
        "different and wrong question"
    )


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_two_facts_sharing_one_window_are_told_apart_by_where_their_figures_sit() -> None:
    """Containment alone cannot separate two figures quoted from one row.

    Sway is the case that forces this. `fund_shares` (875,000) and
    `prior_shares` (800,000) carry an identical window — the fund's row in
    Section 4 — and the 875,000 fact's own distractor IS the 800,000 sub-span.
    Both figures are inside the window, so the window says nothing; position
    says everything, and the two must not be the same position. Eleven windows
    in this corpus are shared, including all three Banzai year-ends, where the
    closing price and the position value sit in one line.
    """
    windows: dict[tuple[str, int, int], dict[str, Place]] = {}
    for fact in FACTS:
        if fact["id"] not in FIELD:
            continue
        window = _window(fact["source"], fact["passage"])
        for row in _figures(fact):
            windows.setdefault((window.document, window.start, window.end), {})[fact["id"]] = (
                row.place
            )
    shared = {key: places for key, places in windows.items() if len(places) > 1}
    assert len(shared) == EXPECTED_SHARED_WINDOWS
    collisions = {
        key: places for key, places in shared.items() if len(set(places.values())) != len(places)
    }
    assert not collisions, f"figures sharing a window and a position: {collisions}"
    sway = next(places for key, places in shared.items() if "sway.series_a3.fund_shares" in places)
    assert sway["sway.series_a3.fund_shares"].start < sway["sway.series_a3.prior_shares"].start


# ── Values ───────────────────────────────────────────────────────────────


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_the_number_the_system_stored_is_the_number_the_manifest_read() -> None:
    """The right window is not the right figure. Both, or neither is worth much.

    A citation can land squarely inside the manifest's window and still carry
    the wrong number out of it — Banzai's year-end line states a date, a price
    and a position value in forty-five characters. `cited_numeral` is the
    project's own parser, mirrored in plpgsql and proved against it in
    `tests/test_citations.py`; a second one written here would be a mirror that
    drifts.

    One figure in the corpus states a number `cited_numeral` refuses, and
    refusing is right: Lucra's CEO wrote `$95M`, and the rule that reads that as
    ninety-five million is the rule that read `November 14, 2025` as 142025.
    """
    problems: list[str] = []
    compared = 0
    unparsed: list[str] = []
    for fact in FACTS:
        if fact["id"] not in FIELD:
            continue
        value = fact["value"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        for row in _figures(fact):
            stated = cited_numeral(row.value_text)
            if stated is None:
                unparsed.append(fact["id"])
                continue
            compared += 1
            if stated != Decimal(str(value)):
                problems.append(f"{fact['id']}: manifest {value}, system {row.value_text!r}")
    assert unparsed == ["lucra.series_a2.post_money_valuation"]
    assert compared == 78
    assert not problems, f"{len(problems)} figure(s) disagree:\n" + "\n".join(problems[:10])


# ── Absences ─────────────────────────────────────────────────────────────


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_no_figure_is_published_where_the_manifest_records_that_none_is_stated() -> None:
    """The fabrication cases: real in the tracker, arithmetically available, and
    stated by no document.

    Lucra is the one to watch and the manifest says so: the tracker records
    750,000 shares, the term sheet states a $1,500,000 commitment and a $2.00
    price and nothing about a share count, and 750,000 is the quotient. Easy to
    compute, obviously right, and with no passage anywhere.

    A figure already bound to a manifest fact is not a violation. Fluidstack's
    Series A-2 aggregate cost is absent while the Series A one is present in the
    same agreement, so the check has to distinguish "this document states no
    such figure" from "this document states one for another lot".
    """
    family: dict[str, set[str]] = {}
    for fact in FACTS:
        if fact["id"] in FIELD:
            family.setdefault(fact["field"], set()).add(FIELD[fact["id"]][1])
    accounted = {(row.source_id, row.claim_key, row.field_name) for row in _bindings()}

    problems: list[str] = []
    checked = out_of_scope = 0
    for absence in ABSENCES:
        field = absence.get("field")
        if field is None:
            continue
        if field in DOCUMENT_GAP_ABSENCES:
            out_of_scope += 1
            continue
        checked += 1
        names = family.get(field, set())
        assert names, f"{field} is claimed absent somewhere and bound nowhere"
        for source_id in absence["not_stated_in"]:
            for key, draft in _extracted()[source_id]:
                if (
                    draft.field_name in names
                    and (source_id, key, draft.field_name) not in accounted
                ):
                    problems.append(
                        f"{absence['holding_id']}.{field} is recorded as stated by no "
                        f"document, but {source_id} publishes {draft.field_name} = "
                        f"{draft.value_text!r}"
                    )
    assert (checked, out_of_scope) == (
        EXPECTED_FIGURE_ABSENCES,
        EXPECTED_DOCUMENT_GAP_ABSENCES,
    ), "the split between figure absences and document gaps moved"
    assert not problems, "\n".join(problems[:10])


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_because_market_has_no_document_and_therefore_no_figure() -> None:
    """The single most important entry in `SOURCES` is the one that is not there.

    The fund holds a $1,000,000 Because Market position whose price, share count
    and cost exist only in the Master Investment Breakdown, which records the
    supporting agreement as not located. A pipeline producing an empty record
    for it rather than no record would read as coverage, and a packet showing
    nothing for it is correct.
    """
    absence = next(entry for entry in ABSENCES if entry.get("missing") == "every document")
    holding = HOLDING.get(absence["holding_id"], absence["holding_id"])
    assert holding == "fund_ii_because_market"
    assert not [source for source in SOURCES if source.holding_id == holding]
    assert not [row for row in _bindings() if row.fact_id.startswith("because_market.")]
    assert not [fact for fact in FACTS if fact["holding_id"] == absence["holding_id"]]


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_the_only_evidence_of_what_the_fund_paid_for_jackpocket_and_banzai_is_unread() -> None:
    """The finding this file was built to surface, stated as a check.

    Four of the nine unbound facts are the corpus's ONLY statements of entry
    cost for two holdings. Jackpocket's is one sentence inside the paying
    agent's realisation notice — `December 30, 2021 at $4.00 per share
    ($2,000,000.00 aggregate), per the Company's stock ledger` — and there is no
    2021 purchase agreement anywhere. Banzai's is a parenthesis in a saved quote
    record: `held at March 2021 purchase price ($10.00/share; $500,000)`.

    Both documents are parsed today. Both figures are cited nowhere. So the
    audit letter's first request — existence and cost — is answered with silence
    for two holdings whose evidence the system has already read and discarded,
    and the packet cannot report a gap it does not know it has.

    This test passes while that is true. It goes red the day it stops being
    true, which is the day the four names below have to move into `FIELD`.
    """
    entry_cost = {
        "jackpocket.entry.fund_price_per_share",
        "jackpocket.entry.fund_aggregate_purchase_price",
        "banzai.entry.fund_price_per_share",
        "banzai.entry.fund_aggregate_purchase_price",
    }
    assert entry_cost <= set(UNMATCHED)
    for name in entry_cost:
        fact = next(entry for entry in FACTS if entry["id"] == name)
        # The passage is in the document and resolves; nothing reads it.
        assert _window(fact["source"], fact["passage"])
        assert not any(row.fact_id == name for row in _bindings())
    reads_nothing = {name for name, why in UNMATCHED.items() if why.startswith("Nothing extracts")}
    assert entry_cost < reads_nothing
    assert len(reads_nothing) == 6


@pytest.mark.skipif(not CORPUS_PRESENT, reason=NO_CORPUS)
def test_every_field_the_manifest_uses_is_declared_in_its_own_vocabulary() -> None:
    """`field_vocabulary` is the manifest's statement of what its names mean.

    A `field:` that does not appear there is a name whose meaning nobody wrote
    down, which is the one thing this file cannot map from — the mapping in
    `tests/corpus_map.py` is an editorial decision, and the vocabulary entry is
    what makes it reviewable rather than a guess. The manifest asks for exactly
    this itself: a name mismatch is not a value disagreement and must not be
    reported as one, which presumes both names exist.

    This is red today, on four names, and the fix belongs in the manifest and
    nowhere else. Editing the manifest to make a comparison pass is the one
    thing its own header forbids; adding a definition for a name it already uses
    is not that.
    """
    vocabulary = set(MANIFEST["field_vocabulary"])
    used = {fact["field"] for fact in FACTS}
    undeclared = sorted(used - vocabulary)
    assert not undeclared, (
        f"{len(undeclared)} field name(s) used by a fact and defined nowhere: {undeclared}"
    )


# ── The rules, on synthetic text ─────────────────────────────────────────
# Everything above needs the private corpus and skips in CI. A guard proved only
# where the private material lives has not been proved, so the rules themselves
# are exercised here on text this file writes. `mutate.py --ci` hides the corpus
# and runs exactly this configuration.

ROW = (
    "SCHEDULE A — SCHEDULE OF PURCHASERS\n"
    "  7GC Fund II, L.P.          625,000        $3.20        $2,000,000.00\n"
    "  Halden Ridge Capital       450,000        $3.20        $1,440,000.00\n"
)


def test_a_manifest_passage_names_the_one_place_it_occurs() -> None:
    """Resolution collapses the whitespace a text layer invents, and no more.

    `pdftotext -layout` puts thirty spaces between a label and its figure and
    wraps a sentence mid-phrase, so a byte-exact comparison would fail on
    formatting and say nothing. What it must NOT do is find two places and pick
    one — that is how a window silently moves to another row.
    """
    window = resolve_window("spa", ROW, "7GC Fund II, L.P. 625,000 $3.20 $2,000,000.00")
    assert _flat(ROW[window.start : window.end]) == "7GC Fund II, L.P. 625,000 $3.20 $2,000,000.00"
    assert resolve_window("spa", "a\n  b", "a b") == resolve_window("spa", "a\n  b", "  a   b  ")
    with pytest.raises(WindowError, match="occurs 2 time"):
        resolve_window("spa", ROW, "$3.20")
    with pytest.raises(WindowError, match="occurs 0 time"):
        resolve_window("spa", ROW, "7GC Fund I, L.P.")
    with pytest.raises(WindowError, match="empty passage"):
        resolve_window("spa", ROW, "   ")


def test_a_citation_carrying_more_context_than_the_window_still_falls_inside_it() -> None:
    """The departure from the contract, on text small enough to read.

    The extractor quotes the whole row to say which row it means. The manifest's
    window is the row too, so the figure is inside it — while the contract's
    substring rule compares the quote against the window and, on the real
    corpus, rejects seven correct citations for carrying the context that
    identifies them.
    """
    quote = "7GC Fund II, L.P.          625,000        $3.20        $2,000,000.00"
    window = resolve_window("spa", ROW, "625,000 $3.20 $2,000,000.00")
    place = figure_place("spa", quote, ROW.index(quote), "625,000")
    assert window.holds(place)
    # The rule the contract asks for, on the same pair, rejecting it.
    assert _flat(quote) not in _flat("625,000 $3.20 $2,000,000.00")


def test_a_figure_outside_the_window_is_refused_however_real_its_quote_is() -> None:
    """The defect being hunted: verbatim in the document, and the wrong passage."""
    other = "Halden Ridge Capital       450,000        $3.20        $1,440,000.00"
    window = resolve_window("spa", ROW, "7GC Fund II, L.P. 625,000 $3.20 $2,000,000.00")
    place = figure_place("spa", other, ROW.index(other), "450,000")
    assert not window.holds(place)


def test_the_same_offsets_in_two_documents_are_two_different_places() -> None:
    """Near-duplicate sources, which is the Jio hazard in miniature.

    Three capital account statements identical apart from their as-of line: the
    same offsets exist in all three and mean a different year in each. A
    containment test taking two integers accepts the wrong one and nothing else
    in the data can tell.
    """
    window = resolve_window("stmt_2023", ROW, "7GC Fund II, L.P. 625,000 $3.20 $2,000,000.00")
    here = figure_place("stmt_2023", "625,000", ROW.index("625,000"), "625,000")
    there = figure_place("stmt_2024", "625,000", ROW.index("625,000"), "625,000")
    assert window.holds(here)
    assert not window.holds(there)
    assert (here.start, here.end) == (there.start, there.end)


def test_two_figures_stated_in_one_passage_are_told_apart_by_where_they_sit() -> None:
    """Sway in miniature: one window, two figures, and a distractor inside it.

    Both figures are in the window, so containment says nothing about which is
    which. Their positions differ, which is the whole of the discrimination —
    and a distractor covering only the second figure must not implicate the
    first, which is why a distractor is checked against one bound figure rather
    than against the document.
    """
    row = "7GC Fund II, L.P. 875,000 Conversion of 800,000 Series A at 1.09375 : 1"
    window = resolve_window("recap", row, row)
    post = figure_place("recap", row, 0, "875,000")
    prior = figure_place("recap", row, 0, "800,000")
    assert window.holds(post) and window.holds(prior)
    assert post != prior
    distractor = resolve_window("recap", row, "Conversion of 800,000 Series A at 1.09375 : 1")
    assert distractor.holds(prior)
    assert not distractor.holds(post)


def test_a_figure_its_own_quote_does_not_state_has_no_place() -> None:
    """`figure_place` refuses rather than guessing, and reuses the project's rule.

    `supports_value` already answers "does this passage state this figure, once
    and unambiguously"; a second answer written here would be a mirror that
    drifts, and this file would then disagree with the database about which
    citations are wrong.
    """
    with pytest.raises(WindowError, match="in its own right"):
        figure_place("spa", "7GC Fund II, L.P. 625,000", 0, "625")
    with pytest.raises(WindowError, match="in its own right"):
        figure_place("spa", "issued at $8.00 per share", 0, "3.20")
