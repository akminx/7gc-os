"""`/holdings/{id}/passages` — the route whose answer is the document's words.

Split the way the retrieval suite is. The route's own contract — which of the
four outcomes it reports, and what it puts on the wire — is proved against a
connection that touches no database, because those are decisions this module
makes. Retrieval itself is proved in `test_retrieval.py` and is not re-proved
here; re-asserting the ranker through an HTTP layer would test it worse and
report it twice.

The last test is the one that runs against the loaded fund, and it exists
because everything above it could pass while the route answered nothing real.
"""

from __future__ import annotations

import pathlib
from datetime import date
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import lookup
from api.config import dsn
from evidence.retrieve import Candidate, RetrievalError, RetrievedPassage, retrieve
from packages.contracts.citations import locate
from packages.contracts.enums import ExecutionStatus, RequirementCode, SourceClass

DSN = dsn("MIGRATION_DATABASE_URL")
ROOT = pathlib.Path(__file__).resolve().parents[1]

TEXT = "The Fund holds a EUR-denominated interest in Moonfare GmbH as of the measurement date."
QUOTE = "EUR-denominated interest in Moonfare GmbH"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(lookup.lookup_router)
    return TestClient(app)


class _CountingConn:
    """A connection that answers only the claim-count probe the route makes.

    Returns `(1,)` so the route treats the holding as known; every other call
    would be `retrieve()`, which each test monkeypatches. A fake that answered
    the retrieval SQL too would be a second implementation of the ranker living
    in the test suite.
    """

    def __init__(self, claims: int = 1) -> None:
        self.claims = claims

    def execute(self, *_: object, **__: object) -> _CountingConn:
        return self

    def fetchone(self) -> tuple[int]:
        return (self.claims,)

    def __enter__(self) -> _CountingConn:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _passage() -> RetrievedPassage:
    candidate = Candidate(
        claim_id="fund_ii_moonfare:fy2024_fx_remeasurement",
        holding_id="fund_ii_moonfare",
        claim_key="fy2024_fx_remeasurement",
        document_version_id="dv_test",
        filename="Moonfare - FX Re-measurement Memo - FY2024.pdf",
        source_class=SourceClass.FUND_INTERNAL_RECORD,
        execution_status=ExecutionStatus.NOT_APPLICABLE,
        issued_date=date(2024, 12, 31),
        applicable_from=date(2024, 12, 31),
        applicable_to=None,
        text_rank=0.5,
    )
    return RetrievedPassage(
        candidate=candidate,
        citation=locate(document_version_id="dv_test", canonical_text=TEXT, quote=QUOTE),
        page=1,
        matched=("eur", "moonfar"),
        rank_key=(0, 0, 0.0, "", 0),
    )


def _get(monkeypatch: pytest.MonkeyPatch, conn: object, **params: Any) -> Any:
    monkeypatch.setattr(lookup, "_connect", lambda: conn)
    query = {"on": "2024-12-31", "requirement": "R2", **params}
    return _client().get("/holdings/fund_ii_moonfare/passages", params=query)


def test_a_passage_travels_with_the_offsets_that_make_it_checkable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quote without its span is a sentence the reader has to trust.

    The span is asserted against the text rather than against a recorded
    number: `locate()` computed it, and a test that hard-codes 17 would keep
    passing if the route started sending someone else's offsets.
    """
    monkeypatch.setattr(lookup, "retrieve", lambda *a, **k: (_passage(),))
    body = _get(monkeypatch, _CountingConn()).json()
    (passage,) = body["passages"]
    assert TEXT[passage["span_start"] : passage["span_end"]] == passage["quote"] == QUOTE
    assert passage["page"] == 1
    assert passage["filename"].startswith("Moonfare")
    assert passage["matched"] == ["eur", "moonfar"]


def test_a_corpus_that_addresses_this_nowhere_says_so_rather_than_returning_a_bare_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`outcome` is the field that keeps an empty pane from reading as a bug.

    An empty `passages` array is indistinguishable from a component that failed
    to load, and this route can produce an empty array for a reason that is a
    real answer.
    """
    monkeypatch.setattr(lookup, "retrieve", lambda *a, **k: ())
    body = _get(monkeypatch, _CountingConn(), q="zebra submarine cricket").json()
    assert body["outcome"] == "none_matched"
    assert body["passages"] == []


def test_a_holding_the_ledger_does_not_hold_is_a_404_not_an_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "No passage for that question" and "no such position" are different.

    Rendered identically, a typo in a holding id reads as a corpus that holds
    nothing about a position the fund owns.
    """
    monkeypatch.setattr(lookup, "retrieve", lambda *a, **k: (_passage(),))
    response = _get(monkeypatch, _CountingConn(claims=0))
    assert response.status_code == 404
    assert "no claims are recorded" in response.json()["detail"]


def test_a_query_that_reduces_to_no_search_terms_is_refused_not_answered_emptily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retrieval's own refusal is carried out to the caller as a 422.

    A stopword-only question matches nothing whatever the corpus holds, and
    reporting that as `none_matched` would tell the reader the fund has no
    document on a subject they never managed to ask about.
    """

    def refuse(*_: object, **__: object) -> tuple[RetrievedPassage, ...]:
        raise RetrievalError("the query 'the of and' reduces to no search terms")

    monkeypatch.setattr(lookup, "retrieve", refuse)
    response = _get(monkeypatch, _CountingConn(), q="the of and")
    assert response.status_code == 422
    assert "no search terms" in response.json()["detail"]


def test_the_query_that_ran_is_echoed_so_silence_is_not_read_as_a_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`supplied` distinguishes the reader's words from the requirement's default.

    `retrieve()` substitutes `default_query(requirement)` for a missing query,
    and a pane that showed that text back without saying where it came from
    would attribute the system's question to the reader.
    """
    monkeypatch.setattr(lookup, "retrieve", lambda *a, **k: (_passage(),))
    asked = _get(monkeypatch, _CountingConn(), q="euro denomination").json()["query"]
    assert asked == {
        "text": "euro denomination",
        "supplied": True,
        "requirement": "R2",
        "on": "2024-12-31",
    }
    silent = _get(monkeypatch, _CountingConn()).json()["query"]
    assert silent["supplied"] is False
    assert silent["text"] and silent["text"] != "euro denomination"


def test_without_a_ledger_the_route_refuses_rather_than_answering_from_a_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every read route falls back to the Dream fixture. This one must not.

    A fixture answer here is a PASSAGE — a quotation attributed to a document,
    with a page and a span — and inventing one is the exact failure the
    citation machinery exists to prevent. The other routes fall back to a
    figure the response labels `fixture`; there is no honest way to label a
    quotation the fund does not hold.
    """
    response = _get(monkeypatch, None)
    assert response.status_code == 503
    assert "no ledger is configured" in response.json()["detail"].lower()


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_loaded_fund_answers_a_question_asked_in_english() -> None:
    """The one test that would fail if the whole route answered nothing real.

    Read-only against `demo`, and skipped where the fund's documents have not
    been loaded — a guard that skips because the corpus is private has not
    failed. `to_tsvector` stems, so the reader's sentence and the memo's
    wording do not have to agree on grammar.
    """
    assert DSN is not None
    connection = psycopg.connect(DSN, connect_timeout=30, prepare_threshold=None)
    try:
        connection.execute("set search_path to demo")
        connection.execute("set default_transaction_read_only = on")
        row = connection.execute(
            "select count(*) from claim where holding_id = 'fund_ii_moonfare'"
        ).fetchone()
        if row is None or int(row[0]) == 0:
            pytest.skip("the `demo` schema holds no loaded corpus")
        #: Called from `evidence.retrieve`, not through `api.lookup`. The
        #: monkeypatched tests above target `lookup.retrieve` because that is
        #: where the route looks the name up; this one wants the real function,
        #: and reaching it through a re-export is what `no_implicit_reexport`
        #: exists to stop — a module's imports are not its public surface.
        found = retrieve(
            connection,
            holding_id="fund_ii_moonfare",
            measurement_date=date(2024, 12, 31),
            requirement=RequirementCode.R2,
            query="what currency is the interest denominated in",
            k=5,
        )
    finally:
        connection.rollback()
        connection.close()

    assert found, "the corpus states Moonfare's denomination and retrieval found nothing"
    #: Every passage is a verbatim slice of the document it names, which is what
    #: makes the answer checkable rather than merely plausible.
    for passage in found:
        assert passage.citation.quote
        assert passage.citation.span_end > passage.citation.span_start
    assert any("EUR" in p.citation.quote for p in found), (
        "the FX memo states the EUR denomination three times and none was retrieved"
    )


def test_the_explain_route_is_exercised_through_http_not_around_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route had never run: it queried `company.name`, and the column is
    `display_name`. Every request was a 500.

    The first version of THIS test executed the route's SQL by hand and asserted
    the join resolved — which is the same shortcut that hid the bug, wearing a
    test's clothes. Delete `explain_row` entirely and it stayed green.

    So it goes through `TestClient`. `restate` is stubbed because the model is
    not what is under test here; everything between the URL and the payload is.
    """
    monkeypatch.setattr(lookup, "_assistant_is_offered", lambda: True)
    monkeypatch.setattr(lookup, "_connect", lambda: _NamedConn())
    monkeypatch.setattr(lookup, "load_policy", lambda conn: object())
    monkeypatch.setattr(
        lookup,
        "row_payload",
        lambda *a, **k: {"company": "Lucra", "verdict": "insufficient"},
    )
    monkeypatch.setattr(
        lookup,
        "restate",
        lambda payload: SimpleNamespace(
            accepted=True, text="The support is insufficient.", refusal=None, model="stub"
        ),
    )
    app = FastAPI()
    app.include_router(lookup.lookup_router)
    body = TestClient(app).get(
        "/holdings/fund_ii_lucra/explain",
        params={"on": "2024-12-31", "requirement": "R2"},
    )
    assert body.status_code == 200
    payload = body.json()
    assert payload["outcome"] == "explained"
    assert payload["text"] == "The support is insufficient."
    assert payload["row"]["company"] == "Lucra"


class _NamedConn(_CountingConn):
    """A connection whose company lookup answers with a display name."""

    def fetchone(self) -> tuple[Any]:
        return ("Lucra",)


def test_a_payload_never_describes_its_outstanding_steps_as_taken() -> None:
    """The key names are the guard for a class neither real guard can see.

    Handed `next_actions`, a model wrote "A request has been filed with
    counsel" for a row whose only action was REQUEST_FROM_COUNSEL — a step
    nobody has taken, rendered as one that is done. No figure, no verdict word:
    nothing for the numeral or verdict checks to catch. The payload has to make
    the misreading unavailable, so the key says so and the note says so twice.
    """
    src = (ROOT / "api" / "lookup.py").read_text(encoding="utf-8")
    #: The old name, which a model read as "already requested". Its absence is
    #: the assertion — a tautology over the new name would pass whatever the
    #: code said.
    assert '"next_actions": glossed(' not in src
    assert "not_yet_done_someone_must_still_do_these" in src
    assert "Never describe any of them" in src  # wrapped by the formatter; match one line

    #: And the payload no longer uses the completion words itself, which is what
    #: lets `_STEP_CLAIMED` forbid them in the output without refusing honest
    #: echoes. A key called `..._filed_under_...` put "filed" in front of the
    #: model and then punished it for using the word.
    assert '"filed_under_requirements"' not in src  # the key, not the docstring's account of it
    assert "other_requirements_with_a_step_still_outstanding" in src


def test_the_paid_route_is_withheld_unless_the_deployment_switches_it_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The restatement costs money per request; the passage search does not.

    Every other route in this service reads Postgres. An unauthenticated GET
    that spends money is an endpoint anyone who finds the URL can loop, so it
    It has its OWN switch. Gating it on `DECISION_ACTORS` reused an existing
    flag and silently coupled two unrelated questions: turning the assistant on
    would also have opened the decision-recording write surface. `/passages`,
    which is free, is unaffected either way.

    Asserted as a PAIR. Withholding both routes would be safe and useless; the
    point is that the free one is untouched.
    """
    monkeypatch.setattr(lookup, "_assistant_is_offered", lambda: False)
    monkeypatch.setattr(lookup, "_connect", lambda: _CountingConn())
    app = FastAPI()
    app.include_router(lookup.lookup_router)
    client = TestClient(app)
    params = {"on": "2024-12-31", "requirement": "R2"}

    withheld = client.get("/holdings/fund_ii_lucra/explain", params=params)
    assert withheld.status_code == 404
    assert "ASSISTANT_ENABLED" in withheld.json()["detail"]

    monkeypatch.setattr(lookup, "retrieve", lambda *a, **k: (_passage(),))
    assert client.get("/holdings/fund_ii_moonfare/passages", params=params).status_code == 200


def test_a_restatement_the_model_did_not_finish_is_refused() -> None:
    """Every guard passes a truncated paragraph, which is why this is separate.

    A response stopped by the token ceiling has real figures, the right verdict
    and a length under the cap. Nothing in `check()` can tell it apart from a
    finished one — only the API's own `finish_reason` knows, so it is read
    rather than inferred.
    """
    src = (ROOT / "evidence" / "explain.py").read_text(encoding="utf-8")
    assert 'finish_reason") == "length"' in src
    assert "stopped mid-sentence" in src
