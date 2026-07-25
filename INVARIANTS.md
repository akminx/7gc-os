# Invariants — distinctions the architecture must never collapse

**Revision 4.** Incorporates the cross-family invariant sweep
(`.captain/review/queue/invariant-sweep.findings.md`, model family `openai`).

An unnamed invariant has no guard and can never fail the gate. Each entry names a
distinction, states the failure it prevents, and binds a guard that can **fail
red**. Guards live in `scripts/arch_checks.py`, in property tests, or in DB
constraints — never in a comment or a convention.

The failure this file exists to catch: an agent "fixing" a red test by collapsing
a distinction. Those edits look like cleanups and are indistinguishable from
progress without a guard.

**[r2] Guard-design rule learned from the sweep.** For every invariant, state the
*cheapest edit that makes the guard green while destroying the distinction*. If
that edit is cheap and undetectable, the guard is decorative. Three r1 guards
failed this test — INV-4 actively rewarded the collapse.

Finding references (F1–F12, G1–G10) point to `docs/ORACLE.md`.
Expected values live in the generated snapshot `evals/oracle/derived.md`,
never in prose — see that file's header for why.

---

## INV-1 · Concluded value ≠ recomputed value

A third-party memo's **concluded** figure is authoritative. The system may
recompute as a cross-check but must never substitute its own arithmetic.

*Why:* Moonfare FY2023. EUR 950,000 × 1.0526 = **999,970**; the memo concludes
**$1,000,000** (rounded). Recompute-and-write-back creates a $30 unexplained
difference from an audited source, and the pattern silently overrides every
third-party conclusion in the ledger.

**Guard:** property test over **all persisted and exported** memo-based marks:
`mark.reported_amount == memo.concluded_value`. The recomputation delta is
written to `variance` and never back. `basis` provenance is immutable after
assignment.

**[r2] Cheapest collapse:** rename the recompute helper, assign through a generic
mapper, or mutate `basis` before assignment. Guard must therefore key on
persisted output and immutable basis, not on a named code path.

*Source rounding inside a concluded value is data. System arithmetic rounding is
presentation-only. No conflict with INV-19.*

---

## INV-2 · Source authority is a lattice, not a score — and a verdict is not an action

Authority must not reduce to one comparable number. Whether a document satisfies
a requirement depends on *which* requirement.

**[r2]** r1 also conflated two outputs: the press cell was specified as both
`insufficient` **and** `investigate`. One is an evidentiary verdict, the other a
next action. A single enum loses one — letting an agent either make Anthropic
green by treating research interest as support, or suppress the evidence request
because press is insufficient.

**Guard:** policy returns a product type
`PolicyResult(verdict, reason_code, next_actions, labels)`. `investigate` is
**not** a verdict. Coverage test enumerates the Cartesian product **derived from
the production enums**, not a hand-listed table, and **fails on any default or
wildcard cell**. `satisfies(R2, press)` is `False` at every rank, forever.
Arch-lint rejects any ordered enum, integer rank, or float confidence
participating in a sufficiency decision.

**[r2] Cheapest collapse:** add a wildcard default, add an enum member without
expanding the test, or convert source classes to an ordered enum. All three are
now blocked.

---

## INV-3 · Measurement date ≠ document date ≠ observation date

Three distinct instants. Conflating any two produces a figure right for the wrong
moment.

*Why:* Banzai's quote is dated 12/29/2023 against a 12/31/2023 measurement date;
Jio's FY2025 statement was delivered 30 Jan 2026; Fluidstack's 18 Dec 2025 cap
table evidences a 30 May 2025 price.

**Guard:** distinct types **plus** distinct contract fields **plus** DB
constraints. **[r2]** `NewType` alone is insufficient — it vanishes at runtime and
protects neither Postgres, generated TypeScript, JSON, nor untyped parsing.
Cross-boundary round-trip tests required.

**[r2]** `document_date` must have exactly one defined meaning (issued / as-of /
received are separate fields), or the subsequent-evidence rule mislabels
legitimate evidence and gets bypassed.

---

## INV-4 · Pro forma ≠ executed — **[r2] REWRITTEN, r1 guard was wrong**

r1 stated: `entry.pro_forma == (evidence.execution_status != executed)`.

That set includes `not_applicable`, so it labelled **Jio's administrator
statement and Banzai's public market quote as pro forma**. It also collapsed
`non_binding` and `unexecuted_referenced` into pro forma. Worst of all, the
cheapest way to make it green was to map every non-executed status to
`pro_forma` — the guard *rewarded* the exact collapse it existed to prevent.

**Corrected predicate:** `pro_forma` is true **iff** at least one relied-upon
valuation input has `execution_status == pro_forma` **and** no superseding
executed input replaces it. `non_binding`, `unexecuted_referenced` and
`not_applicable` each retain their own label and reason code and **do not** imply
pro forma.

**Guard:** each execution status tested independently against a real corpus
fixture. Dream, Fluidstack and Sway assert `pro_forma = true`; Jio, Banzai and
both third-party memos assert `false`. Export blocks on a missing or incorrect
label.

**[r5] Management's label ≠ the derived label — resolved.** r2–r4 asserted that
Anthropic carries both `insufficient` and `pro_forma`, because the tracker says
*"25Q4 mark is PRO FORMA based on press reporting."* The derived predicate
disagrees: `pro_forma` requires a relied-upon input with
`execution_status == pro_forma`, and Anthropic has no such document — it has no
document at all, only a press article.

Both are right about different things, so they are now **different fields**:

- `tracker_label` — a **primitive observation** of what management asserted.
- `pro_forma` — a **derived** assessment label computed from relied-upon evidence.

Where they disagree, that disagreement is a **reconciliation finding**, surfaced
as `label_disagreement`, not a contradiction to be resolved by overriding one.
Anthropic is the corpus case: management calls it pro forma; the evidence says
there is nothing to be pro forma *about*. That is a more damning finding than
either label alone, and collapsing them would lose it.

**Cheapest collapse:** copy `tracker_label` into `pro_forma` on ingest. The
`label_disagreement` anchor fails if the two fields ever agree by construction.

---

## INV-5 · A mark at a new date is a new assertion — **[r2] narrowed**

Poolside at 12/31/2024 and 12/31/2025 are two assertions requiring separate
*assessment*, not one fact observed twice.

**[r2]** r1 said "T2 inherits no evidence link from T1." That was over-specified
and would have been suppressed: an executed 2021 SPA legitimately supports
existence and cost at *every* subsequent date. Forcing document duplication is
not the invariant — **forcing a fresh dated assessment is**.

**Guard:** marks keyed `(holding_id, measurement_date)`. Every mark requires its
own `evidence_assessment` revision dated at that measurement date, with its own
policy-rule version. Re-use of a source document is permitted; re-use of an
*assessment* is not. Generic record-copy and bulk-relink paths are blocked by
arch-lint.

---

## INV-6 · Re-measurement is not carry-forward — **[r2] tightened**

Every measurement date requires an FX rate observed *for that date*. Carrying the
prior USD value forward is not a re-measurement.

*Why:* F1. This guard **must go red on the real data** — Moonfare FY2025 has no
12/31/2025 rate, so the correct behaviour is to fail and report the gap.

**[r2] Cheapest collapse found by the sweep:** copy the stale value and rate, and
change only `rate_date` to T2. Date equality alone does not prove observation.

**Guard:** an `FxRate` must carry a directed currency pair, a cited immutable
source version, an `observed_date`, and an `effective_for_measurement_date`.
Relabelled duplicate provenance is rejected. Regression test asserts Moonfare
FY2025 is `not_derivable`, **not** `1,048,515`.

**[r2]** Non-trading dates use an explicitly encoded market-calendar policy, not
a silent substitution — otherwise the exact-date rule conflicts with V10 and gets
disabled.

---

## INV-7 · Held-at-date ≠ active-today — **[r2] moved to lot level**

Totals are computed over positions held at the measurement date, not positions
still active when the report runs.

*Why:* F4. Fund II FY2023 must total **$6,000,000**, not $4,000,000.

**[r2]** r1 computed this at holding level with one acquired date and one
realised date. That cannot represent Fluidstack's second tranche (30 May 2025) or
Mom Project's three, and cannot represent partial realisation.

**Guard:** acquisition, quantity, PPS, execution status and realisation
allocation live on **immutable lots/events**; holding values are derived
aggregates. A mutable holding-level `active` flag may not participate in
as-of totals. Property test adds a lot between T1 and T2 and partially realises
another, computing the expected total **in the test**, not by calling the
production predicate.

---

## INV-8 · Source fact ≠ derived figure — **[r2] REWRITTEN, r1 was impossible**

r1 required every reported figure to resolve to a verbatim citation. The correct
Fund II FY2023 total of $6,000,000 appears verbatim in no document — the tracker
says $4,000,000. The rule either blocked correct arithmetic or was relaxed until
it meant nothing. All three review passes caught this independently.

**Corrected:** two lineage kinds, two guards.

- A **`SourceFact`** resolves to an exact immutable citation: `text[start:end]`
  equals the quote, content hash matches.
- A **`DerivedFigure`** resolves to a typed computation node recording operator,
  units, currency and input versions, **whose complete leaf set is cited source
  facts**.

A citation is never attached directly to a value the source does not state.

**[r2] Second hole closed:** r1 proved a quote *existed*, not that it *supported*
the figure — any valid quote attached to any figure passed. Guard now includes
table-driven bindings from each output field to an allowed
`(requirement, source_class, document, span)`, with negative cases for a real but
irrelevant quote and a quote from an insufficient source class.

**Guard:** property tests mutate one leaf, one operator, or one unit and require
lineage validation to fail. Export blocks on any unresolved leaf.

---

## INV-9 · Cost basis ≠ fair value

Held-at-cost is a distinct basis, not a fair value that happens to equal cost.

*Why:* F5. Fluidstack 25Q2 reads $2,500,000 (sum of tranche costs) where
own-round gives $3,000,000.

**Guard:** `ValuationBasis` enum bound to **typed calculation lineage**, not a
label. **[r2]** An enum proves the label, not the method — the cheapest collapse
is labelling a value `last_round` while sourcing the amount from cost. Tests
assert method/value agreement, not only the expected label. The finding stays
confined to non-audit quarters; 24Q4 and 25Q4 remain correct.

---

## INV-10 · Approval binds an immutable input **and policy** snapshot — **[r2] widened**

**[r2]** r1 named `(mark, evidence set)`. The decision also depends on document
versions, extracted-fact versions, the sufficiency-rule version, and the mark
revision. A stable evidence-link ID can point at changed content, and a policy
update can change sufficiency without changing the named pair — leaving an
approval badge and an exported packet that *look* current after the ground moved.

**Guard:** approval stores a deterministic fingerprint over mark revision,
ordered evidence/fact version IDs, policy-rule version, and decision payload,
with FKs to immutable revisions. DB denies `UPDATE` **and `DELETE`** on every
constituent. Packet validation recomputes the fingerprint and blocks on any
change. Each constituent is mutated independently in tests.

---

## INV-11 · Money is decimal **and currency-bearing**; shares are integers — **[r2] split**

**[r2]** "No float" does not enforce integer shares — bare `Decimal` shares pass
r1's lint. And two exact Decimals in different currencies could still be added:
an exact number in the wrong currency is exactly wrong.

**Guard:** `Money(amount, currency)` as a type; DB currency check constraints;
cross-currency addition rejected at the type level. Share quantities are
`NUMERIC` with a whole-number CHECK — **not** `BIGINT`, which rounds `100.5` to
`101` instead of refusing it. A type that coerces cannot enforce a rejection.
Arch-lint forbids `float` in any money or share path. One declared rounding point
at presentation, tested at midpoint boundaries and beyond binary-float exactness.

*Fractional shares are out of scope for this corpus. Trigger to revisit:
cash-in-lieu or fractional interests enter the data.*

---

## INV-12 · Gap kinds are distinct **observations**, not permanent properties — **[r2] corrected**

**[r2]** r1's own oracle collapsed this distinction: Lucra was `with_counsel` in
the source but recorded as `not_located`; Anthropic was called `with_counsel`
with no source support; Fluidstack A-2 was omitted. A guard generated from r1
would have enforced the wrong taxonomy. `docs/ORACLE.md` §F12 is corrected.

`DocumentGapKind` ∈ `with_counsel`, `referenced_location_unspecified`,
`not_located`. **[r2]** `never_existed` is removed — it is not demonstrated for
any document in this corpus and may be unknowable.

**Guard:** DB enum plus check constraint. Reason-specific fixtures for each kind,
not just the named companies — the cheapest collapse is normalising every
unavailable document to `not_located` upstream of the enum. Immutable observation
is stored separately from current remediation status, because a `with_counsel`
document can later be retrieved.

---

## INV-13 · Reported amount ≠ validated amount ≠ evidence verdict — **[r2] new**

Three orthogonal facts that r1 let share one nullable `mark.value` plus one
status:

- the amount observed in a tracker;
- the amount independently derivable from admissible facts;
- whether the evidence suffices for the requirement.

Moonfare FY2025 has the first but not the second. Anthropic FY2025 has the first,
and its implied PPS is in no document. Because Market's arithmetic reproduces
from the tracker but no existence document exists — reproducible arithmetic is
not evidentiary support.

**This is the resolution of the r1 contradiction between INV-6 and the old
release gate 2.**

**Guard:** `reported_amount` and optional `validated_amount` stored separately,
each with lineage. `DerivationStatus` and `EvidenceVerdict` are separate
exhaustive enums. Property tests over every meaningful combination, with locked
cases for Moonfare, Anthropic and Because Market. Packet validation states which
amount any total contains and rejects an unlabelled reported-but-unsupported
amount.

---

## INV-14 · Candidate extraction ≠ canonical fact ≠ approved assertion — **[r2] new**

The product promise is "AI proposes, human disposes." r1 stated it and guarded it
nowhere: nothing prevented a schema-valid `extracted_fact` from becoming a
canonical mark or a packet input. Temperature 0 and citation resolution do not
establish that the field, unit, entity or date is correct.

**Guard:** separate candidate, canonical and approved records **at the schema
level**, enforced by FK direction and DB constraints — not application
convention. Only a review decision promotes a candidate to a versioned canonical
fact. Property test: a perfectly schema-valid, perfectly cited candidate still
cannot reach a packet before promotion and approval.

Applies with equal force to generated management assessment drafts.

**[r3] Corrected — r2 said "only an approved assertion feeds packet export."**
That contradicted G3/G4 and SPEC §12, which require the packet to carry
Anthropic's unsupported $8,000,000 and an explicit gap inventory. r2 left only
two bad options: suppress the figure the auditor most needs to see, or call an
unsupported valuation approved.

The distinction r2 missed: **approving faithful transcription ≠ approving fair
value.** SPEC §6.3 defines four separate typed decisions —
`transcription_approval`, `valuation_approval`,
`management_assessment_approval`, `packet_approval`. None implies another.

Corrected rule: a canonical source fact carrying only a `transcription_approval`
**may** appear in reconciliation and gap sections; **only** a `valuation_approval`
admits a figure as fair value or into `approved_fair_value_total`.

**Guard:** DB constraint — a figure in an approved-fair-value context requires a
`valuation_approval` row. Property test: Anthropic 25Q4 appears in the gap
section **and** is absent from every approved total, simultaneously. A UI action
that advances two decision types in one write fails arch-lint (INV-18).

---

## INV-15 · Transport ≠ authority class — **[r2] new**

Email is an envelope. Meridian's email carries an **administrator statement**;
Dream's carries a **company-confirmed cap table**; Lucra's is a **company
communication**. INV-2 protects decisions made *after* `source_class` is
assigned; nothing guarded the assignment, so a classifier mapping all email to
`company_communication` passes the entire matrix while mis-tiering Jio — turning
its strongest evidence into one of its weakest.

**Guard:** transport and authority are separate columns with separate enums.
Arch-lint rejects any sufficiency code that reads a transport field. Locked
classification fixtures for Jio, Dream and Lucra.

**[r2]** Granularity is explicit: `document_type` describes the container;
`source_class` and `execution_status` describe **each relied-upon claim**. One
document may carry several claims of differing authority.

---

## INV-16 · Document date ≠ evidence applicability period — **[r2] new**

Capsule's FY2022 memo can be *explicitly* re-linked to FY2023–FY2025 with all
three date types correct, and still be invalid — the memo itself forbids later
reliance. INV-5's no-inheritance rule catches a copied link, not a deliberate
stale one.

**Guard:** `EvidenceApplicability` carries the source-stated effective date or
interval and any explicit expiry or no-reliance condition. Policy rejects
evidence outside that scope **even when manually linked**. The Capsule F3 fixture
must fail for the source-stated reason, not merely because a link was not copied.

---

## INV-17 · Security class A ≠ security class B for valuation — **[r2] new**

The corpus repeatedly holds multiple preferred classes, and The Mom Project's
term sheet states Series C is *"senior to Series B and Series Seed."* Marking
400,000 Series B shares at the Series C price assumes an economic equivalence the
document contradicts. Nothing in r1 prevented a generic
`all_preferred_shares × latest_round_pps`.

**Guard:** security class identity and rights survive ingestion. Cross-class PPS
propagation requires an explicit, cited valuation-policy decision recorded
against the mark, and produces the `cross_class_policy` label. Tracker-method
result and own-round basis are stored as **separate figures**. The Mom Project is
the failing real-data case; Lucra, Dream and Fluidstack carry graded documentary
support (`docs/ORACLE.md` §4).

**[r3] The requirement is now enforceable.** r2 stated the policy-decision
prerequisite in prose while the oracle simultaneously locked Dream and Fluidstack
as `sufficient + complete` — which r2 defined as `fully_supported`. A system
could therefore approve Dream at $5,000,000 and Fluidstack at $6,000,000 from
their cap tables alone, attach the `cross_class_policy` label, and pass every
gate. The prerequisite existed only as a sentence.

`cross_class_policy` is now an **applicability condition on R2**: where the label
is set, R2 cannot reach `sufficient` until a cited `valuation_policy_decision`
exists. It is a documented prerequisite of `valuation_approval` (SPEC §6.3), so
the four affected positions carry R2 `partial` until 7GC records the decision.
A 1:1 conversion note evidences convertibility, not equal liquidation economics.

---

## INV-18 · Independent state machines never share authorization semantics — **[r2] new**

`document.extracted`, `requirement.sufficient`, `mark.approved`,
`audit_item.ready` and `packet.approved` all sound positive and authorize
different things. r1 declared the machines independent and guarded nothing
against a shared `Status` type or an `if status == "approved"` helper.

Most dangerous instance: a generated management assessment, where
`draft ≠ approved ≠ packet-eligible` is the load-bearing boundary of the whole
product.

**Guard:** distinct state types and transition functions per aggregate; separate
DB enums; arch-lint rejects a shared cross-aggregate `Status` type and any packet
eligibility decision made on a bare string. Packet-policy tests vary each
upstream state independently. Locked test: a generated draft cannot be exported
without its own approval record.

---

## INV-19 · An aggregate inherits the worst support status of its inputs — **[r2] new**

Labelling a component is not labelling the total. Fund II's 25Q4 total contains
Moonfare's stale figure and Anthropic's press-derived figure; presented
unqualified, it launders both.

**Guard:** every derived aggregate carries the union of its inputs' reason codes
and their worst support status. A total containing a non-fully-supported
component is labelled `contains_unsupported_inputs`, exposes the unsupported
subtotal, and can never be called an approved fair-value total.

**[r3] The rule applies at every fund/date, not only Fund II 25Q4.** r2 named
only that one, which permitted a system to taint 25Q4 correctly while publishing
every earlier total as unqualified approved fair value — and still pass G3.
Every packet date has at least one non-fully-supported row: Fund II 12/31/2023
carries Because Market (`none`) and Jackpocket (`insufficient` R1); 12/31/2024
carries Because Market and Lucra; **every** Fund I year carries Capsule
(`insufficient`) and The Mom Project (`partial`).

Consequently **`approved_fair_value_total` is null at all six packet dates** in
this corpus. That is the correct result, not a defect — no fund-year in the
provided data is fully supported. Every published total must therefore be
explicitly typed as one of `tracker_reconciliation_total`,
`held_at_date_reported_total`, or `approved_fair_value_total`, and G3 asserts the
type, the label and the unsupported subtotal for each.

---

## INV-20 · Audit measurement date ≠ lineage-only tracker period — **[r2] new**

Fund II's 24Q2, 25Q2, 25Q3 and 26Q1 are required for the change view and for F5,
but must never become packet measurement dates or generate PBC requirements.
Fund I FY2021–FY2022 likewise.

**Guard:** a versioned reporting-period record carries explicit
`audit_scope ∈ {packet, lineage_only}` — never inferred from cadence or column
name. Packet tests reject lineage-only periods; change-view tests require them.
Locked cases for 25Q2, 25Q3, 26Q1 and Fund I FY2021.

**[r4] "Never satisfies the clock" was too broad — corrected.** r2/r3 barred
lineage-only periods from R3 entirely, which conflated two different roles:

- whether a date is itself in packet/PBC scope, and
- whether a prior dated mark **observation** can establish that the current mark
  is unchanged.

The consequence was that R3 could never fire at the *first* packet date, so
Roofstock — flat at the same mark since November 2021 — escaped calibration at
FY2023, which is exactly the position the auditor's ¶3 is about. The letter says
*"across multiple measurement dates,"* not "across packet dates."

Corrected: a lineage-only period **may** serve as the predecessor observation for
R3's equality limb. It still never generates its own assessment, never counts as
fresh valuation support, never resets support age, and never enters packet
completeness.

**A prior dated mark observation is required — acquisition age is not enough.**
Being held since 2021 does not prove the mark did not move. Because Market and
Jackpocket have no observation before 23Q4, so they correctly do **not** fire
there, while Roofstock does at FY2023. `evals/oracle/anchors.py` locks all three.

---

## Interaction verdicts — **[r2]**

- INV-1 and INV-11 are compatible: preserve the memo's exact concluded Decimal as
  authoritative data; record the recomputation only as variance.
- **INV-4 no longer conflicts with INV-2** — `not_applicable` is a valid execution
  status and no longer implies pro forma.
- **INV-5 no longer conflicts with continuing existence/cost evidence** — fresh
  assessment is required, not fresh documents.
- **INV-8 no longer conflicts with V1–V13 or packet totals** — source citation and
  computation lineage are separate guards.
- INV-6 depends on INV-3's temporal model plus an explicit market-calendar policy.
- INV-10 must include the policy version, or a change to INV-2's matrix silently
  invalidates already-approved packets.
- INV-13 is what makes INV-6 and release gate G3 coexist.

---

## Naming triggers — add an invariant when

- Two states differ only by a boolean and one is "worse."
- A value is copied to the next period without new evidence.
- Two dates appear in the same signature.
- A verdict is reduced to something comparable with `>`.
- A test fails and the tempting fix is to widen a type or relax an equality.
- **[r2]** A guard's cheapest path to green also destroys the distinction.
- **[r2]** A rule is stated in prose in the spec but nothing can fail because of it.
