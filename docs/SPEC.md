# SPEC — 7GC OS: Valuation Evidence Ledger

**Revision 4.** Incorporates Spec Pass B, two fix-verify cycles, and the
cross-family diagnosis review. Companions: `docs/ORACLE.md` r4 ·
`INVARIANTS.md` r4 · generated expectations in `evals/oracle/derived.md`.

Scope changes after this point are a separate reviewed change.

---

## 1. What this is

Function **#7 Audit support** — *"Documenting which evidence supports each change
in valuation for each holding."*

> **Select fund + company + measurement date → assemble evidence → extract cited
> facts → validate support → human approves or rejects → export a reproducible
> auditor packet.**

The Harwell & Kent PBC letter asks 7GC to **provide** support *"organized by
portfolio company."* The deliverable is the assembled package; identified gaps
are its honest residue. A system reporting only gaps under-delivers exactly as
badly as one reporting all green.

### 1.1 Two projections over one ledger

**[r2]** r1 said "neither view is derived from the other in the UI," which could
have been read as two separately computed client-side models that drift.
Corrected: **change view** and **position-date view** are separate API
projections over the same canonical marks, evidence and policy results. Neither
UI surface reads the other's rendered output or local state. Every shared
calculation is implemented once, in backend policy code.

---

## 2. Scope

- Both funds, all 14 positions, all 20 documents.
- **[r2] Packet date set is closed**: Fund II 12/31/2023, 12/31/2024, 12/31/2025;
  Fund I FY2023, FY2024, FY2025. **Exactly these six.** Fund I FY2021–FY2022 and
  Fund II 24Q2/25Q2/25Q3/26Q1 are ingested, appear in the change view and ledger
  lineage, and are **excluded** from packet generation and PBC completeness
  (INV-20). "Focus" no longer appears in this document.
- Deployed and publicly reachable. Seeded and resettable.
- Blueprint (≤3pp), scope/roadmap note (1p).

### Out of scope, with trigger

| Excluded | Trigger |
|---|---|
| Drive / Gmail connectors | documents arrive continuously rather than as a fixed pack |
| Live web search | **[r2]** never in this build; Step 7 processes only the fixed press artifact in fixtures |
| LangGraph | a run must pause and resume days later from an inbound event |
| RBAC / production identity | **[r2]** see §3.1 — the public surface is read-only, so this is not triggered by public reachability |
| Embeddings / pgvector | **[r2]** Recall@5 on the locked gold set improves by ≥5 percentage points over FTS at no more than 2× cost |
| Autonomous sending | **[r2]** permanently prohibited — moved to INV-14, not a build trigger |
| Multi-agent swarm | not planned |
| Graph database | not planned |

### Deliberate extensions beyond the literal ask

1. **The letter is Fund II only.** We apply the same categories to Fund I,
   because the case study asks for a platform. Stated in the Blueprint.
2. **Management assessment drafts.** No such memo exists for any unchanged
   position. The system drafts what the letter asks *management* to author, which
   is why INV-14 and INV-18 are load-bearing rather than polish.

---

## 3. Deployment

| Layer | Service | Free-tier behaviour |
|---|---|---|
| Postgres + Storage | Supabase | never expires; pauses after 7 days idle |
| FastAPI | Render web service | spins down after 15 min idle |
| React/Vite | Vercel Hobby | always awake; free per-PR previews |

**Do not use Render Postgres** — free instances expire 30 days after creation and
are deleted 14 days later.

### 3.1 Public surface is read-only — **[r2] new**

r1 said "publicly reachable" and "human approves or rejects" without stating who
may mutate. Anyone could have altered audit state and forged an approval log.

- The **public** deployment carries synthetic case-study data and is
  **read-only**. Approve, reject, reset and export endpoints are disabled.
- A **private** demo deployment uses named actors. Every approval records actor
  ID, timestamp, target revision and evidence-set hash.
- Production identity and RBAC remain out of scope; this is not a substitute.

### 3.2 Health endpoints — **[r2] split**

r1's single `/health` conflated liveness, readiness and keep-warm, and could have
returned 200 while the database was down.

- `GET /live` — API process only.
- `GET /ready` — executes `SELECT 1` with a 2s timeout; 200 only on success, 503
  otherwise. **Never converts a failure to 200.**

The keep-warm cron calls `/ready` every 12 minutes, which resets both the Render
spin-down and the Supabase pause timers. Cron failures are observable.

---

## 4. Repository layout

```
supabase/migrations/   schema; frozen after Step 0
packages/contracts/    typed models + generated frontend types; frozen
fixtures/              canonical payloads incl. the full Dream slice
ingest/trackers/       both workbooks → canonical rows; reconciliation
ingest/documents/      pdftotext, page split, hash, chunk, rule classify
evidence/              retrieval + cited extraction
policy/                requirements, sufficiency matrix, validators
api/                   typed state machine, review tasks, approvals
web/                   dashboard, workspace, trace, reconciliation
packet/                workbook, company files, index, manifest
evals/                 gold set, graders, fixture replay
docs/ · scripts/
```

---

## 5. Risk tier map

### 5.1 `check-tier.mjs` defects to fix in Step 0

1. **`globToRegExp` cannot match a top-level directory.** `**/evidence*/**`
   compiles to `^.*/evidence[^/]*/.*$`, requiring a `/` before `evidence`.
   `evidence/extract.py` resolves to `routine`. Affects all 54 trust globs.
   Fix: compile a leading `**/` to `(?:.*/)?`.
2. **`policy/` and `packet/` match no glob at any depth.** Add them.
3. **`GILLY_ACK_TRUST=1` passes trust-critical locally with no review.** Fix: the
   ack is valid only when a corresponding queue packet exists.
4. **`minTier` starts at `routine`.** Fix: unmatched paths default to `semantic`.

### 5.2 Intended tier

| Path | Tier |
|---|---|
| `policy/**` `packet/**` `ingest/trackers/**` `evidence/**` `packages/contracts/**` `supabase/migrations/**` | trust-critical |
| `ingest/documents/**` `api/**` `evals/**` `scripts/**` | semantic |
| `web/**` | routine |

Dead globs (`**/nav/**`, `**/waterfall*/**`, `**/carry/**`, `**/dilution*/**`,
`**/money*/**`, ~25 others) are deleted — a glob matching nothing reads as
coverage and provides none.

### 5.3 The `web/**` boundary, defined — **[r2]**

r1 said "must not compute figures," which is unenforceable: formatting is
literally computation. Corrected: **the API supplies every numeric value,
aggregate, percentage, support status and reason code.**

`web/**` **may** apply value-preserving locale formatting and display ordering.
It **may not** add, subtract, multiply, divide, round a canonical value, derive a
percentage or status, choose policy precedence, or aggregate rows. Arch-lint
forbids those operations on contract numeric fields. This is what keeps `web/**`
honestly `routine`.

### 5.4 The guard on the guard

`scripts/test_tier_map.mjs` asserts `tier(path) == intended` for an explicit list
of real paths. A dead glob, a renamed directory, or an engine regression fails
the gate. Without it, §5.2 is a comment.

---

## 6. Data model

```
fund ── holding ── lot (immutable: acquisition, quantity, PPS,
                        security_class, execution_status, realization)
                └─ mark (holding_id, audit_measurement_date)   ← unique
                     ├─ reported_amount     (Money)
                     ├─ validated_amount    (Money, nullable)
                     ├─ derivation_status   enum
                     ├─ valuation_basis     enum + lineage
                     └─ mark_revision

company ── alias
document ── document_version ── page ── chunk
                             └─ claim ── source_fact ── citation(span, quote, hash)
derived_figure ── computation_node ── leaf → source_fact

reporting_period (audit_scope: packet | lineage_only)
pbc_requirement (holding, audit_measurement_date, category, applicability)
  └─ evidence_assessment (revision, policy_rule_version)
       └─ evidence_link → claim   [+ applicability window]

external_signal ── signal_claim ── outreach_task (draft only)
review_task ── review_decision (append-only, fingerprinted)
workflow_run ── workflow_event
packet_version ── packet_manifest
eval_case / eval_run / eval_result / prompt_version / model_version
```

**[r2] Key changes:** lots are immutable and carry `security_class` (INV-7,
INV-17); marks carry `reported_amount` **and** `validated_amount` separately
(INV-13); claims — not documents — carry authority (INV-15); derived figures have
computation lineage (INV-8).

Money is `NUMERIC` with declared scale and a currency column; shares are
`NUMERIC` with a whole-number CHECK (INV-11) — **[r5] corrected, was `BIGINT`**.
`BIGINT` coerces: Postgres accepts `100.5` and silently stores `101`. A
fractional share count must be *rejected*, and a type that rounds cannot reject.

### 6.1 Attribute ownership — **[r2] corrected**

r1 put four attributes on the mark. Three don't belong there.

| Attribute | Owner | Derivation |
|---|---|---|
| `valuation_basis` | mark | declared, bound to lineage |
| `is_subsequent_evidence` | **each evidence link** | `document_date > measurement_date` |
| `pro_forma` | **assessment revision** | INV-4 predicate over relied-upon inputs |
| `stale_mark` | **validator result at a date** | R3 predicate; not mutable state |

Approval binds the resulting assessment revision. Recomputation creates a new
revision and invalidates the approval (INV-10).

### 6.2 State machines

Document · entity match · requirement · mark review · audit item · packet — six
independent machines with **no shared `Status` type** (INV-18).

**[r2]** Every machine gains explicit `failed`, `cancelled` and `invalidated`
states with a published transition table, terminal states, retry policy and
idempotency key. A packet approved against changed evidence becomes
`invalidated`, never remains exportable.

### 6.2.1 Verdict vocabulary — **[r5] one canonical enum**

r1–r4 carried three disagreeing lists: §6.2 omitted `insufficient` but included
`conflicting`; §7.3 and the oracle used `insufficient`; `VERDICT_ORDER` omitted
`conflicting`, leaving the row reducer undefined for a verdict the spec named.

```
not_assessed · not_applicable · missing · insufficient · partial ·
conflicting · sufficient
```

**Severity order** for reducing multiple evidence links, weakest first:
`missing < insufficient < partial < sufficient`. `not_assessed` and
`not_applicable` are outside the order and never reduce.

**`conflicting` is not on that scale — it dominates.** Any material
contradiction between claims yields `conflicting` regardless of the other links,
and it stays there until a recorded human resolution supersedes a specific claim
(§7.4). Row reduction is therefore: `conflicting` if any applicable requirement
is conflicting, otherwise the weakest applicable verdict.

R4 applies only to realisations, R3 only when triggered, R5 only to pro forma
marks — hence `not_applicable` is required, not optional. `investigate` is **not**
a verdict; it is a next action (INV-2).

*No corpus document contradicts another, so `conflicting` cannot arise from this
data. It is exercised by an injected-contradiction mutation case in
`evals/oracle/anchors.py` rather than left as an untestable branch.*

### 6.2.2 What `execution_status` describes — **[r5] resolved**

**It describes the evidence artifact in the Fund's possession, not the state of
the underlying transaction.**

Dream's email states the Series B *closed*, and both Dream's and Fluidstack's cap
tables reference executed agreements — yet both artifacts are `pro_forma`,
because a pro forma capitalisation table is what the Fund actually holds. This is
the reading the letter requires: it asks to *"identify any positions marked on a
pro forma basis pending receipt of executed documentation"* — a question about
the file, not about the world.

If the transaction's own state is ever needed, it gets its own field. Overloading
this one would make "the round closed" and "we have the closing set" the same
fact, which is precisely the gap the auditor is asking about.

### 6.3 Approvable resources — **[r3] new**

r2's INV-14 said "only an approved assertion feeds packet export." That
contradicted G3/G4 and §12, which *require* the packet to carry Anthropic's
unsupported $8,000,000 and an explicit gap inventory. Under r2 the only options
were to suppress the figure the auditor most needs to see, or to call an
unsupported valuation approved. The design conflated **approving that a number
was transcribed faithfully** with **approving that it is fair value**.

Four separate typed decisions. None implies another.

| Decision | Binds | Prerequisites | Effect |
|---|---|---|---|
| `transcription_approval` | `(source_fact, document_version)` | citation resolves | the figure may appear in **reconciliation and gap sections** — never as fair value |
| `valuation_approval` | `(mark_revision, evidence_set_hash, policy_version)` | all applicable requirements `sufficient`; cross-class policy decision present if `cross_class_policy` label set | the mark may appear as an **approved fair value** and enter `approved_fair_value_total` |
| `management_assessment_approval` | `(assessment_revision, mark_revision, evidence_set_hash)` | draft exists and is human-edited | closes R3 (V12) |
| `packet_approval` | `packet_version` | every applicable lower decision exists | permits export |

A UI action must name its target type. Packet approval **requires** the lower
decisions but never creates them.

**Anthropic 25Q4 resolved:** $8,000,000 receives a `transcription_approval` and
appears in the reconciliation and gap sections with reason
`NO_PRIMARY_PPS_SUPPORT`. It receives **no** `valuation_approval`, so it never
enters an approved total. Both documents' requirements are satisfied without
conflict.

---

## 7. PBC requirements and sufficiency

### 7.1 Categories

| ID | Category | Applicability |
|---|---|---|
| R1 | existence_and_cost | always |
| R2 | fair_value_support | always |
| R3 | unchanged_mark_calibration | see §7.2 |
| R4 | realization_support | realised lots only |
| R5 | pro_forma_identification | `pro_forma` marks only; a **labelling** requirement |

**[r2] `fully_supported`** = all **and only applicable** requirements have
verdict `sufficient`. The dashboard displays `sufficient / applicable`, never a
bare count against a fixed denominator.

### 7.2 R3 canonical definition — **[r2] resolves three competing clocks**

r1 stated R3 three different ways (§7.1, V12, INV-5) and §14 introduced a fourth.

> At an audit measurement date **D**, R3 applies when
> **(a)** the reported amount equals the reported amount at the **immediately
> preceding mark observation** for that fund — which may fall in a lineage-only
> period — **and**
> **(b)** **at least one** material component of the current mark lacks
> qualifying support dated within the 12 calendar months preceding D.
>
> Qualifying support includes financing rounds, valuation memoranda,
> administrator statements and market quotes. **Absent dated support counts as
> stale.** The boundary is strict: exactly 12 months is **not** stale.
>
> A lineage-only period may serve **only** as the predecessor observation in (a).
> It never generates its own assessment, never counts as qualifying support in
> (b), never resets support age, and never enters packet completeness (INV-20).

**[r5] Limb (a) said "audit measurement date" through r4.** That made R3
structurally unable to fire at the *first* packet date, so Roofstock — flat at
the same mark since November 2021 — escaped calibration at FY2023, which is
exactly the position the auditor's ¶3 addresses. The letter says *"across
multiple measurement dates,"* not "across packet dates."

The two roles were conflated: whether a date is in packet scope, and whether a
prior dated observation can prove the mark did not move. They are now separate.
A prior **mark observation** is required — acquisition age alone proves nothing,
which is why Because Market and Jackpocket correctly do **not** fire at 23Q4
while Roofstock does at FY2023.

**[r3] The quantifier in (b) was `every` in r2 and was wrong.** Moonfare's mark
has two material components — the underlying EUR 950,000 valuation (March 2023,
33 months stale) and the FX rate (12/31/2024 memo, *exactly* 12 months, therefore
not stale by the boundary rule). Under `every`, the fresh FX component rescued
the stale underlying one and R3 did not fire — contradicting F11, which r2 had
just amended to include Moonfare. Caught by fix-verify.

`at least one` is also the correct audit logic: if any material part of a number
rests on stale evidence, the number needs an assessment.

Re-verified against all 14 positions at their latest packet date. Fires for
exactly six — Because Market, Moonfare, Poolside, Capsule, Mom Project,
Roofstock. Does not fire for Sway, Anthropic, Lucra, Fluidstack and Banzai (value
changed), Dream (no preceding audit-date mark), Jackpocket (realised), or **Jio**
(its single component, the administrator statement, is re-dated annually and is
current at every date).

### 7.3 The sufficiency matrix — **[r2] schema fixed**

r1 keyed on `(requirement, source_class, execution_status, position_type)` while
INV-2 keyed on `document_type`; and it listed `term sheet` and `paying agent
notice` in the source column, though neither is a source class.

**Policy key, identical in both documents:**
`(requirement, source_class, execution_status, position_type)`

`document_type` → `(source_class, allowed execution_statuses)` is a **separate
validated mapping**. `term_sheet` and `paying_agent_notice` are document types.

- `source_class` (8): `executed_transaction_doc`, `company_cap_table`,
  `company_communication`, `administrator_statement`, `public_market_quote`,
  `third_party_valuation_memo`, `press`, `rumor`
- `execution_status` (5): `executed`, `pro_forma`, `non_binding`,
  `unexecuted_referenced`, `not_applicable`
- `position_type` (4): `direct_equity`, `indirect_feeder`, `public_listed`,
  `fx_denominated_interest`

**[r2] No runtime default.** The valid tuple set is explicitly enumerated in
`policy/valid_tuples.py`. Constructing an invalid tuple raises
`InvalidPolicyInput`. Every valid tuple has exactly one explicit verdict. The
table-driven test enumerates the exact valid set derived from the production
enums — never the raw 800-cell Cartesian product, and never a wildcard.

Returns `PolicyResult(verdict, reason_code, next_actions, labels)`.
Selected bindings:

| Req | Source | Exec | Position | verdict | next_actions |
|---|---|---|---|---|---|
| R2 | press | any | any | `insufficient` | `REQUEST_PRIMARY_EVIDENCE` |
| R2 | company_cap_table | pro_forma | direct_equity | `partial` | — (R5 label required) |
| R2 | company_communication | unexecuted_referenced | direct_equity | `partial` | `REQUEST_CLOSING_SET` |
| R2 | public_market_quote | not_applicable | public_listed | `sufficient` | — |
| R2 | administrator_statement | not_applicable | indirect_feeder | `sufficient` | — |
| R2 | third_party_valuation_memo | not_applicable | direct_equity | `sufficient` **only within its applicability window** (INV-16) | — |
| R1 | executed_transaction_doc | executed | direct_equity | `sufficient` | — |
| R1 | any | non_binding | any | `insufficient` | `REQUEST_EXECUTED_DOC` |
| R4 | executed_transaction_doc | executed | any | `sufficient` | — |

**[r2] `with_counsel` resolution:** a referenced-but-absent document yields R1
`partial` with `next_actions = REQUEST_FROM_COUNSEL`. A bare reference with no
stated location (`referenced_location_unspecified`) yields `insufficient`.

### 7.4 Multiple evidence links — **[r2] new**

r1 scored one source tuple but permitted many links per assessment, with no rule
for combining them. Two engineers would produce different requirement states from
identical evidence.

Each link produces its own `PolicyResult`. A deterministic, ordered reducer then
yields the requirement verdict:

1. Any material contradiction between claims → `conflicting`, and it stays
   conflicting until a recorded human resolution supersedes a specific claim.
2. Otherwise the highest verdict among links, where a later document
   **supersedes** an earlier one for the same claim.
3. **Two `partial` results never compose to `sufficient`.**

---

## 8. Deterministic validators

**[r2]** Each declares an applicability condition and returns one of
`pass | fail | not_applicable | not_comparable | unconfirmable | blocked_incomplete`
— never a silent skip. **[r3]** `unconfirmable` was used by V5 in r2 but omitted
from this vocabulary; it is now declared.

**[r3] Decimal policy — was deferred in r2, now specified.** Canonical amounts
are stored unrounded at declared field scale: money `NUMERIC(26,12)` with `check (x = trunc(x, 4))`, PPS
`NUMERIC(26,12)` with `check (x = trunc(x, 6))`, FX rates `NUMERIC(26,14)`
checked at 8, shares `NUMERIC(24,6)` constrained to whole numbers — **[r6]
corrected, was `NUMERIC(20,4)`/`(20,6)`**. Columns are declared **wider** than
the canonical scale on purpose: Postgres coerces a value to the column scale
*before* CHECK constraints run, so a narrow column silently stored `1109.999889`
as `1109.9999` and the constraint meant to catch it could never fire. The width
lets an over-precise figure survive to be rejected — the same reason shares are
`NUMERIC` rather than `BIGINT`. Do not narrow these back. Python `Decimal`
context: precision 34, trap on `Inexact` disabled, **`ROUND_HALF_EVEN`**.
Operation order for `shares × PPS` is a single multiply with no intermediate
rounding. Quantisation to currency minor units happens at exactly one point —
the export/display serialiser — and the backend supplies the rounded value, so
`web/**` performs no arithmetic (§5.3). Exported auditor figures are canonical,
not presentation-only, and carry their unrounded value in the manifest.

| ID | Check | Applicability |
|---|---|---|
| V1 | entry cost == shares × PPS | the **14 enumerated share-bearing lots**; non-share lots return `not_applicable`, never `pass` |
| V2 | mark == shares × PPS | only if basis ∈ {cost, last_round, quoted_price, per-share realization} and both inputs exist; else `not_applicable` |
| V3 | fund total | determines the held-at-date lot set first; passes only if **every** member has an approved mark; missing or unsupported → `blocked_incomplete`, never a partial total |
| V4 | post-money ÷ PPS == stated FD shares | joined by company, round, effective date, currency, capitalization scope; else `not_comparable` |
| V5 | implied FD shares from entry valuation | informational; becomes pass/fail only against a same-round cap table, else `unconfirmable` |
| V6 | Schedule A | exactly one confirmed row for the canonical fund entity; `row_price == shares × PPS`; `stated_total == Σ rows`; zero or multiple matches fail with distinct reason codes |
| V7 | FX rate present | `effective_for_measurement_date == D`, directed pair, cited source; absent → `unsupported_missing_fx`; **never** reuse a prior rate |
| V8 | FX recomputation | **never asserts equality** — computes `recomputed`, `delta = concluded − recomputed`, stores both, classifies. Moonfare FY2023 → recomputed 999,970, concluded 1,000,000, delta 30, `ROUNDING_VARIANCE`, **pass** |
| V9 | realization | per lot: `gross_cash == realized_shares × cash_per_share`; fees, escrow, earnout, non-cash reconciled separately; never compares net to the gross formula |
| V10 | quoted value | official unadjusted close on the primary exchange, that exchange's last completed session ≤ D; asserts Banzai 12/29/2023 |
| V11 | administrator NAV | joined by holding, NAV-as-of date and currency; exact Decimal equality; delivery date sets `is_subsequent_evidence` only |
| V12 | calibration | R3 per §7.2; closes **only** on an `approved` management assessment bound to the current `(mark_id, mark_revision, evidence_set_hash)`. A draft leaves the gap open |
| V13 | recap | joined by recap, security class and lot. **[r3]** A ratio producing a non-integer share count **fails** with `FRACTIONAL_SHARE_UNSUPPORTED` — cash-in-lieu and fractional interests are out of scope (INV-11), so this is a rejection, not a rounding rule. Asserts Sway 800,000 × 1.09375 = 875,000 exactly |
| V14 | citations | source facts resolve verbatim; derived figures resolve through computation lineage (INV-8) |

**[r2] Canonical text.** Citations resolve against the persisted UTF-8 output of
one pinned `pdftotext -layout` version, with zero-based half-open Unicode
code-point offsets, no post-extraction normalisation, and a hash over both the
canonical text and the extractor version.

---

## 9. Orchestration

```
load_scope → derive_requirements → retrieve → extract → validate
   ├─ create review_task
   ├─ approve → build_packet → final_lineage_check
   ├─ reject_with_fix → one semantic repair → retrieve
   └─ evidence_unavailable → record open gap
```

**[r2] Two separate budgets.** One *semantic repair* per review-task revision.
Transport retries (timeout, rate limit, provider outage) have their own bounded
policy with backoff. Every transition and external write carries an idempotency
key keyed by workflow run and step; replay produces no duplicate tasks, events,
links, approvals or packet objects.

**[r2] Failure classes.** Timeout, rate limit, outage, truncated output,
schema-valid-but-ungrounded output, parser non-zero exit and empty extraction
each have a typed terminal status and route to human review. **No failed result
creates a canonical fact** (INV-14).

Parallel: document parsing, assessment jobs, eval cases.
Sequential: validators writing canonical state, approval, promotion, export.

---

## 10. Retrieval and extraction

SQL metadata filter → Postgres FTS → rerank by (execution status, entity match,
date proximity) → top passages with page and span. Deterministic ordering with a
declared tie-break. Embeddings are a nullable column, enabled only on the §2
threshold.

`pdftotext -layout` locally; all 16 PDFs are born-digital. No hosted parser, no
OCR. Trigger: a scanned document enters the corpus.

Extraction cascade — deterministic patterns first (Banzai quote table, Moonfare
FX block, Jackpocket holder statement); model extraction only for prose and for
locating the `7GC Fund II, L.P.` row among many holders. Cached by content hash.
Temperature 0. Fail closed on schema violation.

**[r2] Ingestion identity.** Content-addressed immutable versions; duplicate
upload is idempotent; supersession is explicit and independent of document date;
a new relevant version invalidates assessments and approvals that used the
superseded one.

---

## 11. Evaluation

Layers scored independently: ingestion · retrieval (fixed K=5, locked gold query
set, declared relevance judgements) · extraction (field-level) · grounding ·
policy · classification · cost · packet lineage.

Gold cases derive from the generated snapshot `evals/oracle/derived.json`. Deterministic graders. Fixture replay
only — never live calls.

**Release gates are `docs/ORACLE.md` §7, G1–G10.** They replace r1's five, which a
constants-only implementation passed. **[r3]** G8 now requires expected outputs
for generated inputs to be computed independently *inside the test* — r2 only
required that mutating an input change the dependent outputs, which constants
plus an input-hash branch satisfies without ever recomputing correctly. G10 is
new and asserts the approval separation in §6.3.

**[r3]** Oracle expectations are per `(holding, packet_date, requirement)`
(ORACLE §5.3), with the row summary derived by the named reducer in ORACLE §3.
r2's single row-level verdict pair had no defined mapping to R1–R5, so a
hardcoded summary over misclassified requirements passed.

Model bake-off: adopt the cheapest candidate meeting 100% citation validity and
100% arithmetic cross-checks, tie-broken by recorded cost.

---

## 12. Product surfaces

1. Dual-fund dashboard — completeness scorecard, `sufficient / applicable`.
2. Company evidence workspace — timeline, holding math, source passage beside
   each fact, PBC checklist, approve/reject.
3. Change view — per transition: typed cause codes with an arithmetic
   decomposition summing to the delta; narrative text is non-authoritative and
   needs a typed human decision before export.
4. Reconciliation report — **[r2]** deterministic matching at fund, canonical
   holding, lot and source column; neither workbook silently overwrites the
   other; unresolved findings are surfaced but do not block export.
5. Signals and next actions — draft only, never sent.
6. Workflow trace.
7. Eval summary.
8. Packet export — **[r2]** generated into an isolated version, every manifest
   entry and hash validated, then atomically published. Failed generation exposes
   no partial packet. Contains only cited immutable document versions plus an
   explicit missing-evidence inventory. Manifest records packet schema version,
   policy rule version, mark/evidence/approval revisions, document hashes,
   prompt/model versions, generator commit, deterministic file order and output
   hashes. Reproducibility is **logical**, not byte-identical.

**[r2] Reset** creates a new `seed_epoch` namespace from immutable fixtures. It
never mutates or deletes prior decisions, events, packets or manifests, and is
prohibited while generation or export is active.

---

## 13. Build order

0. **Serial foundation.** Deploy hello-world through Supabase + Render + Vercel.
   Fix `check-tier.mjs`, rewrite globs, add `test_tier_map.mjs`. Run
   `captain-init`. Schema migration. Typed contracts. Dream fixture. Stubbed
   routes. **Contracts frozen at the end.**
1. Tracker ingestion → reconciliation report.
2. Document pipeline: parse, hash, page-split, classify, pattern extractors.
3. Policy: requirements, valid-tuple matrix, reducer, V1–V14.
4. Dream end-to-end: tracker row → parsed doc → cited extraction → approval.
5. Retrieval + model extraction; fixture recording.
6. Widen to all 14 positions × six packet dates.
7. Anthropic signal path — **fixed press artifact from fixtures, no network** —
   plus unsent evidence-request draft.
8. Eval harness, G1–G10.
9. UI surfaces; packet export both funds.
10. Blueprint, roadmap, deploy, rehearse.

Sequential, single pane. The Adversary pane reviews and never builds — this
supersedes the `HANDOFF.md` role table.

---

## 14. Decisions resolved from r1's open items — **[r2]**

| r1 open item | Resolution |
|---|---|
| Cut-ladder direction | **Removed.** Nothing is pre-cut, so it has no implementation effect. Reinstate only if a cut becomes binding. |
| Fund I measurement dates | §2 — packet set is exactly six dates. FY2021–22 are lineage-only. |
| R3 trigger boundary | §7.2 — full definition, verified against all 14 positions. |
| Anthropic 25Q4 display | §5 of ORACLE — `reported_amount` $8,000,000 with reason `NO_PRIMARY_PPS_SUPPORT`; `validated_amount` null; labels `insufficient` **and** `pro_forma`; excluded from any approved total (INV-19). |
| `with_counsel` sufficiency | §7.3 — R1 `partial` + `REQUEST_FROM_COUNSEL`. Bare reference with no location → `insufficient`. |

---

## 15. Scope cuts — **[r4] from the diagnosis review**

The diagnosis review concluded the design was *"over-engineered for a three-day
case-study skeleton"* and told us to keep the distinctions that prevent a
polished wrong number while cutting platform generality. It also flagged five
items I had deferred as "build-phase" that actually **did** block contract
freeze. Each is resolved below by narrowing it to the corpus, not by deferring it
again.

Every cut carries its trigger and belongs in deliverable C, the scope and roadmap
note, which explicitly asks for *"what you deliberately did not build and what
would trigger building it."*

| Cut | Narrowed to | Trigger to build the general form |
|---|---|---|
| Policy universe | the tuples this corpus exercises, plus deliberate negatives. Frozen in `evals/oracle/primitives.yaml`, not in production. An unenumerated tuple **raises** | a document arrives whose tuple is not enumerated |
| **#27/#28** transition tables | states and terminal states named; exhaustive tables, timeouts and retry budgets deferred | a document fails to parse in a real run, or ingestion becomes continuous |
| **#16** V4 tolerance | exact Decimal equality; mismatch → `not_comparable` with the delta stored | a source states a rounded post-money that must still reconcile |
| **#20** V8 variance thresholds | explicit classification only — Moonfare's $30 is `ROUNDING_VARIANCE`; anything unrecognised routes to human review | a second FX position, or a variance that is not rounding |
| **#41** change causes | the nine transitions the corpus contains, enumerated at Step 6 | a tenth transition type appears |
| **#42** reconciliation | **the screen stays**, with both real findings — the $2,000,000 Fund II FY2023 gap and the Fluidstack cost-vs-last-round variance. The general theory of field authority, alias conflict and mismatch codes is cut | the workbooks disagree in a way the two known findings do not cover |
| Market calendar, splits, timezones (#19, #22) | corpus quotes are already dated to trading days; no splits occurred | a quote must be selected rather than read |
| Fractional shares | `FRACTIONAL_SHARE_UNSUPPORTED` — a rejection, not a rounding rule | cash-in-lieu or fractional interests enter the data |
| Latency ceilings (#43) | quality floors and cost tie-break only | the demo is latency-bound |
| **[r5]** FX rate entity | no rate table. INV-6 goes red at the **policy** layer: an FX-denominated mark with no rate observed at the measurement date is `not_derivable`, and the schema cannot contradict that because it stores no rate at all | a second FX position, or an FX mark that must be *derivable* rather than honestly unsupported |

**Not cut, and not negotiable:** reported vs validated amount · source fact vs
derived figure · held-at-date lot/event logic · per-requirement verdicts and
honest gap labels · transcription vs valuation approval · the six packets and
their generated oracle · every one of F1–F12 · all ten release gates.

### Still open — genuinely non-blocking

- ~~**Decimal storage vs display.**~~ **[r6] resolved at the migration, as this
  item anticipated.** `NUMERIC(20,4)` did quantise on write — it stored
  `1109.999889` as `1109.9999` with nothing objecting. The answer was not a
  second column but a wider one: storage is declared past the canonical scale so
  an over-precise figure survives to be *rejected* by a CHECK, rather than being
  silently rounded before any constraint can see it. Computation stays exact,
  storage refuses, and only the serialiser rounds.
