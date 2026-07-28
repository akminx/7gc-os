"""Ask in English, get the documents' own words back.

The audit letter is answered by passages, so this route returns passages. It
does not summarise them, rank them into a narrative, or put a sentence in front
of them — the reader gets what the corpus says, with the page and the span, and
draws their own conclusion. That is the whole design and the rest of this
docstring is why.

**There is no model in the answer path, and that is not a limitation.**

`evidence/retrieve.py` already answers a plain-English question: the text goes
to `plainto_tsquery`, which stems and drops stopwords, so "where does it say
Moonfare is in euros" and "Moonfare euro denomination" reach the same lexemes.
Layer 1 narrows by holding and by the source's own reliance window in SQL, and
the rerank is a lexicographic tuple over declared preferences — never a score.
A language model would add exactly one thing, query expansion for recall, and
it would add it BEFORE the database, where a bad expansion returns fewer rows
rather than a wrong sentence.

So the model is absent here by construction rather than by caution. The failure
mode this project exists to prevent — a plausible wrong figure that renders,
reconciles and type-checks — cannot be produced by a route whose output is a
verbatim slice of `canonical_text` with computed offsets.

**An empty result is an answer, and it is spelled out.**

`{"passages": []}` rendered as an empty list reads as "nothing here", which is
indistinguishable from a question the corpus never addressed and from a query
that matched no lexeme. `retrieve()` already refuses an empty query loudly;
this route carries the distinction outward in `outcome`, so the pane can say
which of the three happened instead of showing an empty box.

**Why the query is echoed back.**

`retrieve()` substitutes `default_query(requirement)` when no text is supplied,
and a reader who typed nothing should not think their silence was a question.
`query.text` is what actually went to the database and `query.supplied` says
whether it came from the reader.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from api.decisions import named_actors
from api.reconciliation import _connect
from evidence.explain import restate
from evidence.retrieve import RetrievalError, RetrievedPassage, default_query, retrieve
from packages.contracts.enums import RequirementCode
from packages.contracts.glossary import describe, glossed
from policy.from_ledger import load as load_policy
from policy.inputs import Ledger
from policy.requirements import assess_row

lookup_router = APIRouter(tags=["lookup"])

#: How many passages a pane shows. `retrieve()` caps at one passage per claim,
#: so five is five distinct claims rather than one verbose document five times.
DEFAULT_K = 5

#: The ceiling a caller may ask for. Not a performance limit — the corpus is
#: 44,365 characters and the query is sub-millisecond — but a reading limit: a
#: pane that returns thirty passages has stopped answering and started dumping.
MAX_K = 20


def passage_json(p: RetrievedPassage) -> dict[str, Any]:
    """One passage, flattened for the wire.

    `quote`, `span_start` and `span_end` travel together and are not optional.
    A quote without its offsets is a sentence the reader has to trust; with
    them it is a claim they can re-verify against the document, which is the
    only difference that matters here.
    """
    c = p.candidate
    return {
        "claim_id": c.claim_id,
        "claim_key": c.claim_key,
        "holding_id": c.holding_id,
        "document_version_id": c.document_version_id,
        "filename": c.filename,
        "source_class": c.source_class.value,
        "execution_status": c.execution_status.value,
        "issued_date": c.issued_date.isoformat(),
        "page": p.page,
        #: Dumped by the model rather than field-by-field, the way `fact_json`
        #: does it. Naming `span_start` and `span_end` here is what INV-8's
        #: architecture check refuses, and it is right to: a span WRITTEN by
        #: hand is the one construct that can attach a plausible offset to a
        #: passage that does not say it. This one was computed by `locate()`
        #: inside `retrieve()` and is only being copied onto the wire — but a
        #: guard that could tell copying from stating would not be a guard.
        **p.citation.model_dump(mode="json"),
        #: The lexemes that actually matched, so a reader can see WHY this
        #: passage came back. A result list with no account of its own
        #: relevance is a ranking the reader has to take on faith.
        "matched": list(p.matched),
    }


@lookup_router.get("/holdings/{holding_id}/passages")
def find_passages(
    holding_id: str,
    on: Annotated[date, Query(description="measurement date; the source's window applies")],
    requirement: Annotated[RequirementCode, Query(description="which of the letter's requests")],
    q: Annotated[str | None, Query(description="the reader's question, in English")] = None,
    k: Annotated[int, Query(ge=1, le=MAX_K)] = DEFAULT_K,
) -> dict[str, Any]:
    """The passages this holding's documents offer for one requirement.

    404 rather than an empty list for a holding that does not exist: "this
    position has no passage for that question" and "there is no such position"
    are different answers, and the pane must not render them identically.
    """
    conn = _connect()
    if conn is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No ledger is configured, so there are no documents to search. "
                "This route has no fixture: a search that answers from a stub "
                "would be a passage the fund does not hold."
            ),
        )
    with conn:
        known = conn.execute(
            "select count(*) from claim where holding_id = %s", (holding_id,)
        ).fetchone()
        #: `isinstance` rather than `int(...)`: psycopg types every column as
        #: `object`, and coercing here would turn a column that came back as
        #: something unexpected into a plausible zero — which reads as "this
        #: holding has no claims" and 404s a position the fund owns.
        counted = known[0] if known else None
        if not isinstance(counted, int) or counted == 0:
            raise HTTPException(
                status_code=404,
                detail=f"no claims are recorded against {holding_id!r}, so nothing can be searched",
            )
        try:
            found = retrieve(
                conn,
                holding_id=holding_id,
                measurement_date=on,
                requirement=requirement,
                query=q,
                k=k,
            )
        except RetrievalError as exc:
            # Retrieval refuses rather than returning nothing when the query
            # itself is the problem — a text whose every token is a stopword
            # matches no lexeme and would otherwise look like a corpus that
            # holds no answer.
            raise HTTPException(status_code=422, detail=str(exc)) from None

    text = q if q is not None else default_query(requirement)
    return {
        "source": "ledger",
        "query": {
            "text": text,
            "supplied": q is not None,
            "requirement": requirement.value,
            "on": on.isoformat(),
        },
        #: Three outcomes, never collapsed into an empty array. `none_matched`
        #: is the corpus saying it addresses this nowhere; `found` is an
        #: answer. A pane that shows an empty list for the first reads as a
        #: component that failed to load.
        "outcome": "found" if found else "none_matched",
        "passages": [passage_json(p) for p in found],
    }


def row_payload(
    ledger: Ledger,
    holding_id: str,
    on: date,
    requirement: RequirementCode,
    *,
    company: str | None = None,
) -> dict[str, Any]:
    """The row, as the thing a restatement must be a restatement OF.

    Deliberately not glossed. The human meanings for every reason code live in
    `web/src/labels.ts` and copying them here would be a second vocabulary to
    keep in step with the first — and the one that drifts is always the copy
    nobody is looking at. The codes are legible enough to restate from, and the
    claims underneath carry the dates that do the real work.

    ── Two rules learned by reading seventeen restatements ──────────────────

    **An absent fact is omitted, never sent as empty.** Given
    `filed_under_requirements: []` a model wrote "other requirements have
    outstanding document requests" anyway — an empty list is an invitation to
    narrate, and the narration contradicted the very field it came from. A key
    the model never sees is a sentence it cannot write. So every empty list and
    null here is dropped before the payload leaves.

    **An identifier is not a name.** Sent `fund_ii_because_market`, a model
    restated it as "Fund II because of market conditions" — reading an id as
    English and inventing a fund strategy out of a slug. `company` is the
    display name, and where the caller cannot supply one the id is labelled as
    an id rather than left to look like prose.
    """
    row = assess_row(ledger, holding_id, on)
    outcome = row.outcomes[requirement]
    #: Indexed off `ledger.claims` directly. An earlier version reached for a
    #: `claims_for` helper behind a `hasattr` guard, which does not exist — so
    #: every payload would have carried an empty evidence list and the model
    #: would have restated a row with nothing under it, fluently. A missing
    #: attribute must be an import-time error, never a quiet empty dict.
    claims = {c.id: c for c in ledger.claims if c.holding_id == holding_id}
    elsewhere = [
        code.value
        for code, other in row.outcomes.items()
        if code != requirement and other.next_actions
    ]
    payload: dict[str, Any] = {
        "company": company or f"(no display name; the ledger id is {holding_id})",
        "measurement_date": on.isoformat(),
        "requirement": requirement.value,
        "verdict": outcome.verdict.value,
        "verdict_means": (describe("VERDICT", outcome.verdict.value) or {}).get("meaning", ""),
        #: The word the UI prints for this verdict. Sent so the restatement may
        #: name the finding in the product's own language rather than in the
        #: enum's.
        "verdict_label": (describe("VERDICT", outcome.verdict.value) or {}).get("label", ""),
        "requirement_is": (describe("REQUIREMENT", requirement.value) or {}).get("meaning", ""),
        #: Codes WITH their definitions, from the same sentences `labels.ts`
        #: shows the reader. Sent as codes alone, a model guessed that
        #: `SUPPORT_OUTSIDE_ITS_OWN_RELIANCE_WINDOW` meant the window R2 relies
        #: on rather than the window the source document states for itself —
        #: INV-16 inverted, fluently, where no numeral guard can see it.
        "reasons": _safe_glosses("REASON_CODE", list(outcome.reasons), outcome.verdict.value),
        #: Named so it cannot be read as done. Handed a key called
        #: `next_actions`, a model wrote "A request has been filed with
        #: counsel" for a row whose action was REQUEST_FROM_COUNSEL — a step
        #: still owed, rendered as a step taken. That is planned-vs-completed
        #: collapsing, which `INVARIANTS.md` forbids, and neither guard can see
        #: it: no figure, no verdict word. The payload has to make the
        #: misreading unavailable, the same way `asked_elsewhere` did.
        "not_yet_done_someone_must_still_do_these": glossed(
            "NEXT_ACTION", list(outcome.next_actions)
        ),
        #: Named as a sentence, and carrying its own note, because the guard
        #: cannot catch this class of error. `check()` refuses an invented
        #: figure and a verdict the row did not reach; it has no opinion on a
        #: RELATIONSHIP stated wrongly. Asked against a key called
        #: `asked_elsewhere`, a model read the list as "this claim is also
        #: filed under R1" — fluent, plausible, and not what the field means.
        #: The fix is a payload that cannot be misread, not a sterner prompt.
        "other_requirements_with_a_step_still_outstanding": elsewhere,
        "evidence": [
            _claim_json(claims[claim_id])
            for claim_id in outcome.relied_on
            #: A relied-upon claim absent from `ledger.claims` would be a
            #: policy verdict resting on something the ledger does not hold.
            #: Skipping it silently would hide that; it cannot happen, and if
            #: it ever does the payload should be short rather than padded.
            if claim_id in claims
        ],
    }
    if outcome.next_actions:
        payload["note_on_steps"] = (
            "These steps are still outstanding: no one has carried them out and no answer "
            "to them exists. They are what someone must do next. Never describe any of them "
            "as already done."
        )
    if elsewhere:
        payload["note_on_other_requirements"] = (
            "Those other requirements carry an outstanding document request for this same "
            "holding and date. It does not mean the evidence below belongs to them."
        )
    return {k: v for k, v in payload.items() if v not in ([], None, "")}


#: Verdict words in their written forms, for spotting them inside a gloss.
_VERDICT_WORDS = ("sufficient", "insufficient", "partial", "missing", "not applicable")


def _safe_glosses(kind: str, codes: list[str], verdict: str) -> list[dict[str, str]]:
    """Definitions, minus any that name a verdict this row did not reach.

    `DOCUMENT_WITH_COUNSEL` means "Existence and cost is partial, not missing."
    That is a good sentence for a reader and a trap for a model: handed it on a
    `partial` row, the model repeats "not missing", and the verdict guard —
    correctly, knowing nothing of provenance — refuses the whole restatement.
    Five of seventeen rows refused this way, all of them rows whose own payload
    set the trap.

    The label always travels; only the sentence that would be refused is
    dropped. Nothing is reworded, because a second wording is the thing the
    generated glossary exists to prevent — this is a subset of the same
    sentences, never a paraphrase of them.
    """
    out: list[dict[str, str]] = []
    for entry in glossed(kind, codes):
        meaning = entry.get("meaning", "")
        foreign = [
            w
            for w in _VERDICT_WORDS
            if w != verdict.replace("_", " ")
            and re.search(rf"(?<!in)\b{w}\w*", meaning, re.IGNORECASE)
        ]
        out.append({k: v for k, v in entry.items() if not (k == "meaning" and foreign)})
    return out


def _claim_json(claim: Any) -> dict[str, Any]:
    """One relied-upon claim, with meaningless values left out.

    `execution_status` is dropped when it is `not_applicable`. It is a property
    of a DOCUMENT — signed, unsigned, pro forma — and an exchange quote has no
    such property, so the enum says `not_applicable`. Handed that verbatim, a
    model wrote that "the settlement terms are not applicable", which is a
    sentence about the fund's position rather than about the document, and
    reads as a finding. A field with nothing to say is better unsaid.
    """
    out = {
        "source_class": claim.source_class.value,
        "issued_date": claim.issued_date.isoformat(),
    }
    if claim.execution_status.value != "not_applicable":
        out["execution_status"] = claim.execution_status.value
    return out


#: The restatement is the only route in this service that COSTS MONEY per
#: request. Every other one is a read against Postgres; this one calls a paid
#: model, and on a public deployment an unauthenticated GET that spends money
#: is an endpoint anyone can loop.
#:
#: So it is off unless the deployment names its actors, exactly as `/decisions`
#: is and for a related reason: the public read-only surface offers what can be
#: served for free, and the private demo — which already declares who may act —
#: is where the assistant lives. Reusing `DECISION_ACTORS` rather than adding a
#: second switch keeps "is this the private deployment?" a question with one
#: answer.
def _assistant_is_offered() -> bool:
    return bool(named_actors())


@lookup_router.get("/holdings/{holding_id}/explain")
def explain_row(
    holding_id: str,
    on: Annotated[date, Query(description="measurement date")],
    requirement: Annotated[RequirementCode, Query(description="which of the letter's requests")],
) -> dict[str, Any]:
    """This row, restated in plain English — or the reason there is no paragraph.

    Both outcomes are 200. The pane renders the structured row either way and
    this is the sentence above it, so a refusal is a reader who learns nothing
    new rather than a page that failed. `refusal` is carried out verbatim
    because "no model is configured" and "the model stated a figure the record
    does not hold" are different facts about the deployment, and collapsing
    them into an empty pane hides the second.
    """
    if not _assistant_is_offered():
        raise HTTPException(
            status_code=404,
            detail=(
                "This deployment does not offer the plain-English restatement. It calls a paid "
                "model per request, so it is enabled only where DECISION_ACTORS names who is "
                "using the system. Every read route, and the passage search, are unaffected."
            ),
        )
    conn = _connect()
    if conn is None:
        raise HTTPException(status_code=503, detail="no ledger is configured")
    with conn:
        #: `display_name`, which is what the column is called. An earlier
        #: version guessed `name` and 500'd on every request for a week of
        #: this session — invisible because no test called this route and the
        #: measurement harness called `row_payload` directly, skipping the SQL.
        #: `api/routes.py` already had the correct query; reuse-first would have
        #: prevented the guess.
        named = conn.execute(
            "select c.display_name from holding h join company c on c.id = h.company_id"
            " where h.id = %s",
            (holding_id,),
        ).fetchone()
        if named is None:
            raise HTTPException(
                status_code=404,
                detail=f"no holding {holding_id!r} in this ledger",
            )
        payload = row_payload(
            load_policy(conn),
            holding_id,
            on,
            requirement,
            company=str(named[0]),
        )
    explanation = restate(payload)
    return {
        "source": "ledger",
        "row": payload,
        "outcome": "explained" if explanation.accepted else "refused",
        "text": explanation.text,
        "refusal": explanation.refusal,
        "model": explanation.model,
    }
