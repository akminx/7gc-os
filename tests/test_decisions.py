"""The write surface: what it records, and what the ledger refuses to let it.

The case this suite is built around is Anthropic 25Q4. Its $8,000,000 rests on a
press article, R1 and R2 are both `insufficient`, and SPEC §6.3 resolves it by
giving the figure a transcription approval and no valuation approval — so it
appears in the reconciliation and gap sections and enters no approved total. A
product that could record `valuation / approved` for that mark would be able to
launder exactly the figure the auditor most needs to see qualified.

So the refusal is the first test here, not the last. Every prerequisite it
turns on already exists in `supabase/migrations/0003_approval_prerequisites.sql`
and is already proven by `tests/test_schema_approval.py`; what is new is that a
request now reaches those triggers and that their sentence reaches a human. That
is what these tests measure — the translation, not the policy.

Two mechanical notes, because both are load-bearing:

* **Nothing here commits.** `api.decisions.ledger_connection` commits after the
  route returns; the tests override that dependency with the session connection
  the `conn` fixture rolls back, so the route's own code path runs unchanged and
  the `public` schema is left as it was found. `demo` holds the fund and is
  never written by a test.
* **Refusals arrive inside the request.** Both prerequisite triggers are
  deferred, so `record` issues `set constraints all immediate`; without it the
  refusal would surface at commit, after the caller had been told the decision
  was recorded.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import decisions
from api.main import app
from tests.schema_helpers import DSN, Conn, make_fact, make_mark, rejects, returned_id
from tests.test_schema_approval import assess

pytestmark = pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")

client = TestClient(app)

ACTOR = "reviewer"


@pytest.fixture
def actors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that names actors is, by SPEC §3.1, the private one."""
    monkeypatch.setenv("DECISION_ACTORS", f" {ACTOR} , second_reviewer ")


@pytest.fixture
def surface(actors: None, conn: Conn) -> Iterator[Conn]:
    """The route, wired to the transaction this test will roll back."""
    app.dependency_overrides[decisions.ledger_connection] = lambda: conn
    yield conn
    app.dependency_overrides.pop(decisions.ledger_connection, None)


def post(body: dict[str, Any], actor: str = ACTOR) -> Any:
    return client.post("/decisions", json=body, headers={"X-Actor-Id": actor})


def valuation(mark_id: int, status: str = "approved", **extra: Any) -> dict[str, Any]:
    return {"decision_type": "valuation", "status": status, "subject_id": str(mark_id), **extra}


def press_claim(conn: Conn, seed: dict[str, str]) -> str:
    """A claim whose authority is `press`. SPEC §7.3 · R2 · press → insufficient.

    No stated figure on the claim row itself, so `0009_claim_figures_are_cited`
    has nothing to demand — the point here is the authority class, not the
    number.
    """
    claim_id = f"{seed['cl']}_press"
    conn.execute(
        "insert into claim (id, document_version_id, holding_id, claim_key, source_class,"
        " execution_status, issued_date, applicable_from)"
        " values (%s, %s, %s, 'press_report', 'press', 'not_applicable',"
        " '2025-11-20', '2025-01-01')",
        (claim_id, seed["dv"], seed["h"]),
    )
    return claim_id


def eight_million(conn: Conn, seed: dict[str, str]) -> int:
    """Anthropic 25Q4's shape: a reported amount nothing independently derives."""
    return returned_id(
        conn,
        "insert into mark (holding_id, period_id, reported_amount, reported_currency,"
        " derivation_status, derivation_reason)"
        " values (%s, %s, 8000000, 'USD', 'not_derivable', 'NO_PRIMARY_PPS_SUPPORT')"
        " returning id",
        (seed["h"], seed["p"]),
    )


def supported_mark(conn: Conn, seed: dict[str, str]) -> tuple[int, list[int]]:
    """A mark whose R1 and R2 are both sufficient and both cite a claim."""
    mark_id = make_mark(conn, seed)
    cited = [assess(conn, seed, mark_id, code, claim=seed["cl"]) for code in ("R1", "R2")]
    return mark_id, cited


# ── The refusal · SPEC §6.3, INV-10 ──────────────────────────────────────
def test_a_valuation_approval_of_a_press_backed_mark_is_refused(
    surface: Conn, seed: dict[str, str]
) -> None:
    """Anthropic 25Q4: $8,000,000, R1 and R2 both `insufficient` on a press
    article. The request is well formed, the actor is named, the mark exists —
    and the ledger still refuses, because an approval resting on an insufficient
    assessment asserts support the assessment itself denies.

    The message is asserted, not just the status. A 409 with an opaque body is a
    block a human cannot act on, and this is the one screen where the reason IS
    the product.
    """
    mark_id = eight_million(surface, seed)
    article = press_claim(surface, seed)
    for code in ("R1", "R2"):
        assess(surface, seed, mark_id, code, verdict="insufficient", claim=article)

    response = post(valuation(mark_id))

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "INV-10" in detail
    assert "valuation_approval_needs_complete_evidence" in detail
    assert f"valuation approval of mark {mark_id}" in detail
    assert "cites no sufficient R1 assessment at policy version v1" in detail


def test_the_refusal_names_fair_value_support_when_that_is_the_short_one(
    surface: Conn, seed: dict[str, str]
) -> None:
    """The same mark with existence and cost satisfied. The refusal must move to
    R2 rather than staying on whichever requirement it named first — otherwise
    the message is a constant and tells a reader nothing about their case."""
    mark_id = eight_million(surface, seed)
    assess(surface, seed, mark_id, "R1", claim=seed["cl"])
    assess(surface, seed, mark_id, "R2", verdict="insufficient", claim=press_claim(surface, seed))

    detail = post(valuation(mark_id)).json()["detail"]

    assert "cites no sufficient R2 assessment at policy version v1" in detail


def test_a_mark_with_no_assessment_at_all_is_refused_one_step_earlier(
    surface: Conn, seed: dict[str, str]
) -> None:
    """The demo ledger's present state, and therefore what an operator sees today.

    `evidence_assessment` is empty in `demo`: verdicts are computed on read by
    `policy/` and nothing writes them down, so a valuation approval of Anthropic
    25Q4 cites nothing and is refused by `0002`'s gate rather than `0003`'s. Same
    block, one step earlier, different sentence — recorded here because a demo
    script quoting the other message would look broken.
    """
    mark_id = eight_million(surface, seed)

    response = post(valuation(mark_id))

    assert response.status_code == 409
    assert "names no evidence set" in response.json()["detail"]


def test_a_refused_decision_leaves_no_row_behind(surface: Conn, seed: dict[str, str]) -> None:
    """A blocked approval must not be a recorded one. The decision row is
    INSERTed before the deferred triggers can see it, so "refused" and "rolled
    back" are two facts and only the test can tell they agree."""
    mark_id = eight_million(surface, seed)
    assess(surface, seed, mark_id, "R1", verdict="insufficient", claim=press_claim(surface, seed))
    assert post(valuation(mark_id)).status_code == 409

    row = surface.execute(
        "select count(*) from review_decision where actor_id = %s", (ACTOR,)
    ).fetchone()
    assert row is not None
    assert row[0] == 0


# ── The path that must survive it ────────────────────────────────────────
def test_a_complete_evidence_set_records_the_approval_and_the_set_it_cites(
    surface: Conn, seed: dict[str, str]
) -> None:
    """Without this, a route that refused everything would pass every test above.

    The cited set is asserted too: INV-10 binds the approval to the assessments
    it rests on, and an approval that names none is the shape `0002` exists to
    refuse.
    """
    mark_id, cited = supported_mark(surface, seed)

    response = post(valuation(mark_id))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["decision_type"] == "valuation"
    assert body["status"] == "approved"
    assert body["mark_id"] == mark_id
    assert body["policy_version"] == "v1"
    assert body["actor_id"] == ACTOR
    assert body["evidence_assessment_ids"] == cited
    stored = surface.execute(
        "select count(*) from decision_evidence where decision_id = %s", (body["id"],)
    ).fetchone()
    assert stored is not None
    assert stored[0] == len(cited)


# ── SPEC §6.3 · a decision names its type, and no type implies another ───
def test_a_transcription_decision_binds_a_source_fact_and_no_mark(
    surface: Conn, seed: dict[str, str]
) -> None:
    """INV-18 · approving that a figure was transcribed faithfully is not
    approving that it is fair value, so the two cannot share a subject. The
    recorded row binds a source fact and carries no mark at all, which is what
    keeps it out of every rule that reads `mark_id`."""
    fact_id = make_fact(surface, seed)

    response = post(
        {"decision_type": "transcription", "status": "approved", "subject_id": str(fact_id)}
    )

    assert response.status_code == 201, response.text
    assert response.json()["mark_id"] is None
    assert response.json()["evidence_assessment_ids"] == []
    row = surface.execute(
        "select subject_kind, subject_id, mark_id from review_decision where id = %s",
        (response.json()["id"],),
    ).fetchone()
    assert row is not None
    assert row[0] == "source_fact"
    assert row[1] == str(fact_id)
    assert row[2] is None


def test_a_mark_bound_decision_cannot_name_something_that_is_not_a_mark(
    surface: Conn, seed: dict[str, str]
) -> None:
    """The subject is one field whose meaning the type fixes. A valuation
    decision naming a packet id is refused at the request rather than becoming a
    foreign key error nobody can read."""
    response = post({"decision_type": "valuation", "status": "approved", "subject_id": "packet_1"})
    assert response.status_code == 422
    assert "binds a mark revision" in response.text


def test_a_review_records_a_verdict_and_not_a_lifecycle_state(actors: None) -> None:
    """`draft` and `superseded` are states a decision arrives at — a supersession
    is the effect of a later decision, not something a reviewer asserts. Letting
    a caller POST one would let the surface retire an approval without recording
    the decision that replaced it."""
    response = post({"decision_type": "valuation", "status": "draft", "subject_id": "1"})
    assert response.status_code == 422
    assert "a review records approved, rejected" in response.text


def test_a_decision_with_no_subject_is_refused(actors: None) -> None:
    """A decision about nothing is a signature on a blank page."""
    response = post({"decision_type": "packet", "status": "approved", "subject_id": "  "})
    assert response.status_code == 422
    assert "must name the subject it binds" in response.text


# ── A rejection states its reason ────────────────────────────────────────
def test_a_rejection_with_no_stated_reason_is_refused(surface: Conn, seed: dict[str, str]) -> None:
    """ "A human said no" is not an audit record. Without the reason, nothing in
    the packet says what would change the answer."""
    mark_id, _ = supported_mark(surface, seed)

    response = post(valuation(mark_id, status="rejected"))

    assert response.status_code == 422
    assert "a rejection must state its reason" in response.text
    assert post(valuation(mark_id, status="rejected", reason="   ")).status_code == 422


def test_a_rejection_records_its_reason_against_the_evidence_it_was_made_on(
    surface: Conn, seed: dict[str, str]
) -> None:
    mark_id, cited = supported_mark(surface, seed)

    why = "The cap table is pro forma; ask for the closing set."
    response = post(valuation(mark_id, status="rejected", reason=why))

    assert response.status_code == 201, response.text
    assert response.json()["evidence_assessment_ids"] == cited
    row = surface.execute(
        "select notes from review_decision where id = %s", (response.json()["id"],)
    ).fetchone()
    assert row is not None
    assert row[0] == why


# ── INV-10 / INV-5 · append-only ─────────────────────────────────────────
def test_changing_the_answer_is_a_new_decision_and_never_an_edit(
    surface: Conn, seed: dict[str, str]
) -> None:
    """Two decisions about one mark, both retained, in the order they were made —
    and the first one still unedited. A surface offering "change this approval"
    would have to UPDATE, which the database refuses outright."""
    mark_id, _ = supported_mark(surface, seed)
    first = post(valuation(mark_id, status="rejected", reason="Waiting on the executed agreement."))
    second = post(valuation(mark_id))
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]

    kept = surface.execute(
        "select id, status from review_decision where mark_id = %s order by id", (mark_id,)
    ).fetchall()
    assert [str(r[1]) for r in kept] == ["rejected", "approved"]

    assert "append-only" in rejects(
        surface,
        "update review_decision set status = 'superseded' where id = %s",
        (first.json()["id"],),
    )


# ── SPEC §3.1 · who may write, and where ─────────────────────────────────
def test_a_deployment_that_names_no_actors_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public deployment. `DECISION_ACTORS` empty is the read-only state, and
    it is the default — an unset variable cannot be an open door."""
    monkeypatch.setenv("DECISION_ACTORS", "")
    response = post({"decision_type": "valuation", "status": "approved", "subject_id": "1"})
    assert response.status_code == 403
    assert "records no decisions" in response.json()["detail"]


def test_an_actor_this_deployment_never_named_is_refused(actors: None) -> None:
    """Not authentication, and it does not claim to be (SPEC §2). It is the
    difference between an approval log naming someone the configuration knows
    and one naming whoever asked."""
    body = {"decision_type": "packet", "status": "approved", "subject_id": "p"}
    assert post(body, "nobody").status_code == 403
    unnamed = client.post("/decisions", json=body)
    assert unnamed.status_code == 403
    assert "not a named actor" in unnamed.json()["detail"]


def test_no_ledger_configured_records_nothing(
    actors: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read routes may honestly answer from the bundled fixture when no
    database is configured. A decision may not: an approval recorded against a
    fixture exists nowhere, which is worse than no approval."""
    monkeypatch.setattr("api.routes._connect", lambda: None)
    response = post({"decision_type": "valuation", "status": "approved", "subject_id": "1"})
    assert response.status_code == 503
    assert "nothing honest to fall back to" in response.json()["detail"]


# ── INV-10 · the decision binds the policy it was made under ─────────────
def test_a_decision_made_under_another_policy_version_is_refused(
    surface: Conn, seed: dict[str, str]
) -> None:
    """A caller whose screen was computed at v0 is deciding about verdicts this
    service no longer produces. Recording it at either version would name one
    policy and mean the other."""
    mark_id, _ = supported_mark(surface, seed)

    response = post(valuation(mark_id, policy_version="v0"))

    assert response.status_code == 409
    assert "INV-10" in response.json()["detail"]
    assert "reload the packet" in response.json()["detail"]


def test_the_write_connection_is_the_sanctioned_one_and_commits_only_at_the_end() -> None:
    """The dependency is the transaction boundary: the commit sits after the
    `yield`, so a refusal — the database's or this module's — leaves nothing
    behind. Driven directly, because every other test here replaces it with a
    connection it can roll back, which would otherwise leave the real one
    unexercised.

    It must also be `api/routes.py::_connect` and not a second helper: that one
    carries `prepare_threshold=None`, and a transaction-mode pooler answers a
    re-prepared statement with a 500 on every route.
    """
    opened = decisions.ledger_connection()
    conn = next(opened)
    assert conn.prepare_threshold is None
    with pytest.raises(StopIteration):
        next(opened)
    assert conn.closed


# ── SPEC §3.1 · the separation is checked, not asserted in prose ─────────
def test_the_decisions_surface_is_the_only_write_path_the_application_serves() -> None:
    """`api/routes.py` says every route it carries is a GET. That sentence is
    only worth anything if something fails when it stops being true.

    Read off the served OpenAPI document rather than off the router objects, so
    it measures what the application actually exposes — including anything a
    later module mounts without telling this one.
    """
    served = {
        (path, method)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    writes = {(path, method) for path, method in served if method != "get"}
    assert writes == {(decisions.PREFIX, "post")}, (
        "a write path exists outside the decisions surface; SPEC §3.1 requires the "
        "write surface to be separable and disableable"
    )
