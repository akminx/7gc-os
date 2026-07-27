"""Model extraction for the one document a pattern reads badly. SPEC §10.

The corpus is read by deterministic extractors and they work: 247 cited facts,
all resolving. This is not a replacement for them. It is the tier SPEC §10 says
rules cannot cover — *"model extraction only for prose"* — built on the single
document that most needs it, so the cascade is a thing that runs rather than a
thing described.

**The document.** Lucra's CEO writes:

    Wanted you to hear it from me before it circulates: we signed and closed
    the Series A-2 on Wednesday. $3.00 per share, $95M post.

`ingest/documents/extract_irregular.py` reads that with
`re.compile(r"on Wednesday\\. (?P<value>\\$[\\d.]+) per share")` — a pattern
anchored to the two words that happen to precede the figure in this one email.
It is correct and it is not a rule about prose; rewrite the sentence and it
matches nothing.

**Why the guardrail makes the model tier safe.** The model returns a
`field_name`, the figure `value_text`, and the `quote` that states it. It never
returns an offset. The span is computed here by `locate()`, and
`supports_value()` then requires the figure to appear in its own quote as a
whole figure exactly once. So the two failures a language model actually
commits — quoting a passage that is not in the document, and attaching a figure
to a passage that does not state it — are both refusals rather than rows.

That is why model *strength* is not a correctness argument here. A weak model
cannot write a wrong span, because it is not asked for one. What a weak model
costs is **recall**: a figure it does not notice, or a quote it paraphrases
closely enough to look right and not closely enough to be found in the text.
Intelligence buys coverage; the guardrail buys correctness, and the guardrail is
model-independent.

**Fail closed, and never retry.** A schema violation raises. An unresolvable or
unsupported quote is recorded as a `Refusal` and the fact is not produced.
Neither is retried with a looser prompt or a different model: a second attempt
that succeeds where the first was refused has not fixed anything, it has
searched for a phrasing the guard happens to accept.

**Record and replay.** The suite reads the fixture. A live call happens only
when the fixture is absent and a key is present, and CI has neither. The
fixture is keyed by the model id and by the text hash of the document the
quotes must resolve against, so changing either invalidates the recording
instead of replaying one model's answer under another's name.

To re-record:

    rm evidence/fixtures/lucra_ceo_email.*.json
    .venv/bin/python -m evidence.extract --record
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api.config import ROOT, load_env
from ingest.documents.claims import FactDraft
from ingest.documents.parse import ParsedDocument, parse
from packages.contracts.citations import (
    CitationError,
    cited_numeral,
    locate,
    supports_value,
)

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

#: Pinned, and overridable through the environment without an edit.
#:
#: The strong model is the default even though the guardrail would hold with a
#: cheap one, because the two buy different things. Spans are computed by
#: `locate()` and never returned by the model, so no model can put a wrong
#: offset into the ledger — correctness is structural. What model strength buys
#: is recall: the figure a weaker model does not notice, and the quote it
#: paraphrases until `supports_value()` refuses it. Cost is not the constraint —
#: this email is ~700 input tokens, the call is about a cent, and the fixture
#: means it happens once.
DEFAULT_MODEL = "anthropic/claude-opus-5"

#: Which of OpenRouter's backends for that model is allowed to answer. See
#: `_request_body` — this is a reproducibility control, not a preference.
PROVIDER = "Anthropic"

FIXTURES = Path(__file__).resolve().parent / "fixtures"

LUCRA_CEO_EMAIL = (
    ROOT
    / "7GC Audit Case Study/02_Portfolio Documentation/Lucra"
    / "Lucra - Email from CEO re Series A-2 Close (October 17, 2025).txt"
)

#: The ledger's vocabulary for this document, identical to the field names
#: `extract_irregular.py` produces — so "what did the model get" and "what does
#: the pattern get" are the same question asked of the same five slots, not two
#: differently-shaped answers that cannot be compared.
#:
#: Enumerated in the schema rather than left open. A model that invents a field
#: name produces a fact nothing downstream can consume, and an extractor whose
#: output vocabulary depends on the model's mood is not a contract.
FIELDS: tuple[str, ...] = (
    "email_date",
    "close_statement",
    "price_per_share",
    "post_money_valuation",
    "closing_set_status",
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field_name", "value_text", "quote"],
                "properties": {
                    "field_name": {"type": "string", "enum": list(FIELDS)},
                    "value_text": {"type": "string"},
                    "quote": {"type": "string"},
                },
            },
        }
    },
}

SYSTEM_PROMPT = """\
You read one source document and report the figures it states, each with the \
passage that states it. You are producing audit evidence, so every rule below \
is about traceability rather than helpfulness.

- `quote` must be copied VERBATIM from the document, character for character, \
including punctuation and spacing. It is looked up by literal search; a \
paraphrase, a re-typed dash, or a tidied space finds nothing and the fact is \
discarded.
- `quote` must occur exactly ONCE in the document. If a short passage repeats, \
extend it until it names one place.
- `value_text` must be the figure itself, copied verbatim, and must appear \
inside your own `quote`.
- Report a field only if the document states it. Omit the field rather than \
inferring, computing, or rounding. An omission is a finding; a guess is not.
- Do not convert or normalise. If the document writes `$95M`, report `$95M`.
"""

USER_PROMPT = """\
Document: {filename}

Report these fields where the document states them:

- email_date — the date the message itself carries
- close_statement — the sentence in which the round is said to have closed
- price_per_share — the price per share of the round
- post_money_valuation — the post-money valuation of the round
- closing_set_status — what the document says about the executed closing documents

--- BEGIN DOCUMENT ---
{text}
--- END DOCUMENT ---
"""


class ExtractionRefused(RuntimeError):
    """The response cannot be read as facts at all. Route to review, do not retry."""


class FixtureMissing(RuntimeError):
    """No recording, and no way to make one here. CI's normal state."""


@dataclass(frozen=True)
class Refusal:
    """A fact the model proposed and the citation binding would not accept.

    Kept rather than dropped. "The model returned five facts and four were
    written" is the only shape in which a reviewer can see the guard working; a
    silent filter reads exactly like a model that returned four.
    """

    field_name: str
    value_text: str
    quote: str
    reason: str


@dataclass(frozen=True)
class Extraction:
    """What the model proposed, split by what the guard accepted."""

    model_requested: str
    model_served: str
    provider_served: str
    document_text_hash: str
    facts: tuple[FactDraft, ...]
    refusals: tuple[Refusal, ...]


def prompt_for(parsed: ParsedDocument) -> tuple[str, str]:
    return SYSTEM_PROMPT, USER_PROMPT.format(filename=parsed.filename, text=parsed.canonical_text)


def named_digest(hexdigest: str) -> str:
    """A digest written so it says what it is. `sha256:…`, never bare hex.

    Two reasons, and the second one is the one that bites. A hash with no
    algorithm beside it is ambiguous the moment a second algorithm exists. And
    the fixture is a committed file: `detect-secrets` classifies a bare 64-char
    hex string as a Hex High Entropy String and refuses the commit, which for a
    content hash is a false positive that would otherwise have to be silenced
    in `.secrets.baseline` — a file whose entries should be triaged findings,
    not routine noise. Naming the algorithm makes the string stop looking like
    a credential without anyone having to assert that it is not one.
    """
    return f"sha256:{hexdigest}"


def prompt_fingerprint(parsed: ParsedDocument) -> str:
    """A hash over everything that decides what the model is asked.

    Recorded in the fixture and checked on replay. A prompt edited after a
    recording was made produces a fixture that answers a question the code no
    longer asks — which is the quiet version of a stale test, because it still
    passes.
    """
    digest = hashlib.sha256()
    for part in (*prompt_for(parsed), json.dumps(SCHEMA, sort_keys=True)):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return named_digest(digest.hexdigest())


def model_id() -> str:
    return load_env().get("OPENROUTER_MODEL") or DEFAULT_MODEL


def fixture_path(parsed: ParsedDocument, model: str, *, stem: str) -> Path:
    """Keyed by the model and by the text the quotes must resolve against.

    `text_hash` rather than the raw content hash: it covers the extractor
    identity as well as the bytes, and the extractor is what decides the
    offsets a recorded quote will be located at. A poppler upgrade that shifts
    every span must invalidate this recording, and only `text_hash` moves when
    it does.
    """
    slug = model.replace("/", "-").replace(":", "-")
    return FIXTURES / f"{stem}.{slug}.{parsed.text_hash[:16]}.json"


def _request_body(parsed: ParsedDocument, model: str) -> dict[str, Any]:
    system, user = prompt_for(parsed)
    return {
        "model": model,
        # SPEC §10 · "Temperature 0." Not a nudge toward determinism: the
        # fixture is what the suite reads, and a recording made at a
        # temperature nobody pinned is a recording of one sample.
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "extracted_facts", "strict": True, "schema": SCHEMA},
        },
        # One named provider, no fallback — and this was not the first attempt.
        #
        # `{"require_parameters": true}` looks like the right control and is a
        # trap here. OpenRouter filters to providers whose declared
        # `supported_parameters` cover the whole request, and of the seven
        # endpoints behind this model only Azure declares `temperature` — so
        # asking for temperature 0 *plus* require_parameters routes every call
        # to Azure, which then answered `structured_outputs not supported in
        # your workspace` with a 400. A flag that reads as "be strict" silently
        # chose the one provider that could not serve the request.
        #
        # Naming the provider is also the better artefact. A recorded response
        # that could have come from any of four backends is not reproducible,
        # and a fallback is precisely the event that would change who answered
        # without changing anything a reader can see. `allow_fallbacks: false`
        # turns that into a failed call, and `record()` writes the provider the
        # response reports rather than the one it asked for.
        "provider": {"order": [PROVIDER], "allow_fallbacks": False},
    }


def call_model(parsed: ParsedDocument, model: str) -> dict[str, Any]:
    """One live call. Raises rather than returning a partial result.

    `httpx` is imported here rather than at module scope: it is a development
    dependency, the replay path does not need it, and a module that cannot be
    imported without it would make the recorded fixture unreadable on any host
    that installs only the runtime requirements.
    """
    import httpx

    key = load_env().get("OPENROUTER_API_KEY")
    if not key:
        raise FixtureMissing("OPENROUTER_API_KEY is not set, so no live call can be made")

    response = httpx.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=_request_body(parsed, model),
        timeout=120.0,
    )
    if response.status_code != 200:
        raise ExtractionRefused(
            f"OpenRouter returned {response.status_code}: {response.text[:400]}"
        )
    payload: dict[str, Any] = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ExtractionRefused(f"no choices in the response: {json.dumps(payload)[:400]}")
    content = choices[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise ExtractionRefused("the model returned no content")
    return {
        "id": payload.get("id"),
        "model": payload.get("model"),
        "provider": payload.get("provider"),
        "usage": payload.get("usage"),
        "content": content,
    }


def record(parsed: ParsedDocument, *, stem: str, model: str | None = None) -> Path:
    """Make the recording. The only thing in this module that uses the network."""
    chosen = model or model_id()
    path = fixture_path(parsed, chosen, stem=stem)
    served = call_model(parsed, chosen)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "recorded_at": datetime.now(UTC).isoformat(),
                "endpoint": ENDPOINT,
                "document": {
                    "filename": parsed.filename,
                    "content_hash": named_digest(parsed.content_hash),
                    "text_hash": named_digest(parsed.text_hash),
                    "extractor": parsed.extractor,
                },
                "request": {
                    "model": chosen,
                    "provider": PROVIDER,
                    "temperature": 0,
                    "prompt_fingerprint": prompt_fingerprint(parsed),
                },
                "response": served,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def replay(parsed: ParsedDocument, *, stem: str, model: str | None = None) -> dict[str, Any]:
    """The recorded response, or a refusal naming exactly what is stale."""
    chosen = model or model_id()
    path = fixture_path(parsed, chosen, stem=stem)
    if not path.exists():
        raise FixtureMissing(
            f"no recording at {path.name} for {chosen} against text {parsed.text_hash[:16]}. "
            "Re-record with: .venv/bin/python -m evidence.extract --record"
        )
    recorded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    expected = prompt_fingerprint(parsed)
    if recorded.get("request", {}).get("prompt_fingerprint") != expected:
        raise FixtureMissing(
            f"{path.name} was recorded against a different prompt or schema, so it "
            "answers a question this code no longer asks. Re-record with: "
            ".venv/bin/python -m evidence.extract --record"
        )
    return recorded


def parse_response(content: str) -> tuple[dict[str, str], ...]:
    """Read the model's JSON, or refuse. No repair, no partial acceptance."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ExtractionRefused(f"the response is not JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
        raise ExtractionRefused("the response has no `facts` array")
    out: list[dict[str, str]] = []
    for item in payload["facts"]:
        if not isinstance(item, dict):
            raise ExtractionRefused(f"a fact is not an object: {item!r}")
        missing = [
            k for k in ("field_name", "value_text", "quote") if not isinstance(item.get(k), str)
        ]
        if missing:
            raise ExtractionRefused(f"a fact is missing {', '.join(missing)}: {item!r}")
        if item["field_name"] not in FIELDS:
            raise ExtractionRefused(
                f"{item['field_name']!r} is not one of the enumerated fields {FIELDS}"
            )
        out.append(
            {
                "field_name": item["field_name"],
                "value_text": item["value_text"],
                "quote": item["quote"],
            }
        )
    return tuple(out)


def bind(
    *,
    document_version_id: str,
    parsed: ParsedDocument,
    proposed: tuple[dict[str, str], ...],
    model_requested: str,
    model_served: str,
    provider_served: str,
) -> Extraction:
    """Turn proposed facts into cited ones, refusing every one that does not bind.

    The same three checks `ingest.documents.claims.cited_fact()` makes, reached
    from the other side: there the value is a named group inside a pattern's own
    match, so the nesting holds by construction; here the model supplies the
    quote and the value separately, and the nesting has to be tested.
    """
    facts: list[FactDraft] = []
    refusals: list[Refusal] = []
    for item in proposed:
        field_name, value_text, quote = item["field_name"], item["value_text"], item["quote"]
        try:
            citation = locate(
                document_version_id=document_version_id,
                canonical_text=parsed.canonical_text,
                quote=quote,
            )
        except CitationError as exc:
            refusals.append(Refusal(field_name, value_text, quote, str(exc)))
            continue
        if not supports_value(citation.quote, value_text):
            refusals.append(
                Refusal(
                    field_name,
                    value_text,
                    quote,
                    f"the cited passage does not state {value_text!r} as a figure in its "
                    "own right, exactly once",
                )
            )
            continue
        facts.append(
            FactDraft(
                field_name=field_name,
                value_text=value_text,
                citation=citation,
                value_numeric=cited_numeral(value_text),
            )
        )
    return Extraction(
        model_requested=model_requested,
        model_served=model_served,
        provider_served=provider_served,
        document_text_hash=parsed.text_hash,
        facts=tuple(facts),
        refusals=tuple(refusals),
    )


def extract_from_fixture(
    *, document_version_id: str, parsed: ParsedDocument, stem: str, model: str | None = None
) -> Extraction:
    """The whole cascade, off the recording. No network, no key, no clock."""
    chosen = model or model_id()
    recorded = replay(parsed, stem=stem, model=chosen)
    response = recorded["response"]
    return bind(
        document_version_id=document_version_id,
        parsed=parsed,
        proposed=parse_response(str(response["content"])),
        model_requested=chosen,
        model_served=str(response.get("model") or chosen),
        provider_served=str(response.get("provider") or "unrecorded"),
    )


LUCRA_STEM = "lucra_ceo_email"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", action="store_true", help="call the model and write the fixture")
    args = ap.parse_args(argv)

    if not LUCRA_CEO_EMAIL.exists():
        print(f"the case-study document is not present at {LUCRA_CEO_EMAIL}", file=sys.stderr)
        return 2
    parsed = parse(LUCRA_CEO_EMAIL)

    if args.record:
        path = record(parsed, stem=LUCRA_STEM)
        print(f"recorded {path}")

    extraction = extract_from_fixture(
        document_version_id=f"dv_{parsed.text_hash[:24]}", parsed=parsed, stem=LUCRA_STEM
    )
    print(
        f"requested {extraction.model_requested} via {PROVIDER} · "
        f"served {extraction.model_served} via {extraction.provider_served}"
    )
    for fact in extraction.facts:
        span = (fact.citation.span_start, fact.citation.span_end)
        print(f"  {fact.field_name:22s} {fact.value_text!r:22s} {span} {fact.value_numeric}")
    for refusal in extraction.refusals:
        print(f"  REFUSED {refusal.field_name}: {refusal.reason}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
