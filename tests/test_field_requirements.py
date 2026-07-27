"""Which of the client's requests each extracted figure answers.

The defect this map exists for was found by USING the product: open Fluidstack,
click R1, then R2 — the same window and the same twelve figures. The ledger
binds a CLAIM to a requirement, and Fluidstack's Series A purchase agreement is
legitimately relied upon for both, so every figure it cites rendered under both.

Three separate things have to hold and each is proved separately here:

  * every field the corpus extracts is DECLARED — corpus-gated;
  * the write path REFUSES an undeclared one rather than defaulting — synthetic,
    so it runs in CI where the corpus does not exist;
  * the route SENDS the declaration, and the browser's copy of that shape has
    not drifted from it.

The middle one is the guard that can go red on its own. Delete the call in
`ingest/documents/claims.py` and it fails; make `requirements_for` return
`frozenset()` for an unknown field and it fails; make it return every code and
the corpus census below fails instead.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from api.serialize import FACT_RANK_KEY, FACT_REQUIREMENT_KEY, fact_json
from ingest.documents.claims import ClaimDraft, cited_fact, store_claim, store_document
from ingest.documents.extract_spa import FLUIDSTACK
from ingest.documents.field_requirements import (
    FIELD_REQUIREMENT,
    LEAD_FIELDS,
    UndeclaredField,
    UnrankableField,
    check_lead_fields,
    requirements_for,
)
from ingest.documents.load import SOURCES
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import from_stored
from packages.contracts.enums import ExecutionStatus, FactState, RequirementCode, SourceClass
from packages.contracts.models import SourceFact
from tests.schema_helpers import DSN, Conn
from tests.test_web_contracts import RESPONSES_TS, _fields

CORPUS_PRESENT = all(source.path.exists() for source in SOURCES)


def _extracted_field_names() -> set[str]:
    """Every `field_name` the corpus produces, with no database in the way.

    Read from the extractors rather than from a loaded schema on purpose: a
    census taken against `extracted_fact` measures whichever corpus somebody
    last loaded, and the question here is what the CODE will write the next time
    it runs.
    """
    names: set[str] = set()
    for source in SOURCES:
        parsed = parse(source.path)
        for draft in source.build(f"dv_{parsed.text_hash[:24]}", parsed, source.holding_id):
            names |= {fact.field_name for fact in draft.facts}
    return names


@pytest.mark.skipif(not CORPUS_PRESENT, reason="case-study documents are not in the repository")
def test_every_figure_the_corpus_extracts_declares_the_request_it_answers() -> None:
    """Fail closed. A figure whose relevance nobody decided must not be storable."""
    undeclared = sorted(_extracted_field_names() - set(FIELD_REQUIREMENT))
    assert not undeclared, (
        f"{len(undeclared)} extracted field(s) have no declared requirement: {undeclared[:5]}"
    )


@pytest.mark.skipif(not CORPUS_PRESENT, reason="case-study documents are not in the repository")
def test_the_map_declares_no_field_the_corpus_does_not_extract() -> None:
    """The other direction, for the same reason `reliance.py`'s seed check runs both.

    A declaration for a field nothing produces is a judgement about a document
    that is not there — it reads as coverage and cannot be wrong, which is worse
    than being absent.
    """
    stale = sorted(set(FIELD_REQUIREMENT) - _extracted_field_names())
    assert not stale, f"declared for {len(stale)} field(s) nothing extracts: {stale[:5]}"


@pytest.mark.skipif(not CORPUS_PRESENT, reason="case-study documents are not in the repository")
def test_existence_and_fair_value_are_not_answered_by_the_same_figures() -> None:
    """The substantive claim, stated as a difference rather than as two lists.

    A map declaring `{R1, R2}` everywhere would satisfy every other test in this
    file and reproduce the exact defect: R1 and R2 showing the same window. So
    the assertion is that the two sets DIFFER, on the document the owner opened.
    """
    source = next(s for s in SOURCES if s.path == FLUIDSTACK.path)
    parsed = parse(source.path)
    drafts = source.build(f"dv_{parsed.text_hash[:24]}", parsed, source.holding_id)
    fields = {fact.field_name for draft in drafts for fact in draft.facts}
    answers_r1 = {f for f in fields if RequirementCode.R1 in requirements_for(f)}
    answers_r2 = {f for f in fields if RequirementCode.R2 in requirements_for(f)}
    assert answers_r1, "the purchase agreement answers existence and cost with something"
    assert answers_r2, "the purchase agreement answers fair value with something"
    assert answers_r1 != answers_r2
    # And the overlap is small, not "everything answers everything by another
    # name". Nine of the twelve are on one side only.
    assert len(answers_r1 & answers_r2) < len(fields) // 2


def test_an_undeclared_field_is_refused_rather_than_defaulted() -> None:
    """No default. Both available ones are wrong and neither would be reported:
    "all" files a settlement confirmation under fair value, "none" deletes a
    figure from every request that asks for it."""
    with pytest.raises(UndeclaredField, match="does not say which"):
        requirements_for("a_field_nobody_has_ruled_on")


def test_a_figure_relevant_to_nothing_is_a_declaration_and_not_an_absence() -> None:
    """Seven claims in `reliance.py` are already a declared `frozenset()`. The
    same posture one level down: the empty set is an answer, and it is only
    reachable through a name that IS in the map."""
    assert requirements_for("administrator") == frozenset()
    assert "administrator" in FIELD_REQUIREMENT


# ── The write path ───────────────────────────────────────────────────────
# Synthetic, so this runs in CI where the corpus does not exist. `mutate.py --ci`
# hides the corpus and runs exactly this configuration.

BODY = (
    "ACME, INC.\n"
    "Series B Preferred Stock issued at $8.00 per share.\n"
    "    7GC Fund II, L.P.        625,000     $3.20      3.29%\n"
)


def _doc(tmp_path: Path) -> ParsedDocument:
    source = tmp_path / "acme.txt"
    source.write_bytes(BODY.encode("utf-8"))
    return parse(source)


@pytest.mark.skipif(not DSN, reason="MIGRATION_DATABASE_URL not set")
def test_the_write_path_refuses_a_figure_whose_relevance_is_undecided(
    conn: Conn, seed: dict[str, str], tmp_path: Path
) -> None:
    """A new extractor cannot ship a figure the evidence trail would then file by
    accident. Checked at the writer, where the error can name the field."""
    doc = _doc(tmp_path)
    version_id = store_document(conn, doc)
    undeclared = cited_fact(
        document_version_id=version_id,
        canonical_text=doc.canonical_text,
        field_name="whatever_the_extractor_felt_like_calling_it",
        pattern=re.compile(r"7GC Fund II, L\.P\.\s+(?P<value>[\d,]+)"),
    )
    draft = ClaimDraft(
        claim_key="series_b",
        holding_id=seed["h"],
        source_class=SourceClass.COMPANY_CAP_TABLE,
        execution_status=ExecutionStatus.PRO_FORMA,
        issued_date=date(2025, 11, 14),
        applicable_from=date(2025, 11, 14),
        facts=(undeclared,),
    )
    with pytest.raises(UndeclaredField, match="whatever_the_extractor_felt_like_calling_it"):
        store_claim(conn, version_id, draft, doc.canonical_text)
    row = conn.execute(
        "select count(*) from claim where holding_id = %s and claim_key = 'series_b'",
        (seed["h"],),
    ).fetchone()
    assert row is not None
    assert row[0] == 0, "the claim must not land when one of its figures is undeclared"
    conn.rollback()


# ── The wire ─────────────────────────────────────────────────────────────
QUOTE = "issued at $8.00 per share"


def _fact(field_name: str) -> SourceFact:
    start = BODY.index(QUOTE)
    return SourceFact(
        id=1,
        claim_id="c",
        field_name=field_name,
        value_text="$8.00",
        value_numeric=Decimal("8.00"),
        state=FactState.CANONICAL,
        citation=from_stored(
            document_version_id="dv_x",
            quote=QUOTE,
            span=(start, start + len(QUOTE)),
            canonical_text=BODY,
        ),
    )


def test_the_route_sends_the_requests_a_figure_answers() -> None:
    """Sent, not derived in the browser. `scripts/check-web-arch.mjs` refuses a
    component that decides `fund_shares` is about existence, and relevance is a
    judgement about evidence rather than formatting."""
    sent = fact_json(_fact("round_price_per_share"))
    assert sent[FACT_REQUIREMENT_KEY] == ["R2"]
    assert sent["field_name"] == "round_price_per_share"
    # Sorted and stable, so a set's iteration order cannot reorder the wire.
    assert fact_json(_fact("closing_date"))[FACT_REQUIREMENT_KEY] == ["R1", "R2"]
    assert fact_json(_fact("administrator"))[FACT_REQUIREMENT_KEY] == []


def test_the_route_says_how_directly_each_figure_answers_each_request() -> None:
    """Which of ten relevant figures leads is a statement about evidence, so it
    is the API's and not the browser's ordering preference."""
    paid = fact_json(_fact("fund_aggregate_purchase_price"))
    signed = fact_json(_fact("company_signature"))
    assert paid[FACT_REQUIREMENT_KEY] == signed[FACT_REQUIREMENT_KEY] == ["R1"]
    # Both answer existence and cost; only one answers "what did the fund pay".
    assert paid[FACT_RANK_KEY]["R1"] < signed[FACT_RANK_KEY]["R1"]
    # A rank arrives for exactly the requests the figure answers, so a caller
    # cannot read a rank for a request the figure has nothing to do with.
    assert set(fact_json(_fact("closing_date"))[FACT_RANK_KEY]) == {"R1", "R2"}
    assert fact_json(_fact("administrator"))[FACT_RANK_KEY] == {}


def test_a_lead_ordering_may_only_name_figures_that_answer_its_request() -> None:
    """Fail closed in the direction that bites: a typo, or a field whose
    requirement set is later narrowed, leaves a name that can never match — and
    the pane would go on opening on whatever came first, silently."""
    check_lead_fields()
    with pytest.raises(UnrankableField, match="does not declare"):
        _check_with({RequirementCode.R1: ("a_field_nobody_has_ruled_on",)})
    with pytest.raises(UnrankableField, match="cannot lead a request it does not answer"):
        # `round_price_per_share` answers fair value, not existence and cost.
        _check_with({RequirementCode.R1: ("round_price_per_share",)})
    with pytest.raises(UnrankableField, match="names a field twice"):
        _check_with({RequirementCode.R1: ("fund_shares", "fund_shares")})


def _check_with(lead: dict[RequirementCode, tuple[str, ...]]) -> None:
    """Run the lead-field check against a substituted table.

    `monkeypatch` would do this too; the module attribute is set and restored by
    hand so the guard is exercised through the same function the import-time
    call uses, rather than through a copy of it that could drift.
    """
    import ingest.documents.field_requirements as module

    was = module.LEAD_FIELDS
    module.LEAD_FIELDS = lead
    try:
        check_lead_fields()
    finally:
        module.LEAD_FIELDS = was


@pytest.mark.skipif(not CORPUS_PRESENT, reason="case-study documents are not in the repository")
def test_every_request_leads_with_something_the_corpus_actually_states() -> None:
    """A lead ordering naming only fields nothing extracts would rank nothing.

    The check above proves the names are declared; this proves they are REAL —
    the two are different, and only the second catches a table written against a
    corpus that has since changed.
    """
    extracted = _extracted_field_names()
    for requirement, fields in LEAD_FIELDS.items():
        assert set(fields) & extracted, f"{requirement.value} leads with nothing the corpus states"


def test_the_route_refuses_to_serialise_a_figure_nobody_has_ruled_on() -> None:
    """The read path fails closed too. A field that reached the database around
    the writer must not arrive in the browser under a silent default."""
    with pytest.raises(UndeclaredField):
        fact_json(_fact("a_field_nobody_has_ruled_on"))


def test_the_browsers_fact_is_the_model_plus_what_the_serialiser_adds() -> None:
    """`responses.ts` mirrors `api/serialize.py`, and nothing reported when it
    stopped: a field that is always `undefined` renders as a blank cell, which on
    these screens reads as "nothing to report"."""
    assert RESPONSES_TS.exists()
    added = {FACT_REQUIREMENT_KEY, FACT_RANK_KEY}
    assert _fields("EvidenceFact") == set(SourceFact.model_fields) | added
    # Read off the serialiser rather than trusted: an entry left here after the
    # route stopped sending the key would make `responses.ts` declare a field
    # the browser never receives, and an absent field renders as a blank.
    assert set(fact_json(_fact("fund_shares"))) - set(SourceFact.model_fields) == added
