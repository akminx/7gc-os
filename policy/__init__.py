"""The policy layer: what the evidence means.

`ingest/` owns what the sources say. This package owns what that amounts to —
the sufficiency matrix (SPEC §7.3), the multi-link reducer (§7.4), the five
requirements (§7.1–7.2) and the deterministic validators (§8).

Nothing here imports `evals/`. The oracle states the answer independently, from
hand-transcribed primitives, and the two are compared as data in
`tests/test_policy_vs_oracle.py`. An implementation that consulted its own answer
key would agree with itself at every step and report nothing.
"""
