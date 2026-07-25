#!/usr/bin/env python3
"""Which invariants are enforced where — derived from the code, not hand-written.

Two consecutive review findings were the same mistake: a rule enforced on one
side only. R1/R2-inapplicable was unrepresentable in the contract and still
storable in the database; over-precise money was refused by the database and
still constructible in the contract. Each fixed half made the other look covered.

A hand-maintained table would drift the first time someone moved a constraint.
So this reads the actual files and reports a blank wherever a layer that should
mention an invariant does not. A blank cell is a candidate defect, not a
formatting issue.

  python scripts/invariant_matrix.py            # print the table
  python scripts/invariant_matrix.py --check    # exit 1 if a required cell is blank
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    ).stdout.strip()
    or "."
)

# Where each layer lives. `db` is the schema plus its guards; `code` is the wire
# contract; `test` is anything under tests/; `oracle` is the executable oracle.
LAYERS: dict[str, list[Path]] = {
    "db": sorted((ROOT / "supabase" / "migrations").glob("*.sql")),
    "code": sorted((ROOT / "packages" / "contracts").rglob("*.py")),
    "test": sorted((ROOT / "tests").glob("*.py")),
    "oracle": sorted((ROOT / "evals" / "oracle").glob("*.py")),
}

# Which layers each invariant MUST appear in. Marked deliberately: not every
# invariant belongs in every layer, and pretending otherwise would make the
# matrix noisy enough to ignore — which is how a check stops being read.
#
#   db     — the distinction is storable, so the database must refuse violations
#   code   — the distinction crosses the wire, so the contract must refuse them
#   test   — something must prove the guard can fail
#   oracle — the expected values depend on it
REQUIRED: dict[str, set[str]] = {
    # Titles are quoted so a renumbering in INVARIANTS.md is visible here rather
    # than silently shifting every requirement by one — which is exactly what the
    # first version of this table did.
    "INV-1": {"oracle"},  # concluded value != recomputed value; anchored in the oracle
    "INV-2": {"oracle"},  # authority lattice — policy, not a storable shape
    "INV-3": {"db", "code", "test"},  # three distinct dates
    "INV-4": {"db", "code", "oracle"},  # pro forma != executed
    "INV-5": {"db", "test"},  # a mark at a new date is a new assertion
    "INV-6": {"oracle"},  # re-measurement — FX, SPEC 15 scope cut
    "INV-7": {"db", "code", "test"},  # held-at-date
    "INV-8": {"db", "code", "test"},  # source fact != derived figure
    "INV-9": {"oracle"},  # cost basis != fair value
    "INV-10": {"db", "code", "test"},  # approval binds immutable inputs
    "INV-11": {"db", "code", "test"},  # money and shares
    "INV-12": {"db", "code", "test"},  # gap kinds are observations
    "INV-13": {"db", "code", "test"},  # reported != validated != supported
    "INV-14": {"db", "code", "test"},  # candidate != canonical != approved
    "INV-15": {"db", "code"},  # transport != authority
    "INV-16": {"db", "code", "test"},  # applicability window
    "INV-17": {"db", "code", "oracle"},  # cross-class pricing
    "INV-18": {"db", "code"},  # independent state machines
    "INV-19": {"code", "test", "oracle"},  # aggregates inherit worst support
    "INV-20": {"db", "code", "test"},  # packet vs lineage-only period
}


def invariants() -> list[tuple[str, str]]:
    """(id, one-line title) for every invariant declared in INVARIANTS.md."""
    text = (ROOT / "INVARIANTS.md").read_text(encoding="utf-8")
    found: list[tuple[str, str]] = []
    for m in re.finditer(r"^#{2,4}\s*(INV-\d+)\s*[·\-—:]?\s*(.*)$", text, re.M):
        title = re.sub(r"[`*_]", "", m.group(2)).strip()
        found.append((m.group(1), title[:52]))
    return found


def mentions(layer: str, inv: str) -> bool:
    """Does any file in this layer name the invariant?

    Naming is the weakest possible signal and deliberately so: the point is to
    surface a layer that says NOTHING about a rule. A cell being filled is not
    proof the guard is right — the tests and reviews are for that.
    """
    pattern = re.compile(rf"\b{re.escape(inv)}\b")
    return any(
        pattern.search(f.read_text(encoding="utf-8", errors="replace"))
        for f in LAYERS[layer]
        if f.is_file()
    )


def build() -> tuple[list[list[str]], list[str]]:
    rows: list[list[str]] = []
    gaps: list[str] = []
    for inv, title in invariants():
        need = REQUIRED.get(inv, set())
        cells = []
        for layer in ("db", "code", "test", "oracle"):
            present = mentions(layer, inv)
            if present:
                cells.append("yes")
            elif layer in need:
                cells.append("MISSING")
                gaps.append(f"{inv} is not enforced in `{layer}` but should be")
            else:
                cells.append("n/a")
        rows.append([inv, title, *cells])
    return rows, gaps


def main() -> int:
    rows, gaps = build()
    if not rows:
        print("no invariants found in INVARIANTS.md", file=sys.stderr)
        return 1

    width = max(len(r[1]) for r in rows)
    print(f"\n{'':7} {'':{width}}  {'db':>7} {'code':>7} {'test':>7} {'oracle':>7}")
    print("-" * (7 + width + 34))
    for inv, title, *cells in rows:
        print(f"{inv:7} {title:{width}}  " + " ".join(f"{c:>7}" for c in cells))

    covered = sum(1 for r in rows if "MISSING" not in r)
    print(f"\n{covered}/{len(rows)} invariants fully covered where required.")
    if gaps:
        print("\nGaps:")
        for g in gaps:
            print(f"  - {g}")
        if "--check" in sys.argv:
            return 1
    else:
        print("No layer is silent about a rule it is supposed to enforce.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
