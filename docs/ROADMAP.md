# 7GC OS — Scope and roadmap

What I did not build, and the condition that would make me build it. A cut
without a trigger is an excuse; a cut with one is a decision someone else can
audit. Built and deployed: both funds, 72 marks over six packet dates, 253 cited
facts each bound to its passage, and an oracle the ledger agrees with on 175
requirement comparisons.

## Built since, and why the trigger fired

- **Model extraction.** A figure no pattern could read — Lucra's CEO email —
  fired the stated trigger. It ships behind the guardrail SPEC §10 required:
  the model returns a quote and a value and never an offset, so a hallucinated
  passage or a misattached figure is a refusal rather than a row. Recorded and
  replayed, never live in CI. Three of five proposed figures were accepted; the
  two refusals are the guardrail firing.
- **Retrieval, layers 1–2.** SQL filter → Postgres FTS → declared rerank. No
  index: the scan is 15 ms and the round trip is sixty times that. Measured on
  request, both ways — entity-scoped 40/40, blind 24/40 at top-5. The scoped
  figure measures the SQL filter, since about one candidate survives it; the
  blind figure is what the ranker is worth.

## Not built

- **The general form of the validators.** V4 is exact Decimal equality, not a
  tolerance; V8 classifies Moonfare's $30 as `ROUNDING_VARIANCE` and routes
  anything unrecognised to a human. The arithmetic answer key stays in
  `evals/oracle/`, so a validator cannot grade itself. *Trigger:* a source states
  a rounded post-money that must still reconcile, or a variance that is not
  rounding.
- **Management-assessment drafts.** R3 fires at 12 holding-dates and emits
  `DRAFT_MANAGEMENT_ASSESSMENT`; nothing drafts. *Trigger:* fired — ¶3(b) asks
  *management* to author it.
- **Connectors · LangGraph · RBAC · outreach sending.** Fixed pack, stateless
  runs, read-only public surface. *Triggers:* continuous arrival · a run pausing
  days for an inbound event · a write surface. Autonomous sending is prohibited
  by INV-14, not deferred.
- **Coverage floor and file-size ceiling, as gates.** Loosened deliberately,
  recorded in `check_all.py`: coverage had ratcheted to 98.25% and the remainder
  was `main()` bodies. Both still report. *Trigger:* a defect either would have
  caught reaches `main`.
- **A second cross-family review round on Step 3.** One ran, and found two real
  citation defects; Step 1 took six rounds, and rounds 5 and 6 found defects in
  rounds 3 and 4's fixes. *Trigger:* a packet defect of a class the first round
  already checks.

## Cut, each with its trigger

| Cut | Trigger to build |
|---|---|
| A chatbot. Windows bound to a selection, not a conversation — a chat answer has no anchor, so provenance is re-argued in prose each time, which is where wrong figures enter | None. Cross-holding questions ("which companies have unsigned paperwork") are filters over the table, which the packet payload already carries. Exact, instant, free |
| Generation over retrieved passages — the G in RAG. Retrieval ships; synthesis does not. The answer is the passages | A corpus too large to show the reader. At 20 documents and 44k characters, an auditor wants the quote, not a paraphrase of it |
| Embeddings / vector search | Recall@5 +5 points over FTS at ≤2× cost (unchanged, and now measurable — the blind 24/40 is the baseline) |
| Model reranking | Never. INV-1 makes authority a lattice, not a score; press cannot support a fair-value mark at any rank. A model rerank turns that into a number |
| Query expansion | Already fired, not yet built: "euros" does not stem to EUR, "currency" does not reach "denominated". Expansion runs before the database, where a bad expansion returns fewer rows rather than a wrong sentence |
| Recall re-measured for the requirement-scoped path | Before any recall number is claimed for the product's own configuration. The filter is opt-in precisely so the baseline did not move |
| Guards against spelled-out figures and synonym inversion | Unclosable by regex. The numeral guard catches digit-typos and digit-arithmetic; the payload is shaped so the misreading is unavailable instead |
| Rate limiting on the paid route | Public exposure beyond a named demo. Today it is off unless `ASSISTANT_ENABLED` says otherwise |
| The vocabulary rollout — 99 definitions still live only in `title=` tooltips | Touch-device or printed use, where hover does not exist |
| A relationship graph beside the ledger. The corpus already holds multi-hop facts relationally — Jio is an LP interest in a feeder that holds the company; every document → claim → fact → span is typed — and at 20 documents a recursive CTE answers them. On the firm's real data the questions change shape: shared signatories across funds, counsel named in one SPA appearing in another's gap note, a round document pricing a class another holding marks off. Those stay *correct* as SQL; they stop being *writable* once each hop is a join someone has to remember | Recurring multi-hop questions three joins deep that operators stop writing as SQL, on a corpus too large for the packet payload to carry as a filter. The ledger remains the source of truth; the graph is a projection over it, never a second store of figures |

## Now

Three defects reached a deployed page and none was caught by a test, because
every test ran where all three were already true: a route that had never
executed, a dependency classified for the wrong lifetime, and one switch
controlling two unrelated things. Two were found by cross-family review, one by
the deployment itself. The gates are good at what they can see; this note is
the honest list of what they cannot.

`/ready` returned 200 through three separate broken deployments — correctly,
since it is `SELECT 1` and the database was up. The API read the wrong schema and
served 121 companies called "Test Co"; every packet route 500'd behind a
transaction-mode pooler while the suite stayed green, connecting on 5432 to
production's 6543; and a gap cited a sentence about the wrong security class,
which 175 oracle comparisons could not see because they compare verdicts, not
quotes. **A check that cannot fail in the way that matters is the failure** —
which is what this system claims about a valuation mark.

## Week 1

The assessment drafts, where the first model call that *writes* earns its place
and is confined by construction, since INV-14 and INV-18 make a draft
un-exportable without its own approval. A deployment check that asserts packet
contents — the three defects above all reached a deployed page past a green
suite — and one CI job through the pooler, so the transaction-mode failure
class is exercised where it can fail.

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

On the firm's real data — not this pack — project the same ledger into a
**relationship graph**: companies, documents, claims, counsel, signatories, and
the edges between them. The figures stay where they are; what becomes queryable
is how they relate. That is the cut above, and it waits on the trigger there.
