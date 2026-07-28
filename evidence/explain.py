"""Restating one row in plain English, under a guard that can refuse it.

The vocabulary in `web/src/labels.ts` is careful and it is hidden: 99 `title=`
attributes hold definitions that never appear on a touch device, never survive
a screenshot, and have to be suspected before they can be read. This is the
other way to close that gap — not 99 hand-written sentences, but the row's own
fields restated for the reader who is looking at it.

**The rule this module exists to enforce.**

A wrong number here is plausible. It renders, it reconciles to itself, and it
passes every type check — which is the whole reason this project pins
correctness to artefacts that can fail rather than to assertion. A language
model writing prose about valuations is the most efficient machine ever built
for producing plausible wrong numbers, so it is not trusted; it is bounded.

`evidence/extract.py` established the shape of the bound and this follows it.
There, the model returns a quote and a value and NEVER an offset, so the span
is computed and a misattached figure is a refusal rather than a row. Here the
model returns prose and never a fact, and the guard is arithmetic:

    every digit-run in the output must already appear in the input payload.

That is checkable, total, and indifferent to how the sentence is phrased. A
model that computes a percentage, annualises a return, sums two lots or simply
mistypes a figure produces a numeral the payload does not contain, and the
answer is thrown away. It cannot be argued with, because it is not a judgement
about whether the sentence reads well.

**The second guard is about conclusions rather than figures.**

A restatement that says "sufficient" about an insufficient row is wrong in a
way no numeral check would catch, and it is exactly the sentence a fluent model
writes when the reasons are complicated. So the closed vocabularies are
enforced too: a verdict word that is not this row's verdict is a refusal.

**What the numeral guard does NOT catch, stated rather than implied.**

An adversarial pass walked through it, and the holes are real. It compares
DIGITS, so a figure spelled out ("two million dollars"), a magnitude or unit
change on a figure that IS in the payload ("$2.00 million", "2.00%", "-2.00"),
and a date component reused as money or a percentage ("$2,024" against a
measurement year of 2024, "rose 12%" against a May date) all pass. It also
cannot see a state inverted without any number at all — "a request has been
filed" about a step nobody has taken.

So it is a guard against digit-typos and digit-arithmetic, which is what it was
built for, and not a guarantee of truthfulness. The mitigations for the rest are
in the PAYLOAD rather than here: fields are named so the misreading is
unavailable, and empty ones are omitted so there is nothing to narrate. That is
a weaker promise than "the model cannot be wrong", and it is the promise this
actually keeps.

**Refusal is never a blank pane.** The structured row is already rendered and
is already complete; this adds a paragraph above it or it adds nothing. That
asymmetry is what makes the feature safe to ship — the failure mode is a reader
who learns nothing new, not a reader who learns something false.

**What it is never asked.** Whether the mark is right, whether the evidence is
enough, whether the fund should mark up. The first two are `policy/` and it
answers them deterministically; the third belongs to the fund. A refusal to
answer those is a designed response, not a limitation to apologise for.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from packages.contracts.enums import RequirementVerdict

#: A run of digits with the separators a figure wears. `1,250,000` and `3.20`
#: are one numeral each rather than three and two — split on the separator and
#: an invented `$1,250,000` would pass against a payload holding `250`.
NUMERAL = re.compile(r"\d[\d,.]*")

#: How long a restatement may run. Not a style rule: the guard is only as good
#: as a reader's willingness to check the paragraph against the row beneath it,
#: and nobody checks nine sentences.
#:
#: Raised from 900 after measurement. Giving the model the reason-code
#: DEFINITIONS rather than the bare codes made it write longer — correctly
#: longer, because a definition explained is a sentence more than a code named
#: — and three of five refusals in that run were this cap rather than anything
#: wrong with the text. A ceiling that mostly rejects good output is not a
#: guard, it is a defect with a principled comment attached.
MAX_CHARS = 1400


#: Restating is the cheap tier, deliberately, and it is a DIFFERENT choice from
#: `extract.py`'s.
#:
#: Extraction is asked to notice a figure buried in prose, and a figure it does
#: not notice is a fact the ledger never gets — so there, model strength buys
#: recall of things that would otherwise be missing, and the strong model is
#: worth its cost on a job that runs at ingestion time and is then cached
#: forever in a fixture.
#:
#: This runs on every pane view, and it is asked to restate a payload that is
#: already in front of it. There is nothing to notice. The guard above rejects
#: an invented figure and a wrong verdict whatever wrote them, so a weaker model
#: cannot buy correctness here — there is no correctness left to buy. What it
#: costs is the REFUSAL RATE: a less careful model writes a sentence that trips
#: the numeral check more often, and the reader sees the structured row with no
#: paragraph over it.
#:
#: That is the right direction to fail in, and it is why this is safe to make
#: cheap. Override with `OPENROUTER_EXPLAIN_MODEL` if the refusal rate turns out
#: to be annoying in practice; the guard does not care which model answers.
EXPLAIN_MODEL = "anthropic/claude-haiku-4.5"

#: The restatement is capped at `MAX_CHARS` and refused above it, so paying for
#: tokens past that ceiling buys nothing but a longer refusal. Roughly four
#: characters to the token, with headroom.
MAX_TOKENS = 500


#: Every written form of each verdict, keyed by the enum value.
#: `not_applicable` is never typed with its underscore by anyone writing prose.
_VERDICT_FORMS: dict[str, str] = {
    "sufficient": r"(?<!in)\bsufficien\w*",
    "insufficient": r"\binsufficien\w*",
    "partial": r"\bpartial\w*",
    "missing": r"\bmissing\b",
    "not_applicable": r"\bnot[_ ]applicable\b",
    "not_assessed": r"\bnot[_ ]assessed\b",
    "conflicting": r"\bconflicting\b",
}


#: A step described as already taken. `INVARIANTS.md` forbids collapsing
#: planned into completed, and this is that collapse in prose: "a request has
#: been filed with counsel" about a row whose only action is REQUEST_FROM_
#: COUNSEL — a step nobody has started.
#:
#: Neither other guard can see it. There is no figure and no verdict word; the
#: sentence is fluent, plausible and exactly what a helpful writer produces from
#: a list of actions. So it gets its own check, and the check is the regex that
#: FOUND it during measurement rather than a new one written to look thorough.
#:
#: This can only be sound because the payload never says any of these words in
#: the completed sense — see `row_payload`, where the field naming was changed
#: so that "filed" does not appear at all. A guard that forbids a word the
#: payload itself uses would refuse honest echoes forever.
_STEP_CLAIMED = re.compile(
    r"\b(?:has|have|was|were)\s+(?:been\s+)?"
    r"(?:filed|sent|submitted|requested|issued|made|obtained|received|dispatched)\b",
    re.IGNORECASE,
)


#: A negation close enough in front of a completion verb to reverse it.
_NEGATED = re.compile(r"\b(?:no|not|nothing|nobody|none|never|neither|yet)\b", re.IGNORECASE)


#: A magnitude or unit attached to a figure. `2.00` is in the payload and
#: "2.00 million" is a different quantity by six orders of magnitude — the
#: numeral check compares digits and cannot see the word beside them. Same for
#: a percentage, a multiple or a sign flip.
_SCALED = re.compile(
    r"\d[\d,.]*\s*(?:%|percent|million|billion|trillion|thousand|bn\b|mm\b|k\b|x\b|bps\b)",
    re.IGNORECASE,
)

#: A step described as finished, in the shapes a writer actually uses. The
#: passive "has been filed" was the first and the narrowest; an adversarial
#: pass walked round it with "has completed the request" and "is now on file".
#: A regex over completion language is bypassable in principle and this is not
#: pretending otherwise — see the module docstring. It closes the phrasings a
#: model actually produces from a list of outstanding actions.
#: Split by grammar, because the two halves are not equally decisive.
#:
#: The perfect and passive forms assert the act happened. The bare present
#: ("a decision is made") does not — it is how a writer describes the step
#: itself, and matching it refused two correct restatements that said only what
#: must happen next. So `made` and its siblings appear only after has/have/
#: was/were, and the present tense is limited to states that cannot be read as
#: future ("is now on file").
_STEP_DONE = re.compile(
    r"\b(?:"
    r"(?:has|have|was|were)\s+(?:been\s+|now\s+)?"
    r"(?:filed|sent|submitted|requested|issued|made|obtained|received|dispatched"
    r"|completed|provided|delivered|answered|returned|resolved|satisfied|done)"
    r"|(?:is|are)\s+now\s+(?:on file|in hand|in place|available|complete|completed)"
    r"|(?:has|have)\s+(?:completed|fulfilled|actioned|closed)"
    r"|no longer outstanding|already (?:filed|sent|requested|received)"
    r")\b",
    re.IGNORECASE,
)


class Refused(RuntimeError):
    """The restatement was not accepted, and the reason names what failed."""


@dataclass(frozen=True)
class Explanation:
    """An accepted restatement, or the refusal that replaced it."""

    text: str | None
    refusal: str | None
    model: str

    @property
    def accepted(self) -> bool:
        return self.text is not None


def numerals(text: str) -> set[str]:
    """Every figure-shaped token in `text`, normalised for comparison.

    Trailing separators are stripped because a numeral at the end of a sentence
    picks up the full stop: `3.00.` and `3.00` are the same figure, and treating
    them as different would refuse correct output. Commas are removed so that
    `1,250,000` and `1250000` compare equal — a model that reformats a figure it
    read from the payload has not invented one.
    """
    out: set[str] = set()
    for match in NUMERAL.finditer(text):
        token = match.group(0).rstrip(".,").replace(",", "")
        if token:
            out.add(token)
    return out


def _payload_text(payload: Mapping[str, Any]) -> str:
    """The payload as one string, so nested values are searched too.

    Serialised rather than walked: a hand-written walk has to know which keys
    hold figures, and the first key it does not know about is a numeral the
    guard would wrongly reject — or, worse, a shape change that silently
    narrows what the guard compares against.
    """
    return json.dumps(payload, sort_keys=True, default=str)


def check(text: str, payload: Mapping[str, Any]) -> None:
    """Accept the restatement, or raise `Refused` naming exactly what failed.

    Order matters only for the message a human reads; every check is total.
    """
    if not text.strip():
        raise Refused("the model returned nothing")
    if len(text) > MAX_CHARS:
        raise Refused(f"the restatement runs to {len(text)} characters, over the {MAX_CHARS} cap")

    #: A figure the record holds, wearing a magnitude the record does not.
    payload_scaled = {
        m.group(0).lower().replace(" ", "") for m in _SCALED.finditer(_payload_text(payload))
    }
    for match in _SCALED.finditer(text):
        if match.group(0).lower().replace(" ", "") not in payload_scaled:
            raise Refused(
                f"the restatement states {match.group(0)!r}. The digits may be in the record but "
                "the magnitude is not, and a figure scaled by a word beside it is a different "
                "figure."
            )

    known = numerals(_payload_text(payload))
    invented = sorted(numerals(text) - known)
    if invented:
        raise Refused(
            f"the restatement states {', '.join(invented)}, which the row does not contain. "
            "A figure that is not in the record is not a restatement of it."
        )

    #: A step the row lists as outstanding, described as done. Checked only
    #: when the row HAS outstanding steps: a row with none cannot make this
    #: mistake, and "the settlement was made in August" about a completed
    #: acquisition is a true sentence the guard must not eat.
    if payload.get("not_yet_done_someone_must_still_do_these"):
        #: Negation-aware, or the guard eats the correct sentence. The payload
        #: tells the model nobody has sent these steps, and "nothing has been
        #: sent" is precisely what a good restatement says — matching it would
        #: refuse the right answer and accept only silence.
        claimed = next(
            (
                m
                for m in _STEP_DONE.finditer(text)
                if not _NEGATED.search(text[max(0, m.start() - 32) : m.start()])
            ),
            None,
        )
        if claimed is not None:
            raise Refused(
                f"the restatement says a step {claimed.group(0)!r} when the record lists it as "
                "still outstanding. A step nobody has taken, described as taken, is the one "
                "error here that no figure check can see."
            )

    #: The row's own verdict is the only one that may be named — in ANY of the
    #: forms a writer would actually use.
    #:
    #: The first version matched `\b<enum value>\b`, case-sensitively, and an
    #: adversarial pass walked through it four ways: "Sufficient" at the start
    #: of a sentence, "not applicable" with a space where the enum has an
    #: underscore, "partially" and "sufficiency" as derived forms, and every
    #: synonym. The first three are now closed. Synonyms are not, and cannot be
    #: by this method — see the module docstring, which says so rather than
    #: implying a completeness this does not have.
    #:
    #: `(?<!in)` on the `sufficient` stem is what keeps `insufficient` from
    #: reading as its own opposite. Refusing more than before is the intended
    #: direction: a row whose gloss legitimately contains another verdict word
    #: costs a paragraph, and a row restated under the wrong finding costs the
    #: reader the finding.
    verdict = str(payload.get("verdict", ""))

    #: The restatement must NAME the row's finding, not merely avoid naming a
    #: different one. Forbidding foreign verdict words leaves "the support meets
    #: the requirement" on an insufficient row untouched: no guarded token
    #: appears, and the finding is inverted in the reader's own language. A
    #: positive requirement closes most of that — a paragraph that never reaches
    #: this row's conclusion is not a restatement of this row. Synonyms remain
    #: reachable in principle and the docstring says so.
    #: The enum word OR the label the UI shows for it. "The evidence is out of
    #: date" is how `labels.ts` says `missing` for an expired reliance window,
    #: and refusing it would demand the reader be told the machine's word for a
    #: finding rather than the product's own. Both name the conclusion; only
    #: silence about it does not.
    own = _VERDICT_FORMS.get(verdict, rf"\b{re.escape(verdict)}\b") if verdict else None
    label = str(payload.get("verdict_label") or "")
    named_by_label = bool(label) and label.lower() in text.lower()
    if own is not None and not named_by_label and not re.search(own, text, re.IGNORECASE):
        raise Refused(
            f"the restatement never says the finding is {verdict!r}. A paragraph that does not "
            "reach the row's own conclusion is not a restatement of it."
        )

    for word in (v.value for v in RequirementVerdict):
        #: `.get` with the escaped word as the fallback. A verdict added to the
        #: enum and not to the table above must still be checked, in its own
        #: plain form, rather than raising KeyError inside a guard — a guard
        #: that crashes on an unfamiliar input is a guard that stops running.
        pattern = _VERDICT_FORMS.get(word, rf"\b{re.escape(word)}\b")
        if word != verdict and re.search(pattern, text, re.IGNORECASE):
            raise Refused(
                f"the restatement calls this {word!r} and the row is {verdict!r}. "
                "A conclusion the record does not reach is not a restatement of it."
            )


def accept(text: str, payload: Mapping[str, Any], *, model: str) -> Explanation:
    """Run the guard and package the outcome. Never raises.

    The caller is a route rendering a pane, and a refusal is a normal answer
    there rather than an error: the structured row underneath is already
    complete, so the worst case is a reader who learns nothing new.
    """
    try:
        check(text, payload)
    except Refused as exc:
        return Explanation(text=None, refusal=str(exc), model=model)
    return Explanation(text=text.strip(), refusal=None, model=model)


SYSTEM = """You restate one row of an audit-support record in plain English.

You are not an analyst. You never decide whether a valuation is right, whether \
evidence is sufficient, or what a position is worth — the record already \
states its own conclusion and your job is to make that conclusion readable.

Rules, all of which are checked after you answer:

1. Never state a number that does not appear in the payload. Do not compute, \
sum, annualise, convert or round anything. If a figure is not in the payload, \
it does not belong in your answer.
2. Never use a verdict word other than the row's own.
3. Write three or four sentences, in the second person, for a reader who knows \
what a fund is but not what this system's terms mean.
4. Say what the finding is, what it rests on, and what happens next. If the \
payload says a request is filed under another requirement, say so.
5. No jargon without a definition in the same sentence. Terms of art like \
"pro forma" stay — define them inline rather than replacing them.
6. If the payload does not carry what you would need, say which field is \
absent and stop there. "The record gives no reason code for this, so I cannot \
say what is short" is a correct and useful answer. Filling the gap with \
something plausible is the one thing you must never do.
6a. Write about what IS in the payload and nothing else. If a key is not \
there, it has no value to report and you must not mention the subject at all. \
Do not say other requirements have outstanding requests unless the payload \
lists them; do not describe what a document contains beyond what the payload \
says it contains.
6b. Plain paragraphs only. No headings, no bullet lists, no bold — this is \
read as a short note above a table, not as a report.
7. If asked whether the mark is right, whether the evidence is enough, or what \
the position is worth: decline and say why. The first two are decided by the \
policy layer and are already in the payload; the third is the fund's judgement \
and not yours.
"""


def prompt_for(payload: Mapping[str, Any]) -> tuple[str, str]:
    """The system and user messages. Separated so the fingerprint can hash both."""
    return SYSTEM, json.dumps(payload, indent=2, sort_keys=True, default=str)


def restate(payload: Mapping[str, Any], *, model: str | None = None) -> Explanation:
    """One live call, guarded. Never raises — a refusal is the answer.

    Shares `extract.py`'s endpoint, provider pin and temperature, because two
    model clients in one repository is two places for a reproducibility control
    to be set differently. `httpx` is imported inside the call for the reason
    given there: the runtime install does not carry it, and a module that
    cannot be imported without it would take the guard down with it.

    An unreachable model, a missing key and a refused restatement are the same
    outcome to the caller — a pane with no paragraph over a row that is already
    complete — but they are different SENTENCES, because "no model is
    configured" and "the model stated a figure the record does not hold" would
    otherwise be one shrug.
    """
    from api.config import load_env
    from evidence.extract import ENDPOINT, PROVIDER

    env = load_env()
    #: NOT `OPENROUTER_MODEL`. That variable steers extraction, where the strong
    #: model earns its cost in recall; pointing both at one setting would mean
    #: making this pane cheaper silently degrades what the ledger extracts.
    chosen = model or env.get("OPENROUTER_EXPLAIN_MODEL") or EXPLAIN_MODEL
    key = env.get("OPENROUTER_API_KEY")
    if not key:
        return Explanation(
            text=None,
            refusal="No model is configured, so this row has no plain-English restatement.",
            model=chosen,
        )

    system, user = prompt_for(payload)
    #: Imported before the request rather than inside the try, so "httpx is not
    #: installed" and "the model was unreachable" stay different answers. The
    #: first is this host missing a development dependency; the second is the
    #: network. A single `except Exception` reported both as the same shrug and
    #: needed a suppression comment to survive lint — and this repo holds
    #: suppressions at zero for exactly this reason: the broad catch was hiding
    #: a distinction, not handling one.
    try:
        import httpx
    except ImportError:
        return Explanation(
            text=None,
            refusal="httpx is not installed on this host, so no model can be called.",
            model=chosen,
        )

    try:
        response = httpx.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": chosen,
                "temperature": 0,
                "max_tokens": MAX_TOKENS,
                "provider": {"order": [PROVIDER], "allow_fallbacks": False},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        #: Every transport and protocol failure httpx raises descends from
        #: this: timeouts, DNS, refused connections, malformed responses. A
        #: narrower list would let one of them escape as a 500 from a route
        #: whose whole contract is that a failure is a pane with no paragraph.
        return Explanation(
            text=None, refusal=f"the model could not be reached: {exc}", model=chosen
        )

    if response.status_code != 200:
        return Explanation(
            text=None,
            refusal=f"the model returned {response.status_code}",
            model=chosen,
        )
    try:
        choice = response.json()["choices"][0]
        content = choice["message"]["content"]
        #: A response stopped by the token ceiling is a paragraph that ends
        #: mid-sentence, and every guard here passes it: the figures are real,
        #: the verdict is right, the length is under the cap. Only the model
        #: knows it was cut off, and it says so here.
        if choice.get("finish_reason") == "length":
            return Explanation(
                text=None,
                refusal=(
                    "the model ran out of room and stopped mid-sentence, so what it wrote is "
                    "not a complete restatement"
                ),
                model=chosen,
            )
    except (KeyError, IndexError, TypeError, ValueError):
        return Explanation(text=None, refusal="the model returned no content", model=chosen)
    if not isinstance(content, str):
        return Explanation(text=None, refusal="the model returned no content", model=chosen)
    return accept(content, payload, model=chosen)
