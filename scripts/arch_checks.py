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

import ast
import json
import os
import re
from collections.abc import Container, Iterable, Iterator, Sequence
from pathlib import Path

#: Directories that hold Python but are not the product: the answer key, the
#: negative cases, and the tooling. Everything else is a producer and is
#: scanned. Named as exclusions rather than as an allowlist so that adding a
#: package cannot silently opt it out of a rule.
#:
#: An exclusion is only honest while the excluded directory really is not the
#: product, so `_excluded_but_imported` below turns the other half into a check:
#: a directory in here that product code imports is a producer wearing an
#: exemption, and it fails.
NOT_PRODUCERS = frozenset({"tests", "evals", "scripts", "web", "supabase", "docs"})


def _producer_packages(root: Path) -> tuple[str, ...]:
    """Every top-level product directory, discovered rather than listed.

    A directory counts if it contains Python at all. The first version required
    an `__init__.py`, which was a proxy for "importable by the application" and
    a wrong one: PEP 420 namespace packages import perfectly well without it, so
    deleting one file took a whole directory out of every rule below, silently.
    Nothing else in this repo depends on the file being there either.
    """
    return tuple(
        sorted(
            d.name
            for d in root.iterdir()
            if d.is_dir()
            and not d.name.startswith(".")
            and d.name not in NOT_PRODUCERS
            and any(d.rglob("*.py"))
        )
    )


def _iter_src(
    root: Path, skip_dirs: Container[str], subdirs: Sequence[str], suffixes: Container[str]
) -> Iterator[Path]:
    """Yield working-tree source files under the given repo-relative subdirs,
    pruning vendored/build dirs. Working-tree (not git-tracked) so staged files
    are covered pre-commit and violations surface before they're committed.

    Symlinked subdirectories are followed. `os.walk` does not follow them by
    default, so a directory reachable and importable through a symlink inside a
    scanned package was not scanned — the rule was one `ln -s` away from being
    optional. Real paths are remembered so a cycle terminates.
    """
    seen: set[str] = set()
    for sub in subdirs:
        base = root / sub
        if not base.exists():
            continue
        if base.is_file():
            if base.suffix in suffixes:
                yield base
            continue
        for dp, dns, fns in os.walk(base, followlinks=True):
            real = os.path.realpath(dp)
            if real in seen:
                dns[:] = []
                continue
            seen.add(real)
            dns[:] = [d for d in dns if d not in skip_dirs]
            for fn in fns:
                p = Path(dp) / fn
                if p.suffix in suffixes and p.is_file():
                    yield p


def _producer_sources(root: Path, skip_dirs: Container[str]) -> Iterator[Path]:
    """Every product `.py` file: the top-level packages, and the modules that
    sit at the repository root beside them.

    Root modules were outside every scope this file defines, so moving a file
    up one directory removed it from the rule.
    """
    subdirs = list(_producer_packages(root))
    subdirs += [f.name for f in sorted(root.glob("*.py")) if not f.name.startswith(".")]
    yield from _iter_src(root, skip_dirs, subdirs, {".py"})


#: The two fields that must never be typed by a human. INV-8.
_SPAN_FIELDS = {"span_start", "span_end"}

#: The one file allowed to state a span, because it is where a span is computed.
#:
#: A FULL repo-relative path, not a basename. The exemption used to compare
#: `p.name == "citations.py"`, so any file anywhere called `citations.py` was
#: outside the rule — an extractor could opt out of INV-8 by choosing a
#: filename, which is not a decision anyone would notice being made.
SANCTIONED_SPAN_PRODUCER = Path("packages/contracts/citations.py")


def _excluded_but_imported(root: Path, sources: Iterable[Path]) -> list[str]:
    """A directory excluded from the producer scan that the product imports.

    `NOT_PRODUCERS` is a claim about what those directories are, and the claim
    is what makes excluding them safe. Nothing checked it, so the cheapest way
    to leave a rule was to put the code somewhere the rule does not look. This
    is that claim as a check: if product code imports it, it is product code.
    """
    hits: list[str] = []
    for path in sources:
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue  # reported by _hand_written_spans, which parses the same file
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                if top in NOT_PRODUCERS and (root / top).is_dir():
                    hits.append(
                        f"{path.relative_to(root)}:{node.lineno} imports `{top}`, which is "
                        "excluded from the producer scan — a directory the product imports "
                        "is a producer, so either the import or the exclusion is wrong (INV-8)"
                    )
    return hits


def _hand_written_spans(path: Path, root: Path) -> list[str]:
    """Every place this file states a citation offset instead of computing one.

    Catches both shapes an offset can arrive in: a keyword argument to a call
    (`Citation(span_start=0, ...)`) and a mapping key (`{"span_start": 0}`),
    which is the same assertion wearing a different hat and is how the rule
    would otherwise be walked around without anyone intending to.
    """
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


def check_architecture(root: Path, skip_dirs: Container[str]) -> tuple[str, str]:
    """Repo-specific structural invariants (INVARIANTS.md). Add rules below.
    Ships empty so it passes out of the box and never false-positives before you
    have anything to enforce."""
    v: list[str] = []

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
    #
    # The tuple is a HARDCODED LIST OF DIRECTORIES, which means a new producer
    # package escapes the rule by existing. That is what happened: `evidence/`
    # and `packet/` were both written after this line, and `evidence/` is the
    # one directory in the repo where a *model* proposes a quote — precisely
    # where an unchecked span would matter most. Neither was scanned, and
    # nothing went red, because the rule's scope is a list rather than a
    # question about what a directory does.
    #
    # Derived instead: every top-level package that is not a test, a script, or
    # the answer key. A directory added tomorrow is covered on the day it is
    # created, which is the difference between a guard and a note.
    #
    # Deriving it once was not enough. A verification pass put four kinds of
    # file back outside the scope — a namespace package with no `__init__.py`, a
    # module at the repository root, a directory reached through a symlink, and
    # any file named `citations.py` — and every one of them reported OK while
    # stating a span. Each is closed where it is caused: in
    # `_producer_packages`, in `_producer_sources`, in `_iter_src`, and in the
    # full-path comparison below.
    sources = list(_producer_sources(root, skip_dirs))
    for p in sources:
        if p.relative_to(root) == SANCTIONED_SPAN_PRODUCER:
            continue
        v.extend(_hand_written_spans(p, root))
    v.extend(_excluded_but_imported(root, sources))

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


def check_ignore_budget(
    root: Path,
    tracked_files: Iterable[Path],
    budget_dir: Path,
    fix: bool = False,
    ratchet: bool = False,
) -> tuple[str, str]:
    """Gate-gaming ratchet: type-ignore and lint-suppression comments are a
    ceiling that only falls, so no one can quietly silence the type or lint
    checks to go green. Split patterns so this file doesn't match itself."""
    bf = budget_dir / "ignore-budget.json"
    budget = json.loads(bf.read_text()) if bf.exists() else {"max_ignores": 0}
    cap = budget.get("max_ignores", 0)
    # Per-line suppressions were the whole pattern, and the file-level form is
    # strictly stronger: two lines at the top of a file —
    #   (mypy directive) ignore-errors
    #   (ruff directive) noqa
    # — turn both checkers off for everything below them, and the ceiling still
    # read zero, because neither line contains the per-line spelling. A file
    # containing an undefined name passed mypy and Ruff with both at exit 0.
    #
    # Literals split so this file does not count itself.
    pat = re.compile(
        r"# *ty" + r"pe: *ignore"
        r"|# *no" + r"qa"
        r"|# *(?:my" + r"py|ru" + r"ff|fla" + r"ke8) *:"
    )
    hits: list[str] = []
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
