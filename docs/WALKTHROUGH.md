# The five-minute walkthrough

Written down because scripting it is worth more than another feature: it is what
guarantees the strongest three minutes are the ones actually shown. Handoff
item 8.

Read once before presenting. During the demo, follow the **bold** lines only.

---

## Before anyone is watching

1. **Wake the API.** Render's free tier sleeps after 15 minutes idle and takes
   about 50 seconds to come back. Hit `/<api>/ready` five minutes before, and
   again one minute before. A cold start during the opening sentence costs the
   whole first minute.
2. **Load the packet once.** The first `GET …/packet` is the slow one; after it
   the pages are warm.
3. **Check `DECISION_ACTORS` and `VITE_DECISION_ACTORS` are both set and equal.**
   If only one is set, the approve control renders and every decision comes back
   403 — which on screen is hard to tell from the database refusing, and that is
   the one moment this walkthrough exists to reach. See `.env.example`.

   Verified: with both set and equal, `POST /decisions` returns **409** and the
   database's own sentence; with `DECISION_ACTORS` unset it returns **403** and
   a sentence about actors. Two different codes and two different messages, so
   the two states ARE distinguishable — but only if you read the message, which
   is why this check is on the list.
4. **Check the source badge says `ledger`, not `fixture`.** With
   `VITE_API_BASE_URL` unset the app serves a one-holding, 5,000,000 stub and
   labels it — but a viewer who does not read the badge is reading a stub as the
   fund.
5. Have `#/fund_ii/fund_ii_25q4/company/fund_ii_lucra/R2` in the clipboard as a
   fallback. If navigation goes wrong, one paste returns to the strongest screen.

---

## The path

### 0 · What am I looking at (20 seconds)

**Open the dashboard on Fund II, 24Q4.**

Say: this is a venture fund's valuation marks at one measurement date, and for
each one the evidence supporting it. The client is the audit firm; the letter
they sent asks four things, and the columns answer them.

Point at the total's caption. It does not say "total" — it says what it is a
total *of*, and whether it contains unsupported inputs. Nothing on this screen
is a figure without a qualification attached.

### 1 · Jackpocket — an answer that is not a gap (40 seconds)

**Click Jackpocket.**

The position was sold in May 2024. It is still in the packet, because the letter
asks for realised investments by name — and it has **no mark**, because it was
not held at 31 December. The screen says "no mark at this date" rather than
leaving a blank cell, because on a screen of amounts a blank reads as zero.

**Click R4 · realization support.** It opens on the gross consideration,
$3,100,000, and the passage beside it is the merger notice stating it.

**Click R1 · existence and cost.** It is `not applicable`, and the screen says
so in words: the requirement does not arise, and *that is not a gap*. Existence
and cost of something no longer held is not what the letter asks for.

That distinction — "does not arise" against "nobody looked" against "we looked
and it is missing" — is three different findings, and most systems render them
identically.

### 2 · Lucra — following a figure to the sentence (60 seconds)

**Switch the period to 25Q4. Click Lucra.**

The mark is $2,250,000.

**Click R2 · fair-value support.** It opens on the price per share, **$2.00**,
from the Series A-1 term sheet. The pane on the right is the stored document
with those exact characters highlighted — not a search result, and not the
quote alone: the offsets are the citation, and a Postgres trigger refuses to
store a citation whose offsets do not select the stored text.

Point at `chars 344–…` under the filename. That is what an auditor uses to find
the passage again by hand.

**Press "Show the whole document."** The highlight stays where it is inside the
full extracted text. The pane defaults to the lines around the citation because
the document is 2,000 characters and the citation is 62 — but nothing is hidden,
and the surrounding page is one click away.

**Click R1 · existence and cost.** A different window and a different figure:
the fund's $1,500,000 commitment. The ledger binds a *document* to a
requirement, so one term sheet answers both — the API says which *figures*
answer which request, so the two questions do not show the same twelve numbers.

**Press "Copy a link to this passage."** That link opens on this exact figure in
this exact document. A partner sends the sentence, not directions to it.

### 3 · Fluidstack — the number that is wrong (60 seconds)

**Click Fluidstack.** Reported: **$6,000,000**.

Beside it, under "Recomputed from the evidence": **$2,500,000**, and
**$3,500,000 apart from the reported figure**.

Read the working out loud. The fund holds 100,000 Series A at $10.00 and 100,000
Series A-2 at $15.00. That is 2,500,000. The reported 6,000,000 is 200,000
shares priced at $30.00 — the Series B price — applied to *every* class.

This is the whole argument. A wrong number in fund valuation is plausible: it
renders, it reconciles to itself, and it passes every type check. Nothing
catches it except an independent derivation from the cited evidence, and the
label is careful — it says **derived**, not *validated*. Nothing here has been
approved by anyone, and the ledger's own validated amount is still empty.

Say the honest part: this check could not run at all until the Series A-2 price
was bound to the requirement it supports. Withholding evidence from a check does
not make the check strict, it makes it silent.

### 4 · Anthropic — the database refusing an approval (60 seconds)

> **READ THIS BEFORE PRESENTING — the refusal does not currently say what this
> section was written to promise.**
>
> `pbc_requirement`, `evidence_assessment` and `evidence_link` are empty in the
> `demo` schema: nothing outside `tests/test_schema_approval.py` writes them, so
> the verdicts are computed on read and stored nowhere. The approval constraint
> reads the stored ones.
>
> The consequence, verified by clicking: **every** approval attempt — supported
> or not — is refused with
>
>     The ledger refused this decision: INV-10: valuation approval 7 names no
>     evidence set. Nothing was recorded.
>
> That is a real Postgres refusal, rendered verbatim, and it is a 409. But it is
> a plumbing sentence, not the audit finding, and the intended line —
> `0003_approval_prerequisites.sql`'s "cites no sufficient existence-and-cost
> assessment" — cannot fire, because the empty-set check rejects first. An
> ACCEPTED approval is likewise unreachable.
>
> **Until an assessment run populates those tables, present this section as
> written below and do not promise the existence-and-cost sentence.** The
> honest version still lands; it is just a smaller claim.

**Click Anthropic.** Reported: $8,000,000. R2 is `insufficient`. The only
evidence on file is a press article, and the trail shows why: "$120 Billion",
"according to three people familiar with the matter", "has not independently
reviewed the transaction documents". Beside the reported figure, the
recomputation says **the evidence does not say** — the documents on file state
no price per share at all.

**Scroll to Approval state. Choose an actor, choose "valuation", press
approve.**

It is refused, and the refusal is quoted verbatim on screen. It comes from a
Postgres constraint, not from a form check and not from a rule in the browser.

Say it plainly: the guarantee is not that the UI asks nicely. It is that a
client with a connection string cannot write this row either — the check runs on
the side that decides what commits, and the browser only reports what came back.

If asked what the message means, answer honestly: the approval names no stored
evidence set, because this deployment computes its verdicts on read and has not
yet written an assessment run. The constraint that would name the *insufficient
requirement* is in the schema and is one table-population away.

### 5 · What is missing, and who to ask (40 seconds)

**Open the Gap inventory.**

Every absence, with the *kind* of absence attached — with counsel, referenced
but not located, never located — because that decides who the letter goes to. A
document sitting with counsel and a document nobody can find read identically in
most systems and require opposite actions.

**Point at Because Market.** One of fourteen holdings, three measurement dates,
no document of any kind. It reads zero across every column and it is not hidden
or footnoted. A page that buries its worst row is a page a reader should
discount entirely.

---

## If asked

**"How do I know the citation is the right passage?"** You do not, yet, and the
system says so. What is proved is that the offsets select the stored quote —
enforced in Python, by two database triggers, and again on export. Whether the
*right* sentence was selected is checked by a hand-transcribed corpus manifest
that is being built independently of the extractors, and until it lands this is
a stated blind spot rather than a claim.

**"Why isn't the derived figure just stored?"** Because an approval is bound to
a mark revision, an evidence set and a policy version, so an approved total
cannot follow a figure that moves. Writing a read-time derivation into the
stored column reopens exactly that question. It is a design decision that has
not been made, not an oversight.

**"Is this an LLM product?"** A model tier proposed five figures on one document
and the citation binding accepted three. One refusal was the price the claim is
priced from, because the quoted passage ended in a comma and the value could not
be read as a whole figure inside it. The guardrail refusing the model is the
feature.

---

## What NOT to do

- Do not open a company before the dashboard. The scorecard is what makes the
  per-company screens legible.
- Do not narrate the schema. The Anthropic refusal *is* the schema, and it lands
  in five seconds where a description takes two minutes.
- Do not apologise for Because Market's zeroes. Volunteering the weak numbers is
  what makes the strong ones believable.
