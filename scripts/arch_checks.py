#!/usr/bin/env python3
"""Architecture-invariant checks for the gate.

Two entry points, both registered in check_all.py:

  check_ignore_budget — GENERIC (works in any repo, nothing to configure): a
    ratchet on type-ignore / lint-suppression comments, so no one silences the
    type or lint checks to go green.

  check_architecture — REPO-SPECIFIC: static cross-module lints that enforce the
    distinctions named in INVARIANTS.md — the ones types and unit tests can't
    span because they cross module boundaries (e.g. "layer X must READ a value
    layer Y owns, never re-derive it", "no privileged key in client code", "one
    embedding dimension shared by writer and reader"). Ships EMPTY (always
    passes). Add one rule each time you name such an invariant; examples are in
    comments below.

Discipline: see INVARIANTS.md. A guard must be able to FAIL, or it's just prose.
"""

import json
import re
from pathlib import Path


def _iter_src(root, skip_dirs, subdirs, suffixes):
    """Yield working-tree source files under the given repo-relative subdirs,
    pruning vendored/build dirs. Working-tree (not git-tracked) so staged files
    are covered pre-commit and violations surface before they're committed."""
    import os
    from pathlib import Path

    for sub in subdirs:
        base = root / sub
        if not base.exists():
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d not in skip_dirs]
            for fn in fns:
                p = Path(dp) / fn
                if p.suffix in suffixes and p.is_file():
                    yield p


#: The two fields that must never be typed by a human. INV-8.
_SPAN_FIELDS = {"span_start", "span_end"}


def _hand_written_spans(path: Path, root: Path) -> list[str]:
    """Every place this file states a citation offset instead of computing one.

    Catches both shapes an offset can arrive in: a keyword argument to a call
    (`Citation(span_start=0, ...)`) and a mapping key (`{"span_start": 0}`),
    which is the same assertion wearing a different hat and is how the rule
    would otherwise be walked around without anyone intending to.
    """
    import ast

    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except SyntaxError as exc:
        return [f"{path.relative_to(root)}:{exc.lineno} could not be parsed: {exc.msg}"]

    hits: list[str] = []
    for node in ast.walk(tree):
        named: set[str] = set()
        if isinstance(node, ast.Call):
            named = {kw.arg for kw in node.keywords if kw.arg in _SPAN_FIELDS if kw.arg}
        elif isinstance(node, ast.Constant) and node.value in _SPAN_FIELDS:
            # Any bare mention of the field name as a string. The first version
            # matched dict literals and call keywords only, so
            # `fields["span_start"] = start` followed by `Citation(**fields)`
            # walked straight past it — the same assertion, spelled differently.
            # Exact equality, so the column list inside a longer SQL string is
            # untouched.
            named = {str(node.value)}
        else:
            continue
        if named:
            hits.append(
                f"{path.relative_to(root)}:{node.lineno} states a citation span "
                f"({', '.join(sorted(named))}) instead of computing it; use "
                "packages.contracts.citations.locate() (INV-8)"
            )
    return hits


def check_architecture(root, skip_dirs):
    """Repo-specific structural invariants (INVARIANTS.md). Add rules below.
    Ships empty so it passes out of the box and never false-positives before you
    have anything to enforce."""
    v = []

    # INV-8 · a citation's span is COMPUTED from the text, never asserted beside
    # the quote.
    #
    # This is the shape audit finding #3 found: `span_start=0, span_end=1` next
    # to a forty-character quote satisfied every check in the system, and the
    # figure read as cited while resolving to nothing. `locate()` and
    # `locate_pattern()` in packages/contracts/citations.py take a quote or a
    # pattern and return the offsets they found — there is no parameter through
    # which a caller can supply one. This keeps it that way: an extractor cannot
    # write a wrong span because it cannot write a span at all.
    #
    # Scoped to the producers. Tests construct spans deliberately, to prove the
    # guards refuse bad ones, and a rule that forbade that would forbid its own
    # negative cases.
    # Parsed rather than grepped. A regex over lines flagged this rule's own
    # explanation of itself, and the obvious repair — rewording the prose — puts
    # the guard at the mercy of how the next person phrases a docstring. The
    # syntax tree only ever sees `span_start=` where it is actually an argument.
    for p in _iter_src(root, skip_dirs, ("ingest", "packages", "api", "evals"), {".py"}):
        if p.name in ("citations.py",):  # the sanctioned producer
            continue
        v.extend(_hand_written_spans(p, root))

    # ── Add a rule each time you name an invariant that types/tests can't span.
    # Copy a block, scope it to the right dirs/suffixes, and cite the INV id.
    #
    # Single source of truth — a UI/query layer must READ a derived column, never
    # re-derive it from raw signals another module owns:
    #   raw = re.compile(r"RAW_SIGNAL_A|RAW_SIGNAL_B")
    #   for p in _iter_src(root, skip_dirs, ("web", "query"), {".sql", ".ts", ".py"}):
    #       for i, ln in enumerate(p.read_text(errors="ignore").splitlines(), 1):
    #           if raw.search(ln):
    #               v.append(
    #                   f"{p.relative_to(root)}:{i} re-derives a value "
    #                   "another module owns (INV-?)"
    #               )
    #
    # No privileged/secret key in client code:
    #   svc = re.compile(r"SERVICE_ROLE_KEY|ADMIN_TOKEN|PRIVILEGED")
    #   for p in _iter_src(root, skip_dirs, ("web",), {".ts", ".tsx", ".js", ".env"}):
    #       for i, ln in enumerate(p.read_text(errors="ignore").splitlines(), 1):
    #           if svc.search(ln):
    #               v.append(f"{p.relative_to(root)}:{i} privileged key in client code (INV-?)")
    #
    # Funnel a shared concern (HTTP, logging) through one entry point:
    #   http = re.compile(r"\brequests\.(get|post|put|delete)\(")
    #   for p in _iter_src(root, skip_dirs, ("pipeline",), {".py"}):
    #       if p.name == "http.py":  # the sanctioned entry point
    #           continue
    #       ...

    if v:
        return ("FAIL", "\n".join(v))
    return (
        "OK",
        "architecture invariants hold"
        if _rule_count
        else (
            "no architecture rules yet — add them in scripts/arch_checks.py as you name invariants"
        ),
    )


# True once real rules exist, so the OK line reads "invariants hold" instead of
# the "none yet" nudge.
_rule_count = True


def check_ignore_budget(root, tracked_files, budget_dir, fix=False, ratchet=False):
    """Gate-gaming ratchet: type-ignore and lint-suppression comments are a
    ceiling that only falls, so no one can quietly silence the type or lint
    checks to go green. Split patterns so this file doesn't match itself."""
    bf = budget_dir / "ignore-budget.json"
    budget = json.loads(bf.read_text()) if bf.exists() else {"max_ignores": 0}
    cap = budget.get("max_ignores", 0)
    pat = re.compile(r"# *ty" + r"pe: *ignore|# *no" + r"qa")
    hits = []
    for f in tracked_files:
        if f.suffix == ".py" and f.is_file():
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if pat.search(line):
                    hits.append(f"{f.relative_to(root)}:{i}")
    if fix or (ratchet and len(hits) < cap):
        budget["max_ignores"] = len(hits)
        bf.write_text(json.dumps(budget, indent=2) + "\n")
        verb = "set to" if fix else f"ratcheted {cap} →"
        return ("OK", f"ignore ceiling {verb} {len(hits)}")
    if len(hits) > cap:
        return (
            "FAIL",
            f"{len(hits)} suppression comment(s) > ceiling {cap} "
            "(don't suppress checks to go green)\n" + "\n".join(hits[:20]),
        )
    return ("OK", f"{len(hits)} suppressions ≤ ceiling {cap}")


def check_invariant_matrix(root: Path) -> tuple[str, str]:
    """Every invariant must be named by each layer that has to enforce it.

    Two review rounds in a row found the same defect: a rule enforced on one
    side only, with the fixed half making the other look covered. This turns
    that from something a reviewer might spot into a cell that is empty.
    """
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "invariant_matrix.py"), "--check"],
        capture_output=True,
        text=True,
    )
    if r.returncode:
        tail = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("-")]
        return "FAIL", "invariant coverage gaps:\n" + "\n".join(tail)
    return "OK", "every invariant named by each layer that enforces it"
