"""Every document in the corpus reaches the ledger, and nothing is silently missed.

The first version of `SOURCES` covered nineteen of the corpus's twenty documents.
The Mom Project's term sheet was omitted when the extractor work was split four
ways, and nothing noticed: `fund_i_the_mom_project` simply carried no claims.

In the data that is indistinguishable from Because Market, which carries none
because the fund genuinely holds no document for it. **Those are opposite facts.**
One is "the evidence does not exist", which is the finding the audit letter most
needs; the other is "we did not look", which is a bug wearing the same clothes.

So the first test here is a set difference against the filesystem, and it is the
only guard in the project that can notice a document nobody wrote code for.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from ingest.documents.load import CORPUS, SOURCES, ingest
from tests.schema_helpers import DSN, Conn

needs_corpus = pytest.mark.skipif(
    not CORPUS.exists(), reason="case-study documents are not in the repository"
)

#: `pdftotext` and the plain-text reader are the two pinned extractors, so these
#: are the suffixes a document can arrive as. A new suffix is a deliberate act
#: (`parse()` refuses anything else), and it will show up here as an uncovered
#: file rather than as silence.
READABLE = {".pdf", ".txt"}


@needs_corpus
def test_every_document_in_the_corpus_has_a_reader() -> None:
    """The guard that would have caught The Mom Project on the day it was missed."""
    on_disk = {p for p in CORPUS.rglob("*") if p.suffix.lower() in READABLE and p.is_file()}
    covered = {s.path for s in SOURCES}
    missing = sorted(str(p.relative_to(CORPUS)) for p in on_disk - covered)
    assert missing == [], (
        f"{len(missing)} document(s) in the corpus that nothing reads. A holding with no "
        f"claims then means 'we did not look', which renders identically to 'no evidence "
        f"exists' — the one distinction the packet must never lose: {missing}"
    )


@needs_corpus
def test_no_source_points_at_a_document_that_is_not_there() -> None:
    """The other direction. A path typo produces a source that silently never
    ingests, and the count of documents would still look plausible."""
    absent = sorted(str(s.path) for s in SOURCES if not s.path.exists())
    assert absent == []


@needs_corpus
def test_every_holding_named_is_one_the_ledger_could_hold() -> None:
    """Holding ids are written by hand here — the one place a document is bound
    to a position — so a typo would attach a company's evidence to nothing, and
    the insert would fail at ingest time rather than at review time."""
    for source in SOURCES:
        assert source.holding_id.startswith(("fund_i_", "fund_ii_")), source


@needs_corpus
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_whole_corpus_ingests_with_every_citation_resolving(conn: Conn) -> None:
    """Both workbooks and all twenty documents, in one transaction, rolled back.

    The fund is loaded first because the documents attach to its real holdings —
    rebinding them all to one seeded holding instead made Dream's and
    Fluidstack's `series_b_pro_forma` claims collide on `holding_id:claim_key`,
    which is a fact about the test, not about the corpus: in the ledger they sit
    on different holdings and cannot collide.

    Each document is reported separately, so this asserts the complete list of
    failures is empty rather than that the first one worked.
    """
    import psycopg

    from ingest.load import persist
    from tests.test_real_data_end_to_end import _mapped

    # The explicit outer block is load-bearing, not decoration. psycopg's
    # OUTERMOST `transaction()` COMMITS on exit and only a nested one is a
    # savepoint, so `persist()` — which opens one per row — writes the whole
    # fund permanently unless something is already open around it. Without this
    # the run left 2 funds, 14 holdings and 72 marks behind and broke
    # `test_real_data_ledger`, which asserts the database refuses nothing about
    # a corpus it has not already been given.
    try:
        with conn.transaction() as outer:
            _landed, refused = persist(conn, _mapped())
            assert refused == [], refused

            results = ingest(conn)
            failures = [f"{r.path.name}: {r.error}" for r in results if r.error]
            assert failures == []
            assert len(results) == len(SOURCES)
            assert sum(r.claims for r in results) >= len(SOURCES)
            # A document that parsed and produced no facts is a pattern that
            # stopped matching — the quiet way an extractor dies while still
            # reporting success.
            assert all(r.facts > 0 for r in results), [r.path.name for r in results if not r.facts]
            raise psycopg.Rollback(outer)
    except psycopg.Rollback:
        pass


@needs_corpus
def test_a_source_whose_file_is_absent_is_reported_not_raised(tmp_path: Path) -> None:
    """An ingestion run must survive a missing file and say which one. Raising
    would abandon the other nineteen documents over one bad path."""
    ghost = type(SOURCES[0])(
        path=tmp_path / "nope.pdf", holding_id="fund_ii_dream", build=SOURCES[0].build
    )
    outcomes = ingest(cast(Conn, _NoConn()), [ghost])
    assert len(outcomes) == 1
    assert outcomes[0].error == "not in the corpus"


class _NoConn:
    """A connection the missing-file path must never reach."""

    def transaction(self) -> object:  # pragma: no cover - reaching this is the failure
        raise AssertionError("a missing file must be reported before any database work")


def _fact_count() -> int:
    """Counted on its own connection, so the caller's open transaction cannot
    hide a commit that really happened."""
    import psycopg

    assert DSN is not None
    with psycopg.connect(DSN, connect_timeout=30) as probe:
        probe.execute("set search_path to public")
        row = probe.execute("select count(*) from extracted_fact").fetchone()
        assert row is not None
        return int(str(row[0]))


@needs_corpus
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_a_dry_run_writes_nothing() -> None:
    """The regression test for a bug this project has now shipped twice.

    psycopg's outermost `transaction()` block COMMITS on exit, and both loaders
    open one per row or per document. Without an explicit outer block, `--commit`
    was decorative: the dry run wrote everything, and the real run then failed on
    duplicate keys against its own output. Counting either side of a dry run is
    the only assertion that can tell the difference, because the dry run's own
    report looked correct both before and after the fix.
    """
    from ingest.documents.load import main

    before = _fact_count()
    main(["--schema", "public"])
    assert _fact_count() == before


@needs_corpus
@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_tracker_loader_dry_run_also_writes_nothing() -> None:
    """The same defect lived in `ingest/load.py`, from the same cause — code
    lifted out of a test fixture that used to supply the outer transaction."""
    import psycopg

    from ingest.load import main as load_main

    assert DSN is not None

    def holdings() -> int:
        with psycopg.connect(DSN, connect_timeout=30) as probe:
            probe.execute("set search_path to public")
            row = probe.execute("select count(*) from holding").fetchone()
            assert row is not None
            return int(str(row[0]))

    before = holdings()
    load_main(["--schema", "public"])
    assert holdings() == before


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
@pytest.mark.parametrize("schema", ["public; drop schema demo", "de mo", "demo'", ""])
def test_a_schema_name_that_is_not_an_identifier_is_refused(schema: str) -> None:
    """The schema is interpolated, not parameterised — `set search_path to %s`
    quotes it as a string literal and silently selects nothing, so it has to be
    formatted in. That makes the identifier check the only thing standing
    between a command-line argument and executed SQL."""
    from ingest.documents.load import main as docs_main
    from ingest.load import main as load_main

    assert docs_main(["--schema", schema]) == 1
    assert load_main(["--schema", schema]) == 1


def test_the_tracker_loader_reports_absent_workbooks_rather_than_raising(
    tmp_path: Path,
) -> None:
    """The workbooks are private and absent in CI. A loader that raised would
    turn a documented condition into a stack trace."""
    from ingest.load import main as load_main

    assert load_main(["--trackers", str(tmp_path / "nowhere")]) == 1
