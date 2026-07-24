"""The oracle is the correctness contract — the gate must run it.

Without these, `check_all` reported "no tests ran" and still went green: a
deterministic gate that proves nothing is exactly the silently-passing check
this workflow exists to prevent.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)


def test_oracle_derivation_regenerates_cleanly() -> None:
    """The committed snapshot must match what derive.py produces."""
    before = (ROOT / "evals/oracle/derived.json").read_text()
    r = _run(sys.executable, "evals/oracle/derive.py")
    assert r.returncode == 0, r.stdout + r.stderr
    after = (ROOT / "evals/oracle/derived.json").read_text()
    assert before == after, "derived.json is stale — re-run evals/oracle/derive.py and commit"


def test_oracle_anchors_pass() -> None:
    """Hand-worked boundary cases with literal expected values."""
    r = _run(sys.executable, "evals/oracle/anchors.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "All anchors pass" in r.stdout


def test_tier_map() -> None:
    """Every real repo path resolves to its intended risk tier (SPEC §5.4)."""
    r = _run("node", "scripts/test_tier_map.mjs")
    assert r.returncode == 0, r.stdout + r.stderr
