# 7GC OS — project context

Read by both panes: Cursor loads `AGENTS.md` automatically, and Claude Code
reads it through the `CLAUDE.md` symlink beside it. One file, so the two panes
cannot drift into different ideas of what this project is.

This file is **shared ground**, not a channel. It carries what both sides are
entitled to know: scope, invariants, commands, conventions. It must never carry
review findings, Bugbot output, or one pane's conclusions — see "Pane blindness"
below.

## What this is

An audit-support slice for a venture fund: for each holding at each measurement
date, assemble the evidence supporting its valuation mark, trace every figure to
an exact source passage, route uncertain evidence through human review, and
export an auditor packet that states its own gaps.

The source materials are a fund's private case-study dataset. They are
gitignored and are not republished.

## The load-bearing idea

In fund valuation a wrong number is *plausible*. It renders, it reconciles to
itself, and it passes every type check. So correctness is pinned by artefacts
that can fail, never by assertion:

- `evals/oracle/primitives.yaml` — hand-transcribed source facts only, no
  derived values.
- `evals/oracle/` — derivation in code, importing nothing from the application.
- `evals/oracle/derived.json` — the generated snapshot, committed so drift shows
  up in a diff.
- `INVARIANTS.md` — 20 distinctions the architecture must not collapse, each
  with a guard that can go red and its cheapest collapse-to-green named.
- `supabase/migrations/` — invariants enforced as database constraints, so a
  violation is rejected rather than stored.

A prose oracle was tried first and failed twice: six of six unsupported
subtotals were wrong, and the reviewer checking them hand-computed one wrong
too. Hand-maintained derived values are unreliable regardless of who maintains
them. That is why the oracle is a program.

## Commands

```bash
python scripts/check_all.py        # Python gate — lint, types, tests, invariants, secrets, CVEs
node scripts/check-all.mjs         # Node gate — biome, tsc, vitest, jscpd, npm audit
python evals/oracle/derive.py      # regenerate the oracle snapshot
python evals/oracle/anchors.py     # check it against hand-worked cases
node scripts/check-tier.mjs        # review tier for the current diff
```

Both gates run in the pre-commit hook and in CI. Never bypass with `--no-verify`
outside a declared emergency. Ratchets only tighten.

## Conventions

- Python is uv-managed. Use `.venv/bin/python`, never a Homebrew interpreter and
  never a bare `python3` — a bare interpreter can miss dependencies and pass
  vacuously.
- Search for existing code before writing new. No duplicate functions.
- Do not add comments, docstrings, or type annotations to code you did not
  change.
- Commit messages and PR text carry no AI attribution.

## Review roles

`review-policy.yaml` derives a tier from changed paths: `routine`, `semantic`,
`trust-critical`. Anything that can produce a reported figure requires human
review regardless of green checks.

Two panes, two model families. Claude Code authors; the Cursor pane owns every
cross-family pass — spec Pass B, oracle adversary, invariant sweep,
implementation Pass B, gate red-team. A pass run in the wrong family is not a
pass.

### Pane blindness

The Adversary reads the packet in `.captain/review/queue/` and nothing else. No
prior findings, no Bugbot output, no Author transcript.

Uncorrelated blind spots are the only thing the second pane irreplaceably
provides. "Pass B never sees Pass A" holds today because it is a property of the
file rather than a rule someone remembers. Automating the transport is fine;
widening what either side sees deletes the value and leaves the ceremony.
