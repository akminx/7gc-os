"""The model tier, and the guard that decides what it is allowed to write.

Two halves, for the same reason the extractor suites have two:

* the binding is proved on synthetic text and synthetic model output, so every
  way a model can be refused runs in CI with no corpus, no key and no network;
* the recorded call is replayed against the real Lucra email, which skips where
  the fund's documents are private.

The recorded result is not a clean pass, and that is the point of having it.
Claude Opus 5 at temperature 0 under a strict JSON schema returned all five
fields with quotes that all located in the document — and the citation binding
refused two of them, because `value_text` ran up against the punctuation that
`value_token_occurrences` reads as a figure continuing. One of the two is the
price per share, which is the figure the whole claim is priced from.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from evidence.extract import (
    FIELDS,
    LUCRA_CEO_EMAIL,
    LUCRA_STEM,
    ExtractionRefused,
    FixtureMissing,
    bind,
    extract_from_fixture,
    fixture_path,
    model_id,
    parse_response,
    prompt_fingerprint,
    replay,
)
from ingest.documents.extract_irregular import lucra_email_facts
from ingest.documents.parse import ParsedDocument, content_hash, parse, split_pages, text_hash

# ── Synthetic ────────────────────────────────────────────────────────────

_TEXT = (
    "ACME, INC. — Notice to Stockholders\n"
    "7GC Fund II, L.P.   625,000   $3.20\n"
    "The round closed at $8.00 per share on a $95M post-money basis.\n"
    "The round closed at $8.00 per share on a $95M post-money basis.\n"
)


def _document(text: str = _TEXT) -> ParsedDocument:
    raw = text.encode("utf-8")
    return ParsedDocument(
        filename="synthetic.txt",
        source_bytes=raw,
        content_hash=content_hash(raw),
        byte_size=len(raw),
        canonical_text=text,
        extractor="utf8-verbatim@1",
        text_hash=text_hash("utf8-verbatim@1", text),
        pages=split_pages(text),
    )


def _bound(*facts: dict[str, str], document: ParsedDocument | None = None) -> Any:
    return bind(
        document_version_id="dv_synthetic",
        parsed=document or _document(),
        proposed=tuple(facts),
        model_requested="test/model",
        model_served="test/model",
        provider_served="test",
    )


def _fact(field_name: str, value_text: str, quote: str) -> dict[str, str]:
    return {"field_name": field_name, "value_text": value_text, "quote": quote}


def test_a_quote_the_document_states_becomes_a_fact_with_a_computed_span() -> None:
    text = "ACME, INC.\n7GC Fund II, L.P.   625,000 shares at $3.20\n"
    out = _bound(
        _fact("price_per_share", "$3.20", "625,000 shares at $3.20"), document=_document(text)
    )
    assert out.refusals == ()
    (fact,) = out.facts
    assert fact.value_numeric == Decimal("3.20")
    assert text[fact.citation.span_start : fact.citation.span_end] == fact.citation.quote


def test_a_paraphrased_quote_is_refused_rather_than_approximately_located() -> None:
    """The failure a language model actually commits, and it is not an offset.

    "The round closed at $8.00 a share" is what the document means and not what
    it says. A retrieval system that scored similarity would accept it; a
    literal search finds nothing, so nothing is written.
    """
    out = _bound(_fact("price_per_share", "$8.00", "The round closed at $8.00 a share"))
    assert out.facts == ()
    (refusal,) = out.refusals
    assert "quote not present" in refusal.reason


def test_a_quote_that_names_two_places_is_refused() -> None:
    """The synthetic document states the same sentence twice, deliberately."""
    out = _bound(_fact("price_per_share", "$8.00", "The round closed at $8.00 per share"))
    assert out.facts == ()
    (refusal,) = out.refusals
    assert "occurs 2 times" in refusal.reason


def test_a_value_that_is_a_fragment_of_a_longer_figure_is_refused() -> None:
    """INV-8's second hole: the quote resolves and the number is still wrong.

    `625` really is in a row stating `625,000`, and every span check passes.
    """
    out = _bound(_fact("price_per_share", "625", "7GC Fund II, L.P.   625,000   $3.20"))
    assert out.facts == ()
    (refusal,) = out.refusals
    assert "as a figure in its own right" in refusal.reason


def test_a_figure_the_cited_passage_does_not_contain_is_refused() -> None:
    out = _bound(_fact("price_per_share", "$3.20", "ACME, INC. — Notice to Stockholders"))
    assert out.facts == ()
    assert "as a figure in its own right" in out.refusals[0].reason


def test_a_refusal_does_not_take_the_facts_beside_it_down() -> None:
    """Per-fact, because a document is rarely wholly readable or wholly not."""
    out = _bound(
        _fact("price_per_share", "$3.20", "7GC Fund II, L.P.   625,000   $3.20"),
        _fact("post_money_valuation", "$95M", "invented text"),
    )
    assert [f.field_name for f in out.facts] == ["price_per_share"]
    assert [r.field_name for r in out.refusals] == ["post_money_valuation"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not json at all", "not JSON"),
        ('{"results": []}', "no `facts` array"),
        ('{"facts": ["a string"]}', "not an object"),
        ('{"facts": [{"field_name": "price_per_share", "value_text": "$1"}]}', "missing quote"),
        ('{"facts": [{"field_name": "cost", "value_text": "$1", "quote": "x"}]}', "enumerated"),
    ],
)
def test_a_schema_violation_raises_rather_than_being_partly_accepted(
    payload: str, message: str
) -> None:
    """Fail closed, and never retry.

    Refusing the whole response rather than the offending fact is deliberate: a
    response that does not match the schema is evidence the call went wrong, and
    keeping the facts that happen to parse would let a truncated or hallucinated
    payload contribute rows.
    """
    with pytest.raises(ExtractionRefused, match=message):
        parse_response(payload)


def test_the_enumerated_fields_are_the_ledgers_own_field_names() -> None:
    """So "what did the model get" and "what does the pattern get" compare."""
    parsed = parse(LUCRA_CEO_EMAIL) if LUCRA_CEO_EMAIL.exists() else None
    if parsed is None:
        pytest.skip("case-study document is not in the repository")
    assert {f.field_name for f in lucra_email_facts("dv", parsed)} == set(FIELDS)


def test_the_fixture_key_separates_models_and_documents() -> None:
    document = _document()
    other = _document(_TEXT + "one more line\n")
    assert fixture_path(document, "a/model", stem="s") != fixture_path(
        document, "b/model", stem="s"
    )
    assert fixture_path(document, "a/model", stem="s") != fixture_path(other, "a/model", stem="s")
    assert "/" not in fixture_path(document, "a/model", stem="s").name


def test_a_prompt_edited_after_the_recording_invalidates_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stale fixture that still passes is the quiet version of no test at all."""
    import evidence.extract as extract

    document = _document()
    monkeypatch.setattr(extract, "FIXTURES", tmp_path)
    path = tmp_path / fixture_path(document, "a/model", stem="s").name
    path.write_text(
        '{"request": {"prompt_fingerprint": "stale"}, "response": {"content": "{}"}}',
        encoding="utf-8",
    )
    with pytest.raises(FixtureMissing, match="different prompt or schema"):
        replay(document, stem="s", model="a/model")

    fingerprint = prompt_fingerprint(document)
    path.write_text(
        f'{{"request": {{"prompt_fingerprint": "{fingerprint}"}},'
        ' "response": {"content": "{}"}}',
        encoding="utf-8",
    )
    assert replay(document, stem="s", model="a/model")["response"]["content"] == "{}"


def test_an_absent_recording_says_how_to_make_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import evidence.extract as extract

    monkeypatch.setattr(extract, "FIXTURES", tmp_path)
    with pytest.raises(FixtureMissing, match="evidence.extract --record"):
        replay(_document(), stem="s", model="a/model")


# ── The request, without making one ──────────────────────────────────────


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self) -> object:
        return self._payload


def _posted(monkeypatch: pytest.MonkeyPatch, response: _Response) -> list[dict[str, Any]]:
    """Capture the request body rather than sending it."""
    import httpx

    seen: list[dict[str, Any]] = []

    def capture(url: str, **kwargs: Any) -> _Response:
        seen.append({"url": url, **kwargs})
        return response

    monkeypatch.setattr(httpx, "post", capture)
    return seen


_OK = {
    "id": "gen-test",
    "model": "test/model",
    "provider": "TestProvider",
    "usage": {"total_tokens": 1},
    "choices": [{"message": {"content": '{"facts": []}'}}],
}


def test_the_request_pins_temperature_schema_and_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three things a recording is worthless without.

    Temperature 0 because a recording made at an unpinned temperature is a
    recording of one sample; `strict` because OpenRouter otherwise treats the
    schema as advice; and one named provider with no fallback because a
    response that could have come from any of four backends is not reproducible.
    """
    from evidence.extract import PROVIDER, call_model

    seen = _posted(monkeypatch, _Response(200, _OK))
    call_model(_document(), "test/model")
    body = seen[0]["json"]
    assert body["temperature"] == 0
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"order": [PROVIDER], "allow_fallbacks": False}
    assert seen[0]["headers"]["Authorization"].startswith("Bearer ")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_Response(400, {"error": "structured_outputs not supported"}), "returned 400"),
        (_Response(200, {"choices": []}), "no choices"),
        (_Response(200, {"choices": [{"message": {"content": "   "}}]}), "no content"),
    ],
)
def test_a_bad_call_raises_rather_than_recording_something(
    monkeypatch: pytest.MonkeyPatch, response: _Response, message: str
) -> None:
    from evidence.extract import call_model

    _posted(monkeypatch, response)
    with pytest.raises(ExtractionRefused, match=message):
        call_model(_document(), "test/model")


def test_no_key_is_a_missing_fixture_not_a_failed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI's normal state, and it must not read as a broken model."""
    import evidence.extract as extract

    monkeypatch.setattr(extract, "load_env", dict)
    with pytest.raises(FixtureMissing, match="OPENROUTER_API_KEY"):
        extract.call_model(_document(), "test/model")


def test_a_recording_round_trips_through_the_replay_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Record then replay, with the network answered by a stub either way."""
    import evidence.extract as extract

    document = _document()
    served = dict(_OK)
    served["choices"] = [
        {
            "message": {
                "content": (
                    '{"facts": [{"field_name": "price_per_share", "value_text": "$3.20",'
                    ' "quote": "7GC Fund II, L.P.   625,000   $3.20"}]}'
                )
            }
        }
    ]
    _posted(monkeypatch, _Response(200, served))
    monkeypatch.setattr(extract, "FIXTURES", tmp_path)

    path = extract.record(document, stem="s", model="test/model")
    assert path.parent == tmp_path

    out = extract.extract_from_fixture(
        document_version_id="dv_synthetic", parsed=document, stem="s", model="test/model"
    )
    assert out.provider_served == "TestProvider"
    assert [f.value_numeric for f in out.facts] == [Decimal("3.20")]
    assert out.refusals == ()


# ── The recorded call ────────────────────────────────────────────────────

_LUCRA_FIXTURE = (
    fixture_path(parse(LUCRA_CEO_EMAIL), model_id(), stem=LUCRA_STEM)
    if LUCRA_CEO_EMAIL.exists()
    else None
)

needs_recording = pytest.mark.skipif(
    _LUCRA_FIXTURE is None or not _LUCRA_FIXTURE.exists(),
    reason="the case-study document or its recording is not in the repository",
)


@pytest.fixture
def lucra() -> ParsedDocument:
    return parse(LUCRA_CEO_EMAIL)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay must not reach for the network, and this is how that is known.

    A test that merely happens not to call the model passes identically whether
    or not the replay path is offline. Breaking `httpx.post` makes the two
    outcomes different.
    """
    import httpx

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay called the network")

    monkeypatch.setattr(httpx, "post", refuse)


@needs_recording
@pytest.mark.usefixtures("no_network")
def test_the_recording_replays_to_three_facts_and_two_refusals(lucra: ParsedDocument) -> None:
    """What the model got, and what the guard would not let it write.

    The model proposed all five fields. Every quote it gave located in the
    document — `locate()` refused nothing, which is the failure mode a strict
    schema and a verbatim instruction do prevent. `supports_value()` refused
    two, and both refusals are about `value_text` ending immediately before
    punctuation inside its own quote.
    """
    out = extract_from_fixture(document_version_id="dv_lucra", parsed=lucra, stem=LUCRA_STEM)
    assert out.model_requested == "anthropic/claude-opus-5"
    assert out.model_served == "anthropic/claude-opus-5"
    assert out.provider_served == "Anthropic"
    assert [f.field_name for f in out.facts] == [
        "email_date",
        "post_money_valuation",
        "closing_set_status",
    ]
    assert [r.field_name for r in out.refusals] == ["close_statement", "price_per_share"]


@needs_recording
@pytest.mark.usefixtures("no_network")
def test_every_accepted_fact_resolves_in_the_document(lucra: ParsedDocument) -> None:
    out = extract_from_fixture(document_version_id="dv_lucra", parsed=lucra, stem=LUCRA_STEM)
    for fact in out.facts:
        span = lucra.canonical_text[fact.citation.span_start : fact.citation.span_end]
        assert span == fact.citation.quote, fact.field_name
        assert fact.value_text in fact.citation.quote, fact.field_name


@needs_recording
@pytest.mark.usefixtures("no_network")
def test_the_guard_refused_the_price_the_claim_is_priced_from(lucra: ParsedDocument) -> None:
    """The result worth reporting, recorded so it cannot be summarised away.

    The model returned `value_text="$3.00 per share"` quoted as
    `"$3.00 per share, $95M post."` — a correct reading of the sentence and not
    a figure. `value_token_occurrences` reads the comma after `share` as the
    figure continuing, exactly as it reads the comma in `625,000`, so the count
    is zero and the fact is refused.

    `ingest/documents/extract_irregular.py` avoids this by ending its `value`
    group at `$3.00` and putting the anchor in front, which its own docstring
    says is not style. A model asked for "the figure" returned the phrase the
    field is named after, and the two rules that make a citation trustworthy —
    quote more context, and let no punctuation follow the value — pull in
    opposite directions for it.
    """
    out = extract_from_fixture(document_version_id="dv_lucra", parsed=lucra, stem=LUCRA_STEM)
    refused = {r.field_name: r for r in out.refusals}
    assert refused["price_per_share"].value_text == "$3.00 per share"
    assert refused["price_per_share"].quote == "$3.00 per share, $95M post."
    assert "as a figure in its own right, exactly once" in refused["price_per_share"].reason
    assert refused["close_statement"].value_text == (
        "we signed and closed the Series A-2 on Wednesday"
    )
    assert {f.field_name for f in out.facts}.isdisjoint({"price_per_share"})


@needs_recording
@pytest.mark.usefixtures("no_network")
def test_the_model_and_the_pattern_read_the_same_document(lucra: ParsedDocument) -> None:
    """Field by field, against the extractor that is already in production.

    Two fields agree exactly. One — `email_date` — the model reads *wider*: the
    pattern stops at `Friday, October 17, 2025` because that is the date it was
    built from, and the model returned the header's full timestamp, which is
    equally verbatim and resolves. Two are refused. Nothing the model produced
    disagrees with the pattern about a value; the difference is coverage and
    extent, which is what the model tier was expected to trade.
    """
    out = extract_from_fixture(document_version_id="dv_lucra", parsed=lucra, stem=LUCRA_STEM)
    pattern = {f.field_name: f.value_text for f in lucra_email_facts("dv_lucra", lucra)}
    model = {f.field_name: f.value_text for f in out.facts}

    assert model["post_money_valuation"] == pattern["post_money_valuation"] == "$95M"
    assert model["closing_set_status"] == pattern["closing_set_status"]
    assert pattern["email_date"] == "Friday, October 17, 2025"
    assert model["email_date"] == "Friday, October 17, 2025, 2:38 PM ET"
    assert pattern["price_per_share"] == "$3.00"
    assert set(pattern) - set(model) == {"close_statement", "price_per_share"}


@needs_recording
@pytest.mark.usefixtures("no_network")
def test_the_command_reports_the_refusals_beside_the_facts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`python -m evidence.extract` with no `--record` reads the fixture only."""
    import evidence.extract as extract

    assert extract.main([]) == 0
    out = capsys.readouterr().out
    assert "served anthropic/claude-opus-5 via Anthropic" in out
    assert "REFUSED price_per_share" in out
    assert "REFUSED close_statement" in out


def test_an_absent_document_is_reported_rather_than_traced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import evidence.extract as extract

    monkeypatch.setattr(extract, "LUCRA_CEO_EMAIL", tmp_path / "absent.txt")
    assert extract.main([]) == 2
    assert "not present" in capsys.readouterr().err


@needs_recording
def test_the_recording_carries_no_credential() -> None:
    """The fixture is committed, so this is not a stylistic preference."""
    assert _LUCRA_FIXTURE is not None
    body = _LUCRA_FIXTURE.read_text(encoding="utf-8")
    assert "Bearer" not in body
    assert "sk-or-" not in body
    assert "Authorization" not in body


@needs_recording
def test_the_recording_states_no_bare_hex_digest() -> None:
    """`detect-secrets` reads a 64-character hex string as a credential.

    Every digest in the fixture is written `sha256:…`, so the gate's secret
    scanner has nothing to flag and `.secrets.baseline` stays a list of triaged
    findings rather than a list of hashes somebody had to promise were fine.
    This is asserted rather than remembered because the fix lives in one helper
    and the next field added to the recording will not go through it by default.
    """
    import re

    assert _LUCRA_FIXTURE is not None
    body = _LUCRA_FIXTURE.read_text(encoding="utf-8")
    assert re.search(r'"[0-9a-f]{32,}"', body) is None
    assert body.count('"sha256:') == 3


@needs_recording
def test_the_recording_is_bound_to_the_text_its_quotes_resolve_against(
    lucra: ParsedDocument,
) -> None:
    """A re-extraction that shifts every offset must invalidate the recording."""
    assert _LUCRA_FIXTURE is not None
    assert lucra.text_hash[:16] in _LUCRA_FIXTURE.name
    assert lucra.extractor == "utf8-verbatim@1"
    assert date(2025, 10, 17).strftime("%B %-d, %Y") in lucra.canonical_text
