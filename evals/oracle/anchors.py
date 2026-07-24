#!/usr/bin/env python3
"""Hand-worked boundary anchors for the oracle derivation.

Expectations are written LITERALLY. They do not call derive.py's predicates to
produce an expected value — that would be the "second implementation agreeing
for the wrong reasons" failure the diagnosis review warned about.

Split across cases_corpus.py and cases_policy.py when the gate's file-size
limit caught this file at 998 lines.

Run:  .venv/bin/python evals/oracle/anchors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cases_corpus
import cases_policy
from harness import FAILURES, Oracle

HERE = Path(__file__).parent


def main() -> int:
    o = Oracle(HERE / "primitives.yaml")
    snap = o.run()
    cases_corpus.run(snap, o)
    cases_policy.run(snap, o)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} ANCHOR FAILURE(S): {FAILURES}")
        return 1
    print("All anchors pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
