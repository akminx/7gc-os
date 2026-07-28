"""Finding the evidence a requirement needs. SPEC §10, layers 1 and 2.

    SQL metadata filter → Postgres FTS → rerank → top passages with page and span.

No model and no migration. The corpus is twenty documents and 44,365 characters
of canonical text, and a sequential scan with `to_tsvector` computed on the fly
answers in under a millisecond of server time — the round trip to Supabase is
about sixty times longer than the query. A generated `tsvector` column with a
GIN index would therefore buy nothing measurable, so it is not built; the
trigger is written down in `measured_query_cost()` rather than asserted here,
because "we did not need an index" is a claim about a number.

Three things are structural rather than conventional.

**Entity match is a filter, not a rank component.** A document about another
company is not weak evidence for this holding, it is not evidence for this
holding, and no amount of textual similarity should be able to promote it. So
`holding_id` narrows the candidate set in SQL and never appears in the rank
key. `recall_at_k()` measures what removing it costs, which is the only honest
way to say what layer 1 is worth.

**Authority is not a score (INV-1).** `SourceClass` is a lattice: press can
trigger research and cannot support a fair-value mark, and that is a statement
about kind, not about rank. Nothing here assigns a number to a source class.
The rerank is a *tuple*, compared lexicographically, whose leading element is
an index into an explicit enumeration of the `(source_class, execution_status)`
pairs this corpus exercises — a declared ordering over pairs, written down
where it can be read, not a weight applied to a dimension. It decides what an
auditor is shown first. It never decides sufficiency: that is
`policy.valid_tuples`, and `press` is `insufficient` for R2 at every position
in this list, including the top.

**A retrieved passage is already a citation.** The span is computed by
`locate()` from a verbatim slice of `canonical_text`, so the thing retrieval
hands back is the same object the ledger stores. There is no later step in
which a plausible offset could be attached to a passage that does not say it.
"""

from __future__ import annotations

import re
import time
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from ingest.documents.parse import split_pages
from packages.contracts.citations import locate
from packages.contracts.enums import ExecutionStatus, RequirementCode, SourceClass
from packages.contracts.models import Citation

Conn = psycopg.Connection[tuple[object, ...]]

#: SPEC §11 · "retrieval (fixed K=5, locked gold query set, declared relevance
#: judgements)". K is fixed in the spec, so it is a constant here rather than a
#: default someone can tune until the number looks good.
K = 5

#: How long a quoted passage may run before it is trimmed to a window around
#: the match. `-layout` renders a cap-table row as one very long line, and a
#: citation an auditor cannot read on one screen is a citation nobody checks.
MAX_PASSAGE_CHARS = 400


class RetrievalError(RuntimeError):
    """Retrieval could not produce something citable. Never downgraded."""


#: The locked gold query set. One query per evidence-bearing requirement, fixed
#: before any recall number was read, and deliberately written in the auditor's
#: vocabulary rather than the corpus's — a query tuned per document would make
#: `recall_at_k()` a measurement of the tuning.
#:
#: R3 and R5 are absent on purpose and `default_query()` refuses them. R3 is
#: closed by a management assessment and R5 is a label derived from R2's own
#: inputs, so neither is answered by pointing at a document — which is exactly
#: what `claim_requirement_is_evidence_bearing` in 0010 refuses to record.
GOLD_QUERIES: dict[RequirementCode, str] = {
    RequirementCode.R1: (
        "executed stock purchase agreement shares purchased price per share capital account balance"
    ),
    RequirementCode.R2: (
        "price per share post-money valuation closing price net asset value fair value"
    ),
    RequirementCode.R4: "merger consideration per share paid at closing realization proceeds",
}

#: The rerank's leading dimension: an ordering over `(source_class,
#: execution_status)` PAIRS, not over source classes.
#:
#: The pair is the unit because neither half orders on its own. `not_applicable`
#: is what a market quote and an administrator statement carry, and ordering
#: execution statuses alone would sort both below a pro forma cap table —
#: sinking the two strongest documents in the corpus. Equally, `company_cap_table`
#: means one thing `pro_forma` and another executed. Ordering the pair is the
#: only version of "executed beats pro forma beats press" that survives contact
#: with this corpus.
#:
#: `press` and `rumor` appear nowhere in this list, and that absence is the
#: point: they are not ranked last, they are unranked, and `_preference()`
#: gives every unlisted pair the same terminal position. A pair that is missing
#: because nobody has ruled on it is therefore indistinguishable from press —
#: which is the conservative direction, and `test_retrieval.py` asserts that
#: every pair the corpus actually exercises is enumerated, so an unruled pair
#: is a red test rather than a silent demotion.
PREFERENCE: tuple[tuple[SourceClass, ExecutionStatus], ...] = (
    (SourceClass.EXECUTED_TRANSACTION_DOC, ExecutionStatus.EXECUTED),
    (SourceClass.ADMINISTRATOR_STATEMENT, ExecutionStatus.NOT_APPLICABLE),
    (SourceClass.PUBLIC_MARKET_QUOTE, ExecutionStatus.NOT_APPLICABLE),
    (SourceClass.THIRD_PARTY_VALUATION_MEMO, ExecutionStatus.NOT_APPLICABLE),
    (SourceClass.FUND_INTERNAL_RECORD, ExecutionStatus.NOT_APPLICABLE),
    # The settlement clause inside an executed SPA — Roofstock's, Poolside's
    # and Fluidstack's. It is the company's own factual statement about how the
    # purchase was paid, carried in paperwork that was signed, and it has no
    # execution status of its own because a clause is not a document.
    (SourceClass.COMPANY_COMMUNICATION, ExecutionStatus.NOT_APPLICABLE),
    (SourceClass.COMPANY_CAP_TABLE, ExecutionStatus.PRO_FORMA),
    (SourceClass.COMPANY_CAP_TABLE, ExecutionStatus.UNEXECUTED_REFERENCED),
    (SourceClass.COMPANY_COMMUNICATION, ExecutionStatus.UNEXECUTED_REFERENCED),
    (SourceClass.COMPANY_COMMUNICATION, ExecutionStatus.NON_BINDING),
)


def _preference(source_class: SourceClass, execution_status: ExecutionStatus) -> int:
    pair = (source_class, execution_status)
    return PREFERENCE.index(pair) if pair in PREFERENCE else len(PREFERENCE)


def default_query(requirement: RequirementCode) -> str:
    """The locked query for this requirement, or refuse."""
    query = GOLD_QUERIES.get(requirement)
    if query is None:
        raise RetrievalError(
            f"{requirement.value} is not evidence-bearing, so no document answers it. "
            "R3 is closed by a management assessment and R5 is derived from R2's "
            "inputs; 0010's claim_requirement CHECK refuses to record either."
        )
    return query


@dataclass(frozen=True)
class Candidate:
    """One claim that survived the metadata filter, with its text rank."""

    claim_id: str
    holding_id: str
    claim_key: str
    document_version_id: str
    filename: str
    source_class: SourceClass
    execution_status: ExecutionStatus
    issued_date: date
    applicable_from: date
    applicable_to: date | None
    text_rank: float


@dataclass(frozen=True)
class RetrievedPassage:
    """A passage, the claim it came from, and the citation it already is.

    `citation` is produced by `locate()` against the same `canonical_text` the
    ledger stores, so `store_claim()` would accept it unchanged. `page` is read
    from the form feeds in that text by `ingest.documents.parse.split_pages`,
    which is the same function the ingestion path uses — a second page
    calculation is a second answer to one question.
    """

    candidate: Candidate
    citation: Citation
    page: int
    matched: tuple[str, ...]
    rank_key: tuple[int, int, float, str, int]


_CANDIDATES_SQL = """
with q as (
  select replace(plainto_tsquery('english', %(query)s)::text, '&', '|')::tsquery as any_q
)
select c.id, c.holding_id, c.claim_key, c.source_class::text, c.execution_status::text,
       c.issued_date, c.applicable_from, c.applicable_to,
       dv.id, sf.filename, dv.canonical_text,
       ts_rank(to_tsvector('english', dv.canonical_text), q.any_q)::float8,
       q.any_q::text
  from claim c
  join document_version dv on dv.id = c.document_version_id
  join source_file sf on sf.id = dv.source_file_id
  cross join q
 where (%(holding_id)s::text is null or c.holding_id = %(holding_id)s)
   and (not %(apply_window)s
        or (c.applicable_from <= %(on)s
            and (c.applicable_to is null or c.applicable_to >= %(on)s)))
   and (%(source_classes)s::text[] is null
        or c.source_class::text = any (%(source_classes)s::text[]))
   and (not %(scoped)s
        or exists (select 1 from claim_requirement cr
                    where cr.claim_id = c.id
                      and cr.requirement::text = %(requirement)s))
   and to_tsvector('english', dv.canonical_text) @@ q.any_q
 order by 12 desc, 9
"""

_LEXEME = re.compile(r"'((?:[^']|'')*)'")
_WORD = re.compile(r"[0-9A-Za-z][0-9A-Za-z'’-]*")


def _typed[T](value: object, kind: type[T], column: str) -> T:
    """A column read back as the type it is declared as, or a loud failure.

    `psycopg.Connection[tuple[object, ...]]` types every column as `object`, so
    without this the module would be a field of casts that assert rather than
    check — and a cast is exactly the construct that lets a NULL travel as a
    `str` until it is far away from the query that produced it.
    """
    if not isinstance(value, kind):
        raise RetrievalError(f"{column} came back as {type(value).__name__}, not {kind.__name__}")
    return value


def retrieve(
    conn: Conn,
    *,
    holding_id: str | None,
    measurement_date: date,
    requirement: RequirementCode,
    query: str | None = None,
    k: int = K,
    source_classes: Sequence[SourceClass] | None = None,
    apply_window: bool = True,
    requirement_scoped: bool = False,
) -> tuple[RetrievedPassage, ...]:
    """The top `k` passages for this requirement at this measurement date.

    `holding_id=None` removes the entity filter, which is not a supported way
    to run retrieval — it is how `recall_at_k()` measures what the filter is
    worth. Layer 1 narrows this corpus to about one document per case, so the
    entity-scoped recall number says almost nothing about the ranker on its
    own; the blind number is the one that does.

    `apply_window` likewise exists to be turned off in measurement. The window
    is INV-16's source-stated reliance window, and dropping it asks the ranker
    to choose between a holding's documents by date proximity rather than being
    handed the answer by SQL.

    At most one passage per claim. A document that makes several claims can
    therefore appear several times — INV-15, authority lives on the claim, and
    Fluidstack's Series B table genuinely makes two claims of different
    execution status — but a single verbose document cannot crowd the other
    nineteen out of a top-5 by contributing five passages to it.
    """
    text = query if query is not None else default_query(requirement)
    rows = conn.execute(
        _CANDIDATES_SQL,
        {
            "query": text,
            "holding_id": holding_id,
            "on": measurement_date,
            "apply_window": apply_window,
            "source_classes": (
                [c.value for c in source_classes] if source_classes is not None else None
            ),
            #: Off by default so `recall_at_k()` keeps measuring the ranker it
            #: has always measured. The ROUTE turns it on, because a reader who
            #: picks "fair-value support" and is handed this holding's
            #: existence-and-cost paperwork has been answered a question they
            #: did not ask — and could reasonably file it as fair-value support.
            "scoped": requirement_scoped,
            "requirement": requirement.value,
        },
    ).fetchall()

    if not rows:
        _refuse_empty_query(conn, text)
        return ()

    passages: list[RetrievedPassage] = []
    for row in rows:
        candidate = _candidate(row)
        canonical_text = _typed(row[10], str, "document_version.canonical_text")
        lexemes = tuple(m.group(1).replace("''", "'") for m in _LEXEME.finditer(str(row[12])))
        best = _best_passage(canonical_text, lexemes)
        if best is None:
            continue
        start, end, matched = best
        citation = _cite(candidate.document_version_id, canonical_text, start, end)
        passages.append(
            RetrievedPassage(
                candidate=candidate,
                citation=citation,
                page=_page_of(canonical_text, citation.span_start),
                matched=matched,
                rank_key=_rank_key(candidate, measurement_date, citation.span_start),
            )
        )

    passages.sort(key=lambda p: p.rank_key)
    return tuple(passages[:k])


def _rank_key(
    candidate: Candidate, measurement_date: date, passage_start: int
) -> tuple[int, int, float, str, int]:
    """The rerank, as a tuple compared lexicographically. INV-1.

    Five independent comparisons in a declared priority order, never combined
    into one number:

    1. the `(source_class, execution_status)` pair's position in `PREFERENCE`;
    2. how far the claim's issue date is from the measurement date, in days —
       closer wins, and `abs` rather than a signed difference because a claim
       issued after the date is already excluded by the window filter, so a
       negative distance here means the caller turned the window off and is
       asking which document is nearest, not which is earlier;
    3. the full-text rank, negated so higher ranks sort first;
    4. the document version id, and
    5. the passage offset — the declared tie-break SPEC §10 asks for, so two
       runs over unchanged data return the same order in the same sequence.

    A weighted sum of the same five would let a very high `ts_rank` promote a
    press article above an executed transaction document, which is the shape
    INV-1 exists to forbid. Lexicographic comparison cannot: no amount of
    element 3 changes element 1.
    """
    return (
        _preference(candidate.source_class, candidate.execution_status),
        abs((measurement_date - candidate.issued_date).days),
        -candidate.text_rank,
        candidate.document_version_id,
        passage_start,
    )


def _candidate(row: Sequence[object]) -> Candidate:
    return Candidate(
        claim_id=_typed(row[0], str, "claim.id"),
        holding_id=_typed(row[1], str, "claim.holding_id"),
        claim_key=_typed(row[2], str, "claim.claim_key"),
        document_version_id=_typed(row[8], str, "document_version.id"),
        filename=_typed(row[9], str, "source_file.filename"),
        source_class=SourceClass(_typed(row[3], str, "claim.source_class")),
        execution_status=ExecutionStatus(_typed(row[4], str, "claim.execution_status")),
        issued_date=_typed(row[5], date, "claim.issued_date"),
        applicable_from=_typed(row[6], date, "claim.applicable_from"),
        applicable_to=row[7] if row[7] is None else _typed(row[7], date, "claim.applicable_to"),
        text_rank=float(_typed(row[11], float, "ts_rank")),
    )


def _refuse_empty_query(conn: Conn, text: str) -> None:
    """Distinguish "nothing matched" from "the query had nothing in it".

    `plainto_tsquery('english', 'the of and')` is the empty tsquery, which
    matches no document — so a query made entirely of stop words returns zero
    rows and reads exactly like a corpus with no relevant evidence in it. One
    of those is a finding about the fund and the other is a bug in the caller.
    """
    row = conn.execute("select plainto_tsquery('english', %s)::text", (text,)).fetchone()
    if row is not None and not str(row[0]).strip():
        raise RetrievalError(
            f"the query {text!r} reduces to no search terms, so it matches nothing "
            "regardless of what the corpus contains"
        )


def _cite(document_version_id: str, canonical_text: str, start: int, end: int) -> Citation:
    """Turn a slice of the canonical text into a citation, via `locate()` only.

    The offsets are already known here — the passage was chosen by scanning the
    text — and they are still not written down. `locate()` re-finds the quote
    and computes the span itself, which is what makes this module unable to
    produce a citation that does not resolve, in the same way
    `ingest.documents.claims.cited_fact()` is.

    `occurrence` is passed rather than left to `locate()`'s uniqueness rule, and
    this is the one place in the project where an index into a list of matches
    is the honest answer: the passage is a slice *at a known offset*, so "the
    third identical line" is precisely what is meant. A quote that identifies
    itself is better where a human wrote it; here nobody did.
    """
    quote = canonical_text[start:end]
    starts = [m.start() for m in re.finditer(re.escape(quote), canonical_text)]
    if start not in starts:
        raise RetrievalError(
            f"passage at [{start}, {end}) in {document_version_id} is not found by a "
            "literal search for its own text, so it cannot be cited unambiguously"
        )
    return locate(
        document_version_id=document_version_id,
        canonical_text=canonical_text,
        quote=quote,
        occurrence=starts.index(start),
    )


def _page_of(canonical_text: str, offset: int) -> int:
    for page in split_pages(canonical_text):
        if page.contains(offset):
            return page.number
    raise RetrievalError(f"offset {offset} lies outside every page of the canonical text")


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(i + 1 for i, ch in enumerate(text) if ch == "\n")
    return starts


def _best_passage(
    canonical_text: str, lexemes: Sequence[str]
) -> tuple[int, int, tuple[str, ...]] | None:
    """The line of this document that covers the most distinct query terms.

    Passage selection happens here rather than in `ts_headline` because the
    quote has to be text *verbatim from the document*: headline output is
    reassembled from lexemes and can normalise the run-together spacing
    `-layout` produces, at which point the span it implies no longer resolves.
    So Postgres decides which documents and which terms — it owns the analyser —
    and the offsets are computed against the stored text, which is the only
    string a citation is allowed to resolve against.

    Matching is a prefix test against the lexemes Postgres already produced,
    because the English stemmer truncates (`consideration` → `consider`). It
    over-matches slightly — `share` also matches `shareholder` — and that
    direction is deliberate: the consequence is a slightly wider passage, where
    the opposite is a term the ranker counted and the quote does not contain.
    """
    if not lexemes:
        return None
    starts = _line_starts(canonical_text)
    per_line: dict[int, set[str]] = {}
    first_hit: dict[int, int] = {}
    for match in _WORD.finditer(canonical_text):
        word = match.group(0).lower()
        hit = {lex for lex in lexemes if word.startswith(lex)}
        if not hit:
            continue
        line = bisect_right(starts, match.start()) - 1
        per_line.setdefault(line, set()).update(hit)
        first_hit.setdefault(line, match.start())
    if not per_line:
        return None

    line = min(per_line, key=lambda i: (-len(per_line[i]), i))
    start = starts[line]
    end = starts[line + 1] - 1 if line + 1 < len(starts) else len(canonical_text)
    start, end = _trim(canonical_text, start, end)
    if end <= start:
        return None
    if end - start > MAX_PASSAGE_CHARS:
        start, end = _window(canonical_text, first_hit[line], start, end)
    return start, end, tuple(sorted(per_line[line]))


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _window(text: str, around: int, low: int, high: int) -> tuple[int, int]:
    """A `MAX_PASSAGE_CHARS` window around the hit, snapped to whitespace."""
    half = MAX_PASSAGE_CHARS // 2
    start = max(low, around - half)
    end = min(high, start + MAX_PASSAGE_CHARS)
    while start > low and not text[start - 1].isspace():
        start -= 1
    while end < high and not text[end].isspace():
        end += 1
    return _trim(text, start, end)


# ── Measurement ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldCase:
    """One `(holding, requirement, measurement date)` and the documents the
    ledger actually relies on for it.

    The relevance judgement is not written by hand. It is read out of
    `claim_requirement` — the table where the extractor that read a document
    recorded which requirement it is relied upon for — joined to the claim's
    own reliance window. A gold set typed beside the code would be a second
    opinion about what the ledger relies on, and the two would drift.
    """

    holding_id: str
    requirement: RequirementCode
    measurement_date: date
    relevant: frozenset[str]


_GOLD_SQL = """
select c.holding_id, cr.requirement::text, p.period_date, c.document_version_id
  from claim_requirement cr
  join claim c on c.id = cr.claim_id
  join holding h on h.id = c.holding_id
  join reporting_period p on p.fund_id = h.fund_id and p.audit_scope = 'packet'
 where c.applicable_from <= p.period_date
   and (c.applicable_to is null or c.applicable_to >= p.period_date)
 order by 1, 2, 3
"""


def gold_cases(conn: Conn) -> tuple[GoldCase, ...]:
    """Every case with at least one relied-upon document in window.

    Packet periods only (INV-20): a lineage-only period never generates its own
    assessment, so retrieving evidence for one would be measuring a question
    nobody asks.
    """
    grouped: dict[tuple[str, str, date], set[str]] = {}
    for row in conn.execute(_GOLD_SQL).fetchall():
        key = (
            _typed(row[0], str, "holding_id"),
            _typed(row[1], str, "requirement"),
            _typed(row[2], date, "period_date"),
        )
        grouped.setdefault(key, set()).add(_typed(row[3], str, "document_version_id"))
    return tuple(
        GoldCase(
            holding_id=holding_id,
            requirement=RequirementCode(requirement),
            measurement_date=on,
            relevant=frozenset(documents),
        )
        for (holding_id, requirement, on), documents in sorted(grouped.items())
    )


@dataclass(frozen=True)
class Recall:
    """What a retrieval configuration scored, and over what.

    `mean_candidates` is reported beside the recall because without it the
    number is unreadable. Entity-scoped, this corpus leaves about one candidate
    document per case, and a recall of 1.000 over a candidate set of one
    measures the SQL filter rather than the ranker.
    """

    k: int
    cases: int
    any_relevant: int
    all_relevant: int
    mean_candidates: float

    @property
    def recall(self) -> float:
        return self.any_relevant / self.cases if self.cases else 0.0


def recall_at_k(
    conn: Conn,
    cases: Sequence[GoldCase],
    *,
    k: int = K,
    entity_scoped: bool = True,
    apply_window: bool = True,
) -> Recall:
    """Recall@k over the locked gold set. Reports a number; asserts nothing."""
    any_hit = 0
    all_hit = 0
    candidates = 0
    for case in cases:
        passages = retrieve(
            conn,
            holding_id=case.holding_id if entity_scoped else None,
            measurement_date=case.measurement_date,
            requirement=case.requirement,
            k=k,
            apply_window=apply_window,
        )
        documents = {p.candidate.document_version_id for p in passages}
        candidates += len(documents)
        if case.relevant & documents:
            any_hit += 1
        if case.relevant <= documents:
            all_hit += 1
    return Recall(
        k=k,
        cases=len(cases),
        any_relevant=any_hit,
        all_relevant=all_hit,
        mean_candidates=candidates / len(cases) if cases else 0.0,
    )


def measured_query_cost(conn: Conn, *, repeats: int = 20) -> float:
    """Mean wall-clock seconds for one retrieval query, round trip included.

    The reason there is no `tsvector` migration. Compare this against the same
    connection's round-trip floor: if the difference is not the cost of the
    scan, an index cannot recover it.
    """
    query = GOLD_QUERIES[RequirementCode.R2]
    began = time.perf_counter()
    for _ in range(repeats):
        conn.execute(
            _CANDIDATES_SQL,
            {
                "query": query,
                "holding_id": None,
                "on": date(2025, 12, 31),
                "apply_window": True,
                #: Unscoped, because this measures the SCAN. Adding the
                #: requirement filter here would time a narrower query and
                #: report the corpus as cheaper than the product's own path.
                "scoped": False,
                "requirement": RequirementCode.R2.value,
                "source_classes": None,
            },
        ).fetchall()
    return (time.perf_counter() - began) / repeats
