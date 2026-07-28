"""Retrieval — SPEC §10 layers 1 and 2, and what the measurement actually says.

Split the way the extractor suites are, because *a guard that skips where the
case-study material is private has not failed*:

* passage selection, citation binding and the rerank tuple are proved on
  synthetic text and synthetic candidates, and run anywhere;
* the SQL layer is proved against the seeded `public` schema, inside the
  transaction `conftest.conn` rolls back;
* Recall@K is measured against the real corpus in `demo`, read-only, and skips
  where the fund's documents have not been loaded.

The recall numbers below are **recorded measurements, not targets**. The
important one is not `1.000`: entity-scoped retrieval over this corpus leaves a
mean of 1.12 candidate documents per case, so a perfect score there is a
statement about the SQL filter and says nothing about the ranker. The number
that carries information is the one with the entity filter removed — 24/40 at
K=5 — because that is the question layer 1 is answering.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from evidence.retrieve import (
    _CANDIDATES_SQL,
    GOLD_QUERIES,
    MAX_PASSAGE_CHARS,
    PREFERENCE,
    Candidate,
    K,
    RetrievalError,
    _best_passage,
    _cite,
    _preference,
    _rank_key,
    _typed,
    default_query,
    gold_cases,
    measured_query_cost,
    recall_at_k,
    retrieve,
)
from packages.contracts.citations import CitationError, locate
from packages.contracts.enums import ExecutionStatus, RequirementCode, SourceClass
from tests.schema_helpers import DSN, SEED_TEXT, Conn

# ── Passage selection, on synthetic text ─────────────────────────────────

_MEMO = (
    "ACME, INC. — Valuation Memorandum\n"
    "Prepared December 31, 2030.\n"
    "The Series C Preferred Stock was issued at $8.00 per share.\n"
    "Signature page follows.\n"
)


def test_the_passage_is_the_line_that_covers_the_most_query_terms() -> None:
    found = _best_passage(_MEMO, ("price", "per", "share", "issu"))
    assert found is not None
    start, end, matched = found
    assert _MEMO[start:end] == "The Series C Preferred Stock was issued at $8.00 per share."
    assert matched == ("issu", "per", "share")


def test_a_passage_is_a_verbatim_slice_so_its_span_resolves() -> None:
    found = _best_passage(_MEMO, ("issu",))
    assert found is not None
    start, end, _ = found
    citation = _cite("dv_x", _MEMO, start, end)
    assert _MEMO[citation.span_start : citation.span_end] == citation.quote


def test_no_lexemes_is_no_passage_rather_than_the_first_line() -> None:
    assert _best_passage(_MEMO, ()) is None
    assert _best_passage(_MEMO, ("nothinghere",)) is None


def test_a_long_line_is_windowed_around_the_hit() -> None:
    """`-layout` writes a cap-table row as one line hundreds of characters wide."""
    row = "x " * 400 + "issued at $8.00 per share " + "y " * 400
    found = _best_passage(row, ("issu",))
    assert found is not None
    start, end, _ = found
    assert end - start <= MAX_PASSAGE_CHARS + 2
    assert "issued at $8.00 per share" in row[start:end]


def test_a_repeated_line_is_cited_at_the_occurrence_it_came_from() -> None:
    """The one place an index into a list of matches is the honest answer.

    `locate()` refuses an ambiguous quote because a human quoting a passage
    should quote more of it. Here the passage is a slice at a known offset, so
    "the second identical line" is exactly what is meant — and the citation has
    to land on that one rather than on the first.
    """
    line = "issued at $8.00 per share"
    doubled = f"{line}\n" * 2
    second = doubled.index(line, 1)
    assert _cite("dv_x", doubled, 0, len(line)).span_start == 0
    assert _cite("dv_x", doubled, second, second + len(line)).span_start == second
    with pytest.raises(CitationError, match="occurs 2 times"):
        # The same quote with no occurrence named is genuinely ambiguous, which
        # is what makes naming one deliberate rather than incidental.
        locate(document_version_id="dv_x", canonical_text=doubled, quote=line)


def test_a_passage_that_cannot_name_its_own_occurrence_is_refused() -> None:
    """Fail closed where a literal search cannot find the slice at its own offset.

    `re.finditer` does not return overlapping matches, so the span [1, 3) of
    `"aaaa"` holds text the scan reports only at 0 and 2. There is no honest
    occurrence index for it, and guessing the nearest one would attach a
    resolving span to a passage nobody selected.
    """
    with pytest.raises(RetrievalError, match="cannot be cited unambiguously"):
        _cite("dv_x", "aaaa", 1, 3)


# ── The rerank tuple ─────────────────────────────────────────────────────


def _candidate(
    source_class: SourceClass,
    execution_status: ExecutionStatus,
    *,
    issued: date = date(2025, 1, 1),
    rank: float = 0.0,
    document: str = "dv_a",
) -> Candidate:
    return Candidate(
        claim_id="c",
        holding_id="h",
        claim_key="k",
        document_version_id=document,
        filename="f.pdf",
        source_class=source_class,
        execution_status=execution_status,
        issued_date=issued,
        applicable_from=issued,
        applicable_to=None,
        text_rank=rank,
    )


def test_no_text_rank_promotes_press_above_an_executed_document() -> None:
    """INV-1 · the rank is a tuple, so element 3 cannot outvote element 1.

    This is the test a weighted score fails. Give the press article the highest
    possible full-text rank and the executed agreement the lowest, and put the
    press article on the measurement date itself: under any sum of weighted
    dimensions there is a weight at which press wins, and there is none here.
    """
    on = date(2025, 12, 31)
    press = _rank_key(
        _candidate(SourceClass.PRESS, ExecutionStatus.NOT_APPLICABLE, issued=on, rank=1.0),
        on,
        0,
    )
    executed = _rank_key(
        _candidate(
            SourceClass.EXECUTED_TRANSACTION_DOC,
            ExecutionStatus.EXECUTED,
            issued=date(2015, 1, 1),
            rank=0.0,
        ),
        on,
        0,
    )
    assert executed < press


def test_an_unenumerated_pair_sorts_where_press_does() -> None:
    """Fail closed: a combination nobody has ruled on is not quietly promoted."""
    assert _preference(SourceClass.PRESS, ExecutionStatus.NOT_APPLICABLE) == len(PREFERENCE)
    assert _preference(SourceClass.RUMOR, ExecutionStatus.NOT_APPLICABLE) == len(PREFERENCE)
    assert _preference(SourceClass.COMPANY_CAP_TABLE, ExecutionStatus.EXECUTED) == len(PREFERENCE)


def test_the_preference_list_names_each_pair_once() -> None:
    assert len(set(PREFERENCE)) == len(PREFERENCE)


def test_the_closer_measurement_date_wins_within_one_pair() -> None:
    on = date(2025, 12, 31)
    pair = (SourceClass.ADMINISTRATOR_STATEMENT, ExecutionStatus.NOT_APPLICABLE)
    near = _rank_key(_candidate(*pair, issued=date(2025, 12, 31)), on, 0)
    far = _rank_key(_candidate(*pair, issued=date(2023, 12, 31)), on, 0)
    assert near < far


def test_the_tie_break_is_declared_all_the_way_down() -> None:
    """SPEC §10 · "deterministic ordering with a declared tie-break"."""
    on = date(2025, 12, 31)
    pair = (SourceClass.PUBLIC_MARKET_QUOTE, ExecutionStatus.NOT_APPLICABLE)
    first = _rank_key(_candidate(*pair, document="dv_a"), on, 10)
    second = _rank_key(_candidate(*pair, document="dv_b"), on, 10)
    same_document = _rank_key(_candidate(*pair, document="dv_a"), on, 99)
    assert first < second
    assert first < same_document


def test_a_requirement_no_document_answers_is_refused() -> None:
    """0010's `claim_requirement_is_evidence_bearing`, restated where it bites."""
    assert default_query(RequirementCode.R2)
    for code in (RequirementCode.R3, RequirementCode.R5):
        with pytest.raises(RetrievalError, match="not evidence-bearing"):
            default_query(code)


# ── The SQL layer, against the seeded schema ─────────────────────────────

needs_db = pytest.mark.skipif(DSN is None, reason="no MIGRATION_DATABASE_URL")

_SEED_QUERY = "preferred stock issued per share"


@needs_db
def test_the_seeded_claim_is_retrieved_with_a_citation_that_resolves(
    conn: Conn, seed: dict[str, str]
) -> None:
    found = retrieve(
        conn,
        holding_id=seed["h"],
        measurement_date=date(2025, 12, 31),
        requirement=RequirementCode.R2,
        query=_SEED_QUERY,
    )
    assert [p.candidate.claim_id for p in found] == [seed["cl"]]
    passage = found[0]
    assert passage.page == 1
    assert SEED_TEXT[passage.citation.span_start : passage.citation.span_end] == (
        passage.citation.quote
    )
    assert "$8.00 per share" in passage.citation.quote


@needs_db
def test_a_date_outside_the_claims_own_reliance_window_retrieves_nothing(
    conn: Conn, seed: dict[str, str]
) -> None:
    """INV-16 · the source states its own window, and it is a filter, not a hint."""
    assert (
        retrieve(
            conn,
            holding_id=seed["h"],
            measurement_date=date(2027, 1, 1),
            requirement=RequirementCode.R2,
            query=_SEED_QUERY,
        )
        == ()
    )


@needs_db
def test_another_holdings_document_is_not_weak_evidence_it_is_no_evidence(
    conn: Conn, seed: dict[str, str]
) -> None:
    assert (
        retrieve(
            conn,
            holding_id=seed["h"] + "_other",
            measurement_date=date(2025, 12, 31),
            requirement=RequirementCode.R2,
            query=_SEED_QUERY,
        )
        == ()
    )


@needs_db
def test_the_source_class_filter_is_a_filter(conn: Conn, seed: dict[str, str]) -> None:
    assert (
        retrieve(
            conn,
            holding_id=seed["h"],
            measurement_date=date(2025, 12, 31),
            requirement=RequirementCode.R2,
            query=_SEED_QUERY,
            source_classes=[SourceClass.PUBLIC_MARKET_QUOTE],
        )
        == ()
    )


@needs_db
def test_a_query_of_only_stop_words_is_a_caller_bug_not_an_empty_corpus(
    conn: Conn, seed: dict[str, str]
) -> None:
    with pytest.raises(RetrievalError, match="reduces to no search terms"):
        retrieve(
            conn,
            holding_id=seed["h"],
            measurement_date=date(2025, 12, 31),
            requirement=RequirementCode.R2,
            query="the of and",
        )


# ── Recall, against the real corpus ──────────────────────────────────────


@pytest.fixture(scope="module")
def demo() -> Iterator[Conn]:
    """The loaded fund, read-only.

    `prepare_threshold=None` mirrors `api/routes.py:_connect()`. Supabase's
    pooler is transaction-mode, so psycopg preparing a statement after its fifth
    execution is a `DuplicatePreparedStatement` on the next backend session —
    and `recall_at_k` runs the same query 120 times.

    `default_transaction_read_only` because this connection is measuring a
    ledger it does not own. Nothing here rolls back, so the guarantee has to
    come from the session rather than from care.
    """
    if DSN is None:
        pytest.skip("no MIGRATION_DATABASE_URL")
    connection = psycopg.connect(DSN, connect_timeout=30, prepare_threshold=None)
    try:
        connection.execute("set search_path to demo")
        connection.execute("set default_transaction_read_only = on")
        if not gold_cases(connection):
            pytest.skip("the `demo` schema holds no loaded corpus")
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_the_gold_set_is_read_from_the_ledgers_own_reliance_records(demo: Conn) -> None:
    """The relevance judgement is `claim_requirement`, not a table typed here.

    Forty `(holding, requirement, packet date)` cases across twelve holdings.
    Two of the fourteen positions appear in none: Because Market, which has no
    document of any kind, and Sway, whose recapitalisation table falls outside
    every packet date's reliance window. Both absences are findings about the
    fund rather than gaps in the measurement.
    """
    cases = gold_cases(demo)
    assert len(cases) == 40
    assert len({c.holding_id for c in cases}) == 12
    assert all(c.relevant for c in cases)
    assert {c.requirement for c in cases} == {
        RequirementCode.R1,
        RequirementCode.R2,
        RequirementCode.R4,
    }


def test_every_pair_the_corpus_exercises_is_ranked_deliberately(demo: Conn) -> None:
    """An unruled pair must be a red test, not a silent demotion to last place.

    `press` is excluded on purpose — it is the pair the terminal position is
    *for*. Everything else the corpus contains has to have been placed by
    somebody.
    """
    rows = demo.execute(
        "select distinct source_class::text, execution_status::text from claim"
    ).fetchall()
    exercised = {
        (SourceClass(str(sc)), ExecutionStatus(str(es)))
        for sc, es in rows
        if SourceClass(str(sc)) not in (SourceClass.PRESS, SourceClass.RUMOR)
    }
    assert exercised <= set(PREFERENCE), f"unranked: {sorted(exercised - set(PREFERENCE))}"


def test_recall_at_k_entity_scoped(demo: Conn) -> None:
    """Recorded, and recorded with the number that makes it readable.

    40/40 at K=5 over a mean of 1.12 candidate documents. The score is the SQL
    filter's, not the ranker's, and stating the candidate count beside it is the
    difference between a measurement and a boast.
    """
    cases = gold_cases(demo)
    at_5 = recall_at_k(demo, cases, k=K)
    assert (at_5.any_relevant, at_5.all_relevant, at_5.cases) == (40, 40, 40)
    assert at_5.mean_candidates == pytest.approx(1.125, abs=0.01)

    at_1 = recall_at_k(demo, cases, k=1)
    assert (at_1.any_relevant, at_1.all_relevant) == (39, 36)


def test_the_single_top_one_miss_is_named_rather_than_averaged_away(demo: Conn) -> None:
    """Lucra R1 at 25Q4, and the rerank is not obviously wrong about it.

    The ledger relies on the May 2024 term sheet for existence and cost. The
    rerank puts the October 2025 CEO email first: it is nearer the measurement
    date, and a communication *referencing an executed closing set* is placed
    above a *non-binding* one. Retrieval offers both inside K=3; what it gets
    wrong is only which to read first.

    Named here rather than smoothed into 0.975 because a miss with a reason is
    reviewable and a percentage is not.
    """
    missed = [
        case
        for case in gold_cases(demo)
        if not (
            case.relevant
            & {
                p.candidate.document_version_id
                for p in retrieve(
                    demo,
                    holding_id=case.holding_id,
                    measurement_date=case.measurement_date,
                    requirement=case.requirement,
                    k=1,
                )
            }
        )
    ]
    assert [(c.holding_id, c.requirement, c.measurement_date) for c in missed] == [
        ("fund_ii_lucra", RequirementCode.R1, date(2025, 12, 31))
    ]


def test_removing_the_entity_filter_is_what_the_measurement_is_for(demo: Conn) -> None:
    """24/40 at K=5 without it, against 40/40 with it.

    Retrieval is never run this way — `holding_id` is required in production.
    The configuration exists so the entity filter's contribution is a number
    rather than an assumption, and so nobody reads the 1.000 above as a claim
    about the ranker.
    """
    cases = gold_cases(demo)
    blind = recall_at_k(demo, cases, k=K, entity_scoped=False)
    assert (blind.any_relevant, blind.cases) == (24, 40)
    assert blind.recall < recall_at_k(demo, cases, k=K).recall


def test_dropping_the_reliance_window_costs_precision_not_recall(demo: Conn) -> None:
    """With the window off the ranker must choose among a holding's documents.

    36/40 at K=1 rather than 39/40, and still 40/40 by K=3 — so date proximity
    and the preference order between them recover the right document, they just
    do not always put it first.
    """
    cases = gold_cases(demo)
    at_1 = recall_at_k(demo, cases, k=1, apply_window=False)
    at_3 = recall_at_k(demo, cases, k=3, apply_window=False)
    assert at_1.any_relevant == 36
    assert (at_3.any_relevant, at_3.all_relevant) == (40, 40)


def test_the_scan_is_not_what_costs_the_time_so_no_index_is_built(demo: Conn) -> None:
    """The measurement SPEC §10 asks for before an embedding or tsvector column.

    Twenty documents and 44,365 characters: recomputing `to_tsvector` per row
    per query is 15 ms of SERVER time with every buffer already in cache. A
    generated column and a GIN index recover time spent scanning, and there is
    almost none to recover. This is a guard against the corpus growing by two
    orders of magnitude, not a latency SLA.

    **Measured on the server, not on the clock.** This asserted
    `measured_query_cost(demo) < 20 * floor`, where both sides were client
    wall-clock and `floor` was the mean of twenty `select 1` round trips. It
    failed three runs in five on an unchanged tree, because the DENOMINATOR was
    network jitter: the same floor measured 42 ms on one connection and 285 ms
    on another, so the bound moved by a factor of six while nothing about the
    query changed. A check whose verdict is decided by the noise in its own
    baseline reports the weather.

    Worse, it could not see what it was for. Client cost is ~1 s per query
    against 15 ms of execution; that ~985 ms is real, is not the scan, is not
    the row payload (removing `canonical_text` did not reduce it) and is not
    the pooler mode (session and transaction endpoints measure the same). It is
    unexplained and recorded in the handoff. A wall-clock bound would go red for
    that reason and be read as "the scan got slow", which is the one conclusion
    the evidence rules out.

    So: ask the planner. `EXPLAIN ANALYZE` reports execution independent of the
    network, which is the quantity that decides whether an index would help.
    """
    plan = demo.execute(
        "explain (analyze, buffers, format json) " + _CANDIDATES_SQL,
        {
            "query": GOLD_QUERIES[RequirementCode.R2],
            "holding_id": None,
            "on": date(2025, 12, 31),
            "apply_window": True,
            "scoped": False,
            "requirement": "R2",
            "source_classes": None,
        },
    ).fetchone()
    assert plan is not None
    root = _typed(plan[0], list, "explain output")[0]
    execution_ms = _typed(root, dict, "explain plan")["Execution Time"]

    # 200 ms is two orders of magnitude above the 15 ms this corpus measures,
    # which is exactly the growth this guard exists to notice. It is an absolute
    # server-side bound rather than a ratio, so nothing about the network can
    # move it in either direction.
    # Reported, never asserted on. It is the figure that made the old bound
    # unstable, and printing it beside the server time is what makes the
    # difference between them legible instead of mysterious.
    client_ms = measured_query_cost(demo, repeats=3) * 1000
    assert execution_ms < 200, (
        f"the scan now costs {execution_ms:.1f} ms of server time (client round trip "
        f"{client_ms:.0f} ms). At this point a tsvector column and a GIN index would "
        f"recover real time, and SPEC §10's measurement should be re-taken rather "
        f"than this bound raised."
    )
