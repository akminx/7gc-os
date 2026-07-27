# 7GC OS — Scope and roadmap

What I did not build, and the condition that would make me build it. A cut
without a trigger is an excuse; a cut with one is a decision someone else can
audit. Built and deployed: both funds, 72 marks over six packet dates, 247 cited
facts each bound to its passage, and an oracle the ledger agrees with on 175
requirement comparisons.

## Not built

- **Any model call.** Deterministic extractors read the whole corpus — a packet
  an auditor re-derives is the wrong place for a non-reproducible step.
  *Trigger:* a figure no pattern reads; the cascade (SPEC §10) ships behind the
  eval harness, never ahead of it.
- **Retrieval — FTS, rerank, embeddings.** 20 documents, each read whole, so no
  ranking step can fail silently. *Trigger:* a corpus too large to read whole;
  for embeddings, Recall@5 +5 points over FTS at ≤2× cost.
- **The general form of the validators.** V4 is exact Decimal equality, not a
  tolerance; V8 classifies Moonfare's $30 as `ROUNDING_VARIANCE` and routes
  anything unrecognised to a human. The arithmetic answer key stays in
  `evals/oracle/`, so a validator cannot grade itself. *Trigger:* a source states
  a rounded post-money that must still reconcile, or a variance that is not
  rounding.
- **Management-assessment drafts.** R3 fires at 12 holding-dates and emits
  `DRAFT_MANAGEMENT_ASSESSMENT`; nothing drafts. *Trigger:* fired — ¶3(b) asks
  *management* to author it.
- **Settlement-of-funds evidence.** Nine extracted facts reach no requirement,
  and ¶1 names it. *Trigger:* fired.
- **Connectors · LangGraph · RBAC · outreach sending · graph DB.** Fixed pack,
  stateless runs, read-only public surface. *Triggers:* continuous arrival · a
  run pausing days for an inbound event · a write surface. Autonomous sending is
  prohibited by INV-14, not deferred.
- **Coverage floor and file-size ceiling, as gates.** Loosened deliberately,
  recorded in `check_all.py`: coverage had ratcheted to 98.25% and the remainder
  was `main()` bodies. Both still report. *Trigger:* a defect either would have
  caught reaches `main`.
- **A second cross-family review round on Step 3.** One ran, and found two real
  citation defects; Step 1 took six rounds, and rounds 5 and 6 found defects in
  rounds 3 and 4's fixes. *Trigger:* a packet defect of a class the first round
  already checks.

## Now

`/ready` returned 200 through three separate broken deployments — correctly,
since it is `SELECT 1` and the database was up. The API read the wrong schema and
served 121 companies called "Test Co"; every packet route 500'd behind a
transaction-mode pooler while the suite stayed green, connecting on 5432 to
production's 6543; and a gap cited a sentence about the wrong security class,
which 175 oracle comparisons could not see because they compare verdicts, not
quotes. **A check that cannot fail in the way that matters is the failure** —
which is what this system claims about a valuation mark.

## Week 1

Settlement of funds, oracle first: those facts need a matrix cell that raises
today, and the oracle models 23 evidence records against the ledger's 28. Amend
the answer key, add the cell, re-derive; the reverse order is an implementation
grading itself. Then the assessment drafts, where the first model call earns its
place and is confined by construction, since INV-14 and INV-18 make a draft
un-exportable without its own approval. Then a deployment check that asserts
packet contents, and one CI job through the pooler.

## Week 4

The second and third functions, on the same six layers. Quarterly reporting is
half-built: 12 fund-periods ingested, 6 packeted, the other six `lineage_only`
only because the auditor did not ask — and those are the quarterly dates. Same
assertions, same typed totals, same lineage; the requirement set changes. The
waterfall runs on the Positions layer, where Jackpocket's realisation is already
stored as gross, holdback, withholding and net separately, because a distribution
cannot be computed from the netted figure.

## Week 12

Expose the ledger as an **MCP server**, so any assistant can query it — safe only
because of what the ledger already is. An assistant reading the raw pack can
produce a confident wrong number: a share count off a superseded pro forma table.
One reading this ledger cannot. Every fact is typed and carries its span and its
approval state; a figure no requirement supports comes back labelled unsupported;
`approved_fair_value_total` comes back **null at all six packet dates**, because
no fund-year here is fully supported. The refusal is the product, and it is where
buy-versus-build falls: buy the assistant, build the ledger.
