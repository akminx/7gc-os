# 7GC OS — Valuation Evidence Ledger

An audit-support slice for a venture fund: for each holding at each measurement
date, assemble the evidence supporting its valuation mark, trace every figure to
an exact source passage, route uncertain evidence through human review, and
export an auditor packet with its gaps stated honestly.

> **Status: design foundation.** The correctness contract, invariants and
> deterministic gate are complete and enforced. The application — schema,
> ingestion, retrieval, UI, packet export — is next. See `docs/SPEC.md` §13 for
> the build order.
>
> The source materials are a fund's private case-study dataset and are not
> republished here. The oracle references them by name and quotes short passages
> where a finding depends on the exact wording.

## Why the oracle is a program

In fund valuation a wrong number is *plausible*. It renders, it reconciles to
itself, and it passes every type check. Lint and types prove almost nothing, so
correctness has to be pinned down before any code exists.

The first attempt was a prose document holding ~200 hand-maintained expected
values — row verdicts, calibration dates, subtotals — alongside the rules those
values were supposed to follow. It failed twice. Six of six unsupported
subtotals were wrong, and the reviewer checking them hand-computed one wrong
too. Hand-maintained derived values are unreliable regardless of who maintains
them.

So the oracle is split three ways:

| Path | Contents | Maintained by |
|---|---|---|
| `evals/oracle/primitives.yaml` | share counts, prices, dates, document existence and gap kind, claim-level authority, applicability windows, the policy matrix | **hand**, reviewed |
| `evals/oracle/{model,policy,checks,derive}.py` | every derived value | code — imports nothing from the application |
| `evals/oracle/derived.{json,md}` | the generated snapshot | **generated**, committed so diffs are reviewable |

`cases_corpus.py` and `cases_policy.py` hold 174 anchors whose expected values
are written **literally**, so they cannot agree with the derivation for the
wrong reasons. Synthetic scenarios via `Oracle.from_dict` reach branches the
fixed dataset cannot — positive approval paths, multi-lot realisations,
multi-class pricing, contradictory claims.

```bash
python evals/oracle/derive.py     # regenerate the snapshot
python evals/oracle/anchors.py    # check it against hand-worked cases
python scripts/check_all.py       # the full gate
```

## What the design protects

`INVARIANTS.md` names 20 distinctions the architecture must not collapse, each
with a guard that can fail red and its cheapest collapse-to-green path stated.
A representative few:

- **reported ≠ validated ≠ supported.** A tracker figure, an independently
  derivable figure, and an evidence verdict are three different facts. One
  holding reproduces its arithmetic perfectly and still has no evidence at all.
- **Source authority is a lattice, not a score.** Press reporting can trigger
  research; it can never support a fair-value mark, at any rank, ever.
- **Transport ≠ authority.** An administrator statement arriving by email is an
  administrator statement. Classifying by envelope mis-tiers the strongest
  evidence in the set.
- **Re-measurement is not carry-forward.** A currency-denominated position needs
  a rate observed *at* the measurement date. This guard goes red on the real
  data, which is the point.
- **Approving a faithful transcription ≠ approving a fair value.** Otherwise the
  packet must either hide an unsupported figure or bless it.

## The gate

`scripts/check_all.py` runs lint, format, types, tests with a coverage ratchet,
duplicate detection, file-size limits, debt markers, architecture invariants, a
suppression ratchet, secrets, SAST, dependency CVEs, CLAUDE.md alignment, and CI
parity. It runs as a pre-commit hook and in CI.

`scripts/check-tier.mjs` derives a review tier from changed paths, so anything
producing a reported figure requires human review regardless of green checks.
`scripts/test_tier_map.mjs` asserts 20 real paths resolve to their intended
tier — because the tier engine was silently broken for the entire design phase:
its glob compiler could not match a top-level directory, so `policy/`,
`packet/` and `evidence/` all resolved to *routine*. A check that passes because
it cannot run is worse than no check.

## Layout

```
docs/SPEC.md          scope, data model, requirements, validators, build order
docs/ORACLE.md        findings F1-F12, release gates G1-G10
INVARIANTS.md         20 named distinctions and their guards
evals/oracle/         the executable oracle
scripts/              the deterministic gate
tests/                wires the oracle and tier map into the gate
```
