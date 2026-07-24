## Summary
<!-- 1-3 bullets: what changed and why -->

## Risk tier
<!-- Must be ≥ path-derived minimum from review-policy.yaml. Trust-critical
     paths (grants/policy/auth/event-log/protocol/redaction/payments) cannot
     be declared routine. -->

- [ ] `routine`
- [ ] `semantic`
- [ ] `trust-critical`

Path-derived minimum (if known): ___________

## Oracle / evidence
<!-- For semantic + trust-critical: oracle author ≠ implementer. -->

- Spec section(s):
- Oracle path (tests/goldens/properties):
- Command run + result:

## Review topology (from review-policy.yaml)

- [ ] Deterministic gate green (`check_all` / CI)
- [ ] Bugbot (mechanical only — not semantic approval)
- [ ] Pass A — semantic adversary
- [ ] Pass B — implementation adversary (required for semantic+)
- [ ] **Pass A / Pass B / Bugbot each ran blind** — no pass was shown another's findings
- [ ] Finding-owner verified fixer changes (if any)
- [ ] Human Judge (required for trust-critical)
- [ ] CODEOWNERS approval (trust-critical paths — n/a on solo repos, see below)

## Fresh-eyes check (the solo substitute for code-owner review)
<!-- GitHub cannot require you to approve your own PR, so "require code-owner
     review" is unenforceable on a solo repo. This is the honest replacement:
     separation in TIME between the mind that generated the diff and the mind
     that approves it. The solo failure mode is merging in flow state with a
     green gate and a skimmed diff. -->

- [ ] I read this diff in a **separate session** from the one that produced it
- [ ] For trust-critical: I read the diff itself, not just the summary of it

## Implementer model family
<!-- For routing recalibration — e.g. Grok/Terra, Opus, Sol, Fable -->

## Unresolved assumptions
<!-- Anything reviewers should not assume is settled -->

## Test plan
- [ ]
