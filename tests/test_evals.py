"""`GET /evals` · that the numbers are measured, and measured of the right thing.

Handoff 7a's acceptance criteria, as tests. The sharp one is the third:

* every count can be reproduced by a command a reader can run;
* changing a reliance judgement changes the page, without editing the page;
* the numbers come from the ledger being READ, not from a previous run;
* the page renders honestly when the API is unreachable.

The last is a browser test and lives in `web/src/Evals.test.tsx`.

The third is what catches a page of transcribed literals, and it is proved by
falsification rather than by mutation: the same code is pointed at a migrated but
EMPTY schema, and every count collapses. A transcribed page reports the same
figures against an empty database, and this is the only assertion in the file
that could tell the difference. Nothing is written and nothing is rolled back,
so it cannot wedge the shared schema the way a corpus mutation could.

Read-only against `demo`, in the pattern `tests/test_retrieval.py` established:
this measures a ledger it does not own, so the guarantee comes from the session
rather than from care.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from api.evals import MEASURED_K, REPORTED_K, evals
from evidence.retrieve import gold_cases, recall_at_k
from packages.contracts.models import Packet
from policy.from_ledger import load as load_policy
from policy.inputs import Ledger
from tests.conftest import PACKET_PERIODS
from tests.schema_helpers import DSN, Conn

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")


@pytest.fixture(scope="module")
def demo() -> Iterator[Conn]:
    """The loaded fund, read-only.

    `prepare_threshold=None` mirrors `api/routes.py:_connect()` — Supabase's
    pooler is transaction-mode, and this fixture runs the same retrieval query
    eighty times. `default_transaction_read_only` because `demo` is the deployed
    data and belongs to whoever reloads it.
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


def _built(conn: Conn) -> tuple[Ledger, dict[str, Packet]]:
    from api import ledger as api_ledger

    packets = {
        period_id: packet
        for fund_id, period_id in PACKET_PERIODS
        if (packet := api_ledger.packet(conn, fund_id, period_id)) is not None
    }
    return load_policy(conn), packets


@pytest.fixture(scope="module")
def measured(demo: Conn) -> dict[str, Any]:
    ledger, packets = _built(demo)
    return evals(demo, ledger, packets, measured_at=datetime(2026, 7, 27, tzinfo=UTC))


# ── The numbers are the ledger's ─────────────────────────────────────────


def test_the_recall_the_page_reports_is_the_recall_the_reference_reports(
    demo: Conn, measured: dict[str, Any]
) -> None:
    """The route runs ONE retrieval per case at the largest cutoff and reads the
    smaller cutoffs off its prefix, because `retrieve` sorts the whole candidate
    list and returns `passages[:k]`. That is an optimisation, and one that
    quietly reported a different number from the reference implementation would
    be worse than the queries it saves.

    So it is checked against `evidence.retrieve.recall_at_k`, which runs the
    retrieval separately for each k. A ranking change that broke the prefix
    property goes red here rather than making this page disagree with the suite.
    """
    cases = gold_cases(demo)
    for scope, entity_scoped in (("scoped", True), ("blind", False)):
        for k in REPORTED_K:
            reference = recall_at_k(demo, cases, k=k, entity_scoped=entity_scoped)
            reported = measured["retrieval"][scope][f"k{k}"]
            assert reported["found_some_relied_on"] == reference.any_relevant, (scope, k)
            assert reported["found_every_relied_on"] == reference.all_relevant, (scope, k)
            assert reported["cases"] == reference.cases == len(cases)


def test_the_blind_figure_is_worse_than_the_scoped_one_and_both_are_reported(
    measured: dict[str, Any],
) -> None:
    """The condition that makes the page worth serving at all.

    A page showing only the entity-scoped number reports the SQL filter as if it
    were the ranker. Asserted as a RELATIONSHIP rather than as two literals: two
    fixed numbers would need editing every time the corpus moved, and the first
    person to edit them would make the page agree with itself again.
    """
    scoped = measured["retrieval"]["scoped"][f"k{MEASURED_K}"]
    blind = measured["retrieval"]["blind"][f"k{MEASURED_K}"]
    assert blind["found_some_relied_on"] < scoped["found_some_relied_on"]
    # And the reason the scoped number says so little: the filter leaves about
    # one candidate per case, so it is scoring the filter.
    assert scoped["candidate_documents"] < blind["candidate_documents"]


def test_every_miss_is_named_and_not_merely_counted(measured: dict[str, Any]) -> None:
    """ "Recall@1 is 39/40" is a score. "The miss is Lucra's existence-and-cost at
    25Q4" is a finding, and it is worth more than the score."""
    misses = measured["retrieval"]["misses"]
    scoped_k1 = [m for m in misses if m["scope"] == "scoped" and m["k"] == 1]
    reported = measured["retrieval"]["scoped"]["k1"]
    assert len(scoped_k1) == reported["cases"] - reported["found_some_relied_on"]
    for miss in misses:
        assert miss["relied_on"], "a case with nothing relied upon is not a gold case"
        assert set(miss["relied_on"]).isdisjoint(miss["retrieved"])
        assert miss["company_name"] and miss["measurement_date"]


def test_the_citation_census_is_measured_against_the_stored_text(
    demo: Conn, measured: dict[str, Any]
) -> None:
    """A constraint existing and the rows satisfying it NOW are different
    statements, and a migration applied to one schema and not another is exactly
    how the two come apart."""
    row = demo.execute("select count(*) from extracted_fact").fetchone()
    assert row is not None
    assert measured["citations"]["total"] == row[0]
    assert measured["citations"]["resolving"] == measured["citations"]["total"]
    assert measured["citations"]["failures"] == []


def test_the_extraction_figures_come_from_a_replay_and_name_the_refusals(
    measured: dict[str, Any],
) -> None:
    """The model proposed five figures and the citation binding accepted three.

    The refusal that matters is the price the claim is priced from: the quoted
    passage ends in a comma, so the value could not be read as a whole figure
    inside it. That is the guardrail firing — a result rather than a fault — and
    it is on the page with its reason.
    """
    extraction = measured["extraction"]
    assert extraction["measured"], extraction.get("why")
    assert extraction["replayed_from_recording"] is True
    assert extraction["proposed"] > extraction["accepted"]
    refused = {r["field_name"] for r in extraction["refused"]}
    assert "price_per_share" in refused
    for refusal in extraction["refused"]:
        assert refusal["reason"], "a refusal with no reason reads as a dropped fact"


def test_the_validator_census_is_a_census_and_never_a_pass_rate(
    measured: dict[str, Any],
) -> None:
    """SPEC §8's six outcomes are unordered, so one ratio over them would be a
    number with no meaning: `not_comparable` is not a soft fail."""
    census = measured["validators"]
    assert sum(census["outcomes"].values()) == census["holding_dates"]
    assert {"pass", "fail", "unconfirmable"} <= set(census["outcomes"])
    assert census["disagreements"], "the known disagreements must be named"
    for row in census["disagreements"]:
        assert row["reported"]["currency"] == row["derived"]["currency"]
        assert row["company_name"] and row["measurement_date"]


def test_the_worst_holding_is_on_the_page_rather_than_hidden(
    measured: dict[str, Any],
) -> None:
    """Because Market: one of fourteen positions, three measurement dates, no
    document of any kind. A page that buried its worst row is a page a reader
    should discount entirely."""
    rows = {r["company_name"]: r for r in measured["by_holding"]}
    assert len(rows) == measured["corpus"]["holdings"]
    worst = rows["Because Market"]
    assert worst["documents"] == worst["claims"] == worst["facts"] == 0
    assert worst["requirements_sufficient"] == 0
    assert worst["packet_appearances"] > 0


def test_the_page_states_what_it_does_not_measure(measured: dict[str, Any]) -> None:
    """The block that decides whether a reader believes the rest.

    Two entries are load-bearing and are asserted by name: nothing here measures
    whether a resolving citation is the RIGHT passage, and nothing compares the
    product against the oracle — because the product is not permitted to see its
    own answer key, which is a guard rather than an omission.
    """
    spots = measured["not_measured"]
    assert len(spots) >= 4
    for spot in spots:
        assert spot["what"] and spot["why"] and spot["measured_by"]
    said = " ".join(spot["what"] for spot in spots).lower()
    assert "right passage" in said
    assert "oracle" in said


def test_the_page_never_reports_a_rate_without_its_two_counts(
    measured: dict[str, Any],
) -> None:
    """A count is auditable; a percentage is a conclusion. The one division on
    the whole response travels with both of its counts."""
    for scope in ("scoped", "blind"):
        for k in REPORTED_K:
            row = measured["retrieval"][scope][f"k{k}"]
            assert row["cases"] > 0
            assert row["mean_candidates_per_case"] * row["cases"] == pytest.approx(
                row["candidate_documents"]
            )


# ── The criterion that catches a transcribed page ────────────────────────


def test_the_figures_are_a_read_of_whichever_ledger_is_pointed_at(
    conn: Conn, measured: dict[str, Any]
) -> None:
    """7a · "Deleting a document from the corpus lowers a number, rather than the
    page reporting the same figure from a cache."

    Proved by falsification, and without mutating a corpus. The same functions
    are pointed at `public` — a different schema holding a different, much
    smaller graph — and asked the same questions. A page whose figures were
    transcribed, cached, or read from a previous run would report the FUND's
    numbers against a schema that does not hold the fund.

    Not asserted as zero. `public` is not empty and is not supposed to be: the
    one schema test that must COMMIT to fire its deferred triggers leaves its
    graph behind, and `ingest/policy_seed.py` says as much in its own comment.
    Asserting emptiness here would make this test depend on what ran before it,
    which is the kind of assertion that goes green for the wrong reason.

    So each count is checked against an independent SQL count of the SAME
    schema — that is what proves it is a read — and then against the fund's
    figures, which it must not equal.
    """
    empty = evals(conn, *_built(conn))
    counted = conn.execute(
        "select (select count(*) from holding), (select count(*) from document_version),"
        " (select count(*) from extracted_fact)"
    ).fetchone()
    assert counted is not None
    assert empty["corpus"]["holdings"] == counted[0]
    assert empty["corpus"]["documents"] == counted[1]
    assert empty["corpus"]["facts"] == counted[2]
    assert len(empty["by_holding"]) == counted[0]

    # And the two readings are not the same reading. A constant would be.
    #
    # Asserted on the READING as a whole, not field by field. Field by field
    # demanded that EVERY count differ, and `public` is not a fixed graph: the
    # schema test that must COMMIT leaves rows behind, so its document count
    # climbs about two per suite run. The fund holds twenty. So the count had to
    # pass through twenty eventually, and on the run where it did this test
    # failed once and then never again — a time bomb with a single fuse, armed
    # by an assertion stronger than the property it was defending.
    #
    # Coincidental equality on one count is not a cache. A cached or transcribed
    # page would report the fund's figures for EVERY field, which is what this
    # compares now. The proof that these are reads is the block above, where
    # each count is checked against an independent SQL count of the same schema.
    def reading(page: dict[str, Any]) -> tuple[int, ...]:
        return (
            page["corpus"]["facts"],
            page["corpus"]["documents"],
            page["retrieval"]["gold_cases"],
            page["citations"]["total"],
            page["validators"]["holding_dates"],
        )

    assert reading(empty) != reading(measured)

    # The blind spots are a property of the SYSTEM rather than of the data, so
    # they are reported whatever the ledger holds. A page that lost its own
    # caveats when the data changed would be claiming more the less it knew.
    assert empty["not_measured"] == measured["not_measured"]
    conn.rollback()


def test_changing_a_reliance_judgement_changes_the_page(conn: Conn, seed: dict[str, str]) -> None:
    """7a · "Changing a reliance judgement changes the page, without editing the
    page."

    The gold set is READ from `claim_requirement` — the table where the extractor
    that read a document recorded which requirement it is relied upon for. A gold
    set typed beside the code would be a second opinion about what the ledger
    relies on, and the two would drift; this is what proves it is not one.

    Seeded rather than run against the corpus, because the property is about the
    JOIN and not about the fund: unbind the judgement, lose the case.
    """
    conn.execute(
        "insert into claim_requirement (claim_id, requirement) values (%s, 'R2')",
        (seed["cl"],),
    )
    with_judgement = evals(conn, *_built(conn))
    assert with_judgement["retrieval"]["gold_cases"] == 1

    conn.execute("delete from claim_requirement where claim_id = %s", (seed["cl"],))
    without = evals(conn, *_built(conn))
    assert without["retrieval"]["gold_cases"] == 0
    conn.rollback()
