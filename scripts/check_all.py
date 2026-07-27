#!/usr/bin/env python3
"""Agent-ready verification harness — one deterministic gate the agent cannot bypass.

Detects Python sub-projects (dirs containing pyproject.toml) and enforces:
lint, format, types (mypy), tests + coverage floor, a floor on how many tests
exist, database guards actually running rather than skipping
(REQUIRE_DB_TESTS=1), duplicate code, file-size limits, debt markers,
architecture invariants (INVARIANTS.md, via arch_checks), suppression budget,
secrets (detect-secrets), security SAST (bandit), dependency CVEs (pip-audit),
CLAUDE.md path alignment, and CI parity. Budgets live in scripts/budgets/ and
ratchet forward — they only get stricter.

One rule sits above all of them: a check that could not run reports FAIL. SKIP
and WARN do not aggregate into "all checks passed", and the two checks allowed
to say they could not run are named in main() with the reason. A tool that
crashed, a suite that skipped, a workflow that mentions the gate in a comment
and a discovery pass that found nothing are all the same defect — a green tick
over an empty measurement — and this file has now been repaired for it
fourteen times.

  python3 scripts/check_all.py                # run the full gate (pre-commit + CI)
  python3 scripts/check_all.py --init-budgets # baseline the ratchets to current state
  python3 scripts/check_all.py --ratchet      # tighten budgets to current (never looser)
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import arch_checks  # architecture-invariant checks (INVARIANTS.md); scripts/ on sys.path

_top = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
).stdout.strip()
ROOT = Path(_top) if _top else Path.cwd()
BUD = ROOT / "scripts" / "budgets"
SRC_EXT = {".py", ".sql"}  # .ts/.tsx/.js/.jsx are owned by check-all.mjs when present
# Split the literal markers so this file does not match its own debt scan.
_MARKERS = ["TO" + "DO", "FIX" + "ME", "XX" + "X", "HA" + "CK"]
DEBT_RE = re.compile(r"\b(" + "|".join(_MARKERS) + r")\b")


def sh(
    cmd: Sequence[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env={**os.environ, **env} if env else None
    )


def tracked() -> list[Path]:
    out = sh(["git", "ls-files"], cwd=ROOT).stdout.splitlines()
    return [ROOT / f for f in out]


_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "site-packages",
    "build",
    "dist",
    ".tox",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".worktrees",
    "worktrees",
    ".claude",
}


def py_projects() -> list[Path]:
    # a real project's pyproject.toml — never one inside an installed dep
    # (.venv/.../stevedore/example2/) or a git worktree (.worktrees/…,
    # .claude/worktrees/…). Prune skip dirs DURING the walk so we never
    # descend into node_modules/.venv (rglob would walk them all first).
    out = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if "pyproject.toml" in filenames:
            out.add(Path(dirpath))
    return sorted(out)


def load(name: str, default: dict[str, Any]) -> dict[str, Any]:
    f = BUD / name
    if not f.exists():
        return dict(default)
    stored: dict[str, Any] = json.loads(f.read_text())
    return stored


def save(name: str, data: dict[str, Any]) -> None:
    (BUD / name).write_text(json.dumps(data, indent=2) + "\n")


def venv_bin(p: Path) -> Path | None:
    """Per-project .venv/bin, if the project has one — else None."""
    for name in ("bin", "Scripts"):
        vb = p / ".venv" / name
        if vb.is_dir():
            return vb
    return None


def project_python(p: Path) -> str:
    vb = venv_bin(p)
    if vb:
        for exe in ("python", "python.exe"):
            if (vb / exe).exists():
                return str(vb / exe)
    return sys.executable


def _tool_for(p: Path, name: str) -> str | None:
    vb = venv_bin(p)
    search_path = f"{vb}{os.pathsep}{os.environ.get('PATH', '')}" if vb else None
    return shutil.which(name, path=search_path)


def ruff_for(p: Path) -> str | None:
    return _tool_for(p, "ruff")


# A required check has no way of saying "I could not run". SKIP and WARN both
# printed a symbol and then aggregated into "all checks passed", so a missing
# ruff, mypy, pytest, jscpd, detect-secrets or bandit read the same as a clean
# one. The only sanctioned SKIPs are declared in main(); everything else that
# cannot run says FAIL and says why.
MISSING_TOOL = "{tool} not installed — required check cannot SKIP ({how})"


def check_lint(projects: Sequence[Path]) -> tuple[str, str]:
    fails, missing = [], []
    for p in projects:
        rb = ruff_for(p)
        if not rb:
            missing.append(p.name)
            continue
        r = sh([rb, "check", str(p)])
        if r.returncode:
            fails.append(r.stdout + r.stderr)
    if fails:
        return ("FAIL", "\n".join(fails))
    if missing:
        return (
            "FAIL",
            MISSING_TOOL.format(tool="ruff", how="pip install ruff, or add it to a project .venv")
            + f"\nnot found for: {', '.join(missing)}",
        )
    return ("OK", f"{len(projects)} project(s) clean")


def check_format(projects: Sequence[Path]) -> tuple[str, str]:
    fails, missing = [], []
    for p in projects:
        rb = ruff_for(p)
        if not rb:
            missing.append(p.name)
            continue
        r = sh([rb, "format", "--check", str(p)])
        if r.returncode:
            fails.append(r.stdout)
    if fails:
        return ("FAIL", "\n".join(fails) + "\nrun: ruff format .")
    if missing:
        return (
            "FAIL",
            MISSING_TOOL.format(tool="ruff", how="pip install ruff")
            + f"\nnot found for: {', '.join(missing)}",
        )
    return ("OK", "formatted")


def check_types(
    projects: Sequence[Path], fix: bool = False, ratchet: bool = False
) -> tuple[str, str]:
    """mypy as a ratchet: the type-error count is a ceiling that only falls.
    Existing untyped code is baselined so it doesn't block, but no new type
    error can slip in. Tighten per-project strictness in [tool.mypy]."""
    budget = load("mypy.json", {"max_errors": 0})
    cap = budget.get("max_errors", 0)
    total, ran, missing, sample, crashed = 0, False, [], [], []
    for p in projects:
        mb = _tool_for(p, "mypy")
        if not mb:
            missing.append(p.name)
            continue
        ran = True
        # `--explicit-package-bases` with the project root as the base, because
        # without it mypy reached `scripts/capture_web_fixture.py` by two paths,
        # called it two module names, and ABORTED with exit 2 having checked
        # nothing. The gate read that as "no lines matched `: error:`" and
        # printed `0 type errors ≤ ceiling 79` for as long as the collision
        # existed. Naming the base makes every module resolve the way it does at
        # runtime — `api.config`, `packages.contracts` — instead of depending on
        # which directory mypy happened to walk from.
        r = sh(
            [
                mb,
                ".",
                "--ignore-missing-imports",
                "--no-error-summary",
                "--explicit-package-bases",
                "--exclude",
                r"(\.venv|node_modules|build|dist)/",
            ],
            cwd=p,
            env={"MYPYPATH": str(p)},
        )
        errs = [ln for ln in (r.stdout + r.stderr).splitlines() if ": error:" in ln]
        # mypy exits 0 when it found nothing and 1 when it found errors. Any
        # other status — a crash, a bad flag, a binary that is not mypy — is a
        # run that did not happen, and so is exit 1 with nothing parseable to
        # show for it. This used to be read as "no lines matched `: error:`,
        # therefore zero type errors": replacing the binary with /usr/bin/false
        # reported a clean type check against a ceiling of 79.
        if r.returncode not in (0, 1) or (r.returncode and not errs):
            crashed.append(
                f"{p.name}: mypy exited {r.returncode} with no parseable errors\n"
                + (r.stdout + r.stderr)[-800:]
            )
            continue
        total += len(errs)
        sample += errs[:5]
    if crashed:
        return ("FAIL", "the type check did not run:\n" + "\n".join(crashed))
    if missing or not ran:
        return (
            "FAIL",
            MISSING_TOOL.format(tool="mypy", how="pip install mypy, or add it to a project .venv")
            + (f"\nnot found for: {', '.join(missing)}" if missing else ""),
        )
    if fix:
        budget["max_errors"] = total
        save("mypy.json", budget)
        return ("OK", f"type-error ceiling set to {total}")
    if ratchet and total < cap:
        budget["max_errors"] = total
        save("mypy.json", budget)
        return ("OK", f"type-error ceiling ratcheted {cap} → {total}")
    if total > cap:
        return ("FAIL", f"{total} type errors > ceiling {cap}\n" + "\n".join(sample[:10]))
    nudge = f"  (ratchet ceiling down toward {total})" if cap - total > 0 else ""
    return ("OK", f"{total} type errors ≤ ceiling {cap}{nudge}")


#: pytest's own tally line — "40 passed, 1 skipped in 0.31s". Read rather than
#: trusted: a line this cannot parse is a FAIL, because an unreadable summary
#: must never resolve to "nothing was skipped".
TALLY = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed|deselected)\b")


def _tally(text: str) -> dict[str, int]:
    """The last parseable tally line in a pytest run, as {kind: count}."""
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        found = TALLY.findall(line)
        if found:
            return {kind: int(n) for n, kind in found}
    return {}


#: Every project's pytest output from the last check_tests() run, keyed by
#: project name. check_db_guards() reads the skip report out of it instead of
#: running a hand-listed subset of suites a second time — see the comment there.
#: Empty is not "nothing skipped"; it is "no run to read", which is a FAIL.
_TEST_REPORTS: dict[str, str] = {}


def check_tests(
    projects: Sequence[Path], fix: bool = False, ratchet: bool = False
) -> tuple[str, str]:
    budget = load("coverage.json", {"floor": 0.0})
    floor = budget.get("floor", 0.0)
    fails, total, ran, missing = [], None, False, []
    _TEST_REPORTS.clear()
    for p in projects:
        py = project_python(p)
        if sh([py, "-c", "import pytest"]).returncode:
            missing.append(p.name)
            continue
        ran = True
        has_cov = sh([py, "-c", "import pytest_cov"]).returncode == 0
        # `-rs` prints one SKIPPED line per skipped test, with the reason pytest
        # was given. It is what check_db_guards() reads: the set of suites that
        # need a database is derived from what actually skipped and why, rather
        # than from a list of filenames somebody has to remember to grow.
        cmd = [py, "-m", "pytest", "-q", "-rs"]
        jp = p / ".coverage.json"
        if has_cov:
            cmd += [f"--cov={p}", f"--cov-report=json:{jp}", "--cov-report="]
        r = sh(cmd, cwd=p)
        _TEST_REPORTS[p.name] = r.stdout + r.stderr
        if r.returncode:
            fails.append(f"{p.name}:\n{(r.stdout + r.stderr)[-1500:]}")
        else:
            # A run in which nothing executed is not a passing run. A project
            # whose every test skipped returned OK with 100% coverage, because
            # "pytest exited 0" and "the tests pass" were treated as the same
            # sentence.
            tally = _tally(r.stdout)
            if not tally:
                fails.append(f"{p.name}: pytest exited 0 but printed no tally to read")
            elif not tally.get("passed"):
                fails.append(
                    f"{p.name}: {sum(tally.values())} test(s) collected and none passed "
                    f"({', '.join(f'{v} {k}' for k, v in sorted(tally.items()))}) — "
                    "a suite in which nothing ran is not a suite that passed"
                )
        if has_cov and jp.exists():
            pc = json.loads(jp.read_text()).get("totals", {}).get("percent_covered", 0)
            jp.unlink()
            total = pc if total is None else min(total, pc)
    if missing or not ran:
        return (
            "FAIL",
            MISSING_TOOL.format(
                tool="pytest", how="pip install pytest, or add it to a project .venv"
            )
            + (f"\nnot found for: {', '.join(missing)}" if missing else ""),
        )
    if fails:
        return ("FAIL", "tests failed\n" + "\n".join(fails))
    if total is None:
        return ("OK", "tests pass (coverage off: pip install pytest-cov)")
    # Owner's decision, recorded rather than silently dropped: the coverage
    # FLOOR is not a gate on this project. It is reported at every run so a
    # collapse is still visible, but it cannot turn the gate red.
    #
    # The reason is that it stopped measuring anything useful here. The floor
    # had ratcheted to 98.25% and the last three-hundredths of a percent were
    # CLI `main()` bodies and `except` arms of loaders — while the checks that
    # actually defend a wrong number are elsewhere and are not percentages:
    # `tests/test_policy_vs_oracle.py` compares 175 requirement verdicts
    # against an independently derived answer key, `scripts/mutate.py` proves
    # every guard goes red when removed, and the database refuses what the
    # schema forbids. A number that must be pushed up by testing argparse is a
    # number that has stopped tracking correctness.
    #
    # `--ratchet` still records where it stands, so the figure keeps moving in
    # one direction and the decision can be reversed by deleting this block.
    if floor and not (fix or ratchet):
        return ("OK", f"tests pass · coverage {total:.2f}% (floor not enforced — owner's call)")
    if fix:
        budget["floor"] = math.floor(total * 100) / 100
        save("coverage.json", budget)
        return ("OK", f"tests pass · coverage floor set to {total:.2f}%")
    if ratchet and total > floor:
        budget["floor"] = math.floor(total * 100) / 100
        save("coverage.json", budget)
        return ("OK", f"tests pass · coverage floor ratcheted {floor}% → {total:.2f}%")
    if total + 1e-9 < floor:
        return ("FAIL", f"tests pass but coverage {total:.2f}% < floor {floor}%")
    nudge = f"  (ratchet floor up toward {total:.1f}%)" if total - floor > 1 else ""
    return ("OK", f"tests pass · coverage {total:.2f}% ≥ floor {floor}%{nudge}")


#: The skips that are correct rather than missing coverage, matched on the
#: reason pytest was given rather than on the file that gave it.
#:
#: Every one names the same condition: the fund's case-study material is private,
#: gitignored, and will never be present in CI. Failing on those would make the
#: gate permanently red for a state that is right.
#:
#: This list is the whole of what is allowed. A skip for any other reason —
#: including every way of spelling "there is no database" — is a guard that did
#: not run, and a guard that did not run is a FAIL. That direction is the fix:
#: the previous version listed the SUITES that must not skip, so a suite nobody
#: added to the list skipped in silence, and the list was short three times in a
#: row. A new suite is covered on the day it is written, because it is covered by
#: default.
SANCTIONED_SKIPS = (
    "case-study workbooks are not in the repository",
    "case-study documents are not in the repository",
    "case-study document is not in the repository",
    "the case-study document or its recording is not in the repository",
    "the `demo` schema holds no loaded corpus",
)

#: pytest's `-rs` short summary: "SKIPPED [3] tests/test_packet_export.py:483: no DATABASE_URL".
SKIPPED_LINE = re.compile(r"^SKIPPED \[\d+\] ")


def check_db_guards() -> tuple[str, str]:
    """Fail when any test skipped for a reason that is not sanctioned.

    Gated on REQUIRE_DB_TESTS=1, which CI sets alongside a Postgres service;
    locally, without a database, this reports SKIP with its reason rather than
    blocking a commit.

    It reads the skip report of the run `check_tests` already performed rather
    than running a second, hand-listed subset. Two things follow. The set of
    database-backed suites is DERIVED — whatever skipped for want of a DSN is
    named by pytest itself, so deleting a suite from a list cannot hide it and
    a new suite needs no registration. And there is no second pytest invocation
    to drift from the first.

    An absent report is a FAIL, not a pass: "no run to read" and "nothing
    skipped" are different sentences and were being collapsed into one.
    """
    if os.environ.get("REQUIRE_DB_TESTS") != "1":
        return ("SKIP", "REQUIRE_DB_TESTS is not 1 — guards optional here; CI sets it")
    if not _TEST_REPORTS:
        return (
            "FAIL",
            "no pytest output to read — the tests check did not produce a skip report, "
            "so nothing here shows the database guards ran",
        )
    problems, total_ran, total_skipped = [], 0, 0
    for name, out in _TEST_REPORTS.items():
        tally = _tally(out)
        if not tally:
            problems.append(
                f"{name}: pytest printed no tally — refusing to assume nothing skipped\n"
                + out[-1200:]
            )
            continue
        total_ran += sum(tally.values())
        total_skipped += tally.get("skipped", 0)
        unexpected = [
            ln
            for ln in out.splitlines()
            if SKIPPED_LINE.match(ln) and not any(s in ln for s in SANCTIONED_SKIPS)
        ]
        if unexpected:
            problems.append(
                f"{name}: {len(unexpected)} test(s) SKIPPED for a reason that is not "
                "sanctioned — a skipped guard is not a passing guard. If it is the "
                "database, point MIGRATION_DATABASE_URL and DATABASE_URL at one with "
                "supabase/migrations applied; if the reason is genuinely permanent in "
                "CI, add it to SANCTIONED_SKIPS deliberately.\n" + "\n".join(unexpected[:10])
            )
    if problems:
        return ("FAIL", "\n".join(problems))
    return (
        "OK",
        f"{total_ran} test(s) reported, {total_skipped} skipped and every skip sanctioned",
    )


def check_test_inventory(fix: bool = False, ratchet: bool = False) -> tuple[str, str]:
    """A floor on how many tests exist, so deleting guards is not a quiet act.

    The check above proves that whatever ran was not silently skipped. It cannot
    see a suite that no longer exists — a deleted or renamed file collects
    nothing, skips nothing, and reads as clean. The list this replaced caught
    that by naming files; a count catches it without naming anything, and covers
    files the list never knew about.

    Counted by collection, not by execution, so it is the same number with or
    without a database and takes about ten seconds.
    """
    budget = load("tests.json", {"min_tests": 0})
    floor = budget.get("min_tests", 0)
    r = sh(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
    )
    m = re.search(r"(\d+) tests? collected", r.stdout)
    found = int(m.group(1)) if m else 0
    if r.returncode or not found:
        return (
            "FAIL",
            f"collection failed (exit {r.returncode}) — the test inventory is unknown, "
            "which is not the same as unchanged\n" + (r.stdout + r.stderr)[-1200:],
        )
    if fix or (ratchet and found > floor):
        budget["min_tests"] = found
        save("tests.json", budget)
        verb = "set to" if fix else f"ratcheted {floor} →"
        return ("OK", f"test-count floor {verb} {found}")
    if found < floor:
        return (
            "FAIL",
            f"{found} tests collected < floor {floor} — {floor - found} test(s) went missing. "
            "Deleting a suite is a decision, not a refactor; if it was deliberate, "
            "re-baseline with --init-budgets.",
        )
    nudge = f"  (ratchet floor up toward {found})" if found - floor > 0 else ""
    return ("OK", f"{found} tests collected ≥ floor {floor}{nudge}")


def check_dups() -> tuple[str, str]:
    if not (ROOT / ".jscpd.json").exists():
        return ("FAIL", "no .jscpd.json — the duplicate-code check is required, not optional")
    if not shutil.which("npx"):
        return ("FAIL", MISSING_TOOL.format(tool="npx/node", how="install Node; jscpd needs it"))
    r = sh(["npx", "--yes", "jscpd", "--config", str(ROOT / ".jscpd.json")], cwd=ROOT)
    return (
        ("OK", "no clones above threshold")
        if r.returncode == 0
        else (
            "FAIL",
            (r.stdout + r.stderr)[-1800:],
        )
    )


def check_file_sizes(fix: bool = False) -> tuple[str, str]:
    budget = load("file-sizes.json", {"max_lines": 600, "overrides": {}})
    mx, ov = budget["max_lines"], budget.get("overrides", {})
    over = []
    for f in tracked():
        if f.suffix in SRC_EXT and f.is_file():
            n = sum(1 for _ in f.open("rb"))
            rel = str(f.relative_to(ROOT))
            if n > ov.get(rel, mx):
                over.append((rel, n))
    if fix:
        for rel, n in over:
            ov[rel] = n
        budget["overrides"] = ov
        save("file-sizes.json", budget)
        return ("OK", f"baselined {len(over)} file(s) over {mx} lines")
    # Owner's decision, recorded rather than silently dropped: file length is
    # reported, never enforced. It is a proxy for "this module does too many
    # things", and on this project the proxy stopped tracking the thing —
    # splitting a passing test suite to save seven lines is ceremony, and the
    # split that mattered (`to_lots.py` out of `to_contracts.py`) was worth
    # doing for its own reason and would have been done without a limit.
    #
    # Reported so a file that doubles is still visible in the run. Restoring
    # enforcement means turning this return back into a FAIL.
    if over:
        lines = [f"{rel} = {n} lines" for rel, n in over]
        return ("OK", f"{len(over)} file(s) over {mx} lines (not enforced): " + ", ".join(lines))
    return ("OK", f"all source files ≤ {mx} lines")


def check_debt(fix: bool = False, ratchet: bool = False) -> tuple[str, str]:
    budget = load("debt-allowlist.json", {"max_markers": 0})
    cap = budget.get("max_markers", 0)
    hits = []
    for f in tracked():
        if f.suffix in SRC_EXT and f.is_file():
            for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                if DEBT_RE.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{i}")
    if fix:
        budget["max_markers"] = len(hits)
        save("debt-allowlist.json", budget)
        return ("OK", f"debt ceiling set to {len(hits)}")
    if ratchet and len(hits) < cap:
        budget["max_markers"] = len(hits)
        save("debt-allowlist.json", budget)
        return ("OK", f"debt ceiling ratcheted {cap} → {len(hits)}")
    if len(hits) > cap:
        return ("FAIL", f"{len(hits)} debt markers > ceiling {cap}\n" + "\n".join(hits[:20]))
    return ("OK", f"{len(hits)} debt markers ≤ ceiling {cap}")


_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_FENCED_WORD = re.compile(r"[A-Za-z0-9_./-]+")


def markdown_paths(text: str) -> list[str]:
    """Every token in a markdown file that could be naming a path.

    The extractor was `re.findall(r"`([^`]+)`", whole_file)`, and a fenced code
    block silently inverts what that pairs. An opening fence is three
    backticks: the scanner consumes the third as an opening delimiter, closes
    it on the FIRST backtick of the closing fence, and from there on it pairs
    the prose BETWEEN inline spans rather than the spans themselves. Every one
    of those prose runs contains a space, so the filter below discarded them
    without a word — and every real inline path below the fence was never
    looked at.

    In this repository that hid nine of the eleven sections: appending
    `xyz/nonexistent` to the end of CLAUDE.md was not detected, while breaking
    a token above the Commands block was. The check printed "referenced paths
    exist" having read a quarter of the file.

    So fences are separated from prose before anything is paired. Prose
    contributes its inline spans. A fence contributes its own words, because
    the Commands block lists the scripts an agent is told to run and it was the
    one part of the file this check had never read at all.
    """
    prose: list[str] = []
    fenced: list[str] = []
    fence = ""
    for line in text.splitlines():
        m = _FENCE.match(line)
        marker = m.group(1)[0] * 3 if m else ""
        if not fence:
            if marker:
                fence = marker
            else:
                prose.append(line)
        elif marker == fence:
            fence = ""
        else:
            fenced.append(line)
    toks = re.findall(r"`([^`]+)`", "\n".join(prose))
    return toks + _FENCED_WORD.findall("\n".join(fenced))


def _git_ignored(rels: Sequence[str]) -> set[str]:
    """Which of these repository-relative paths git ignores. Tracked paths are
    never reported, which is what `check-ignore` does by default."""
    if not rels:
        return set()
    r = sh(["git", "check-ignore", "--", *rels], cwd=ROOT)
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def check_claude_md() -> tuple[str, str]:
    """The paths CLAUDE.md points an agent at still exist. Its failure mode is
    a doc that survives a rename and quietly misdirects every reader after it.
    """
    candidates: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for name in ("CLAUDE.md", "AGENTS.md"):
        cf = ROOT / name
        if not cf.exists():
            continue
        # In this repository CLAUDE.md is a symlink to AGENTS.md, so the two
        # names are one inode and every finding was reported twice — a reader
        # counting the lines would think two files disagreed with the tree.
        # A repository where the two are genuinely separate files still gets
        # both, because this compares what they resolve to and not their names.
        real = cf.resolve()
        if real in seen:
            continue
        seen.add(real)
        for raw in markdown_paths(cf.read_text()):
            tok = raw.strip()
            if " " in tok or any(c in tok for c in "*<>"):
                continue
            # A leading separator is an absolute path or the scheme-relative
            # tail of a URL (`//example.com/x`, once the charset above has
            # dropped the colon). Neither is a path in this repository.
            if tok.startswith(("http", "npm ", "git ", "localhost", "/")):
                continue
            # A separator BETWEEN two segments is what makes a token a
            # repository-relative path. `triage/` and `queue/` in the review
            # section are bare directory names — the sentence beside them
            # spells the anchored form, `.captain/review/triage/` — and
            # resolving a bare name against the root reports drift that is not
            # there. The cost is that a bare `web/` goes unchecked; no token
            # this check has ever verified is of that shape.
            if "/" not in tok.strip("/"):
                continue
            if (ROOT / tok.rstrip("/")).exists():
                continue
            candidates.append((name, tok))
    # A path git ignores is present on some machines and absent on others:
    # `.venv/bin/python` and everything under `.captain/` exist locally and do
    # not exist in a CI checkout at all. Reporting those as documentation drift
    # would make this check's verdict depend on which machine ran it, which is
    # the one thing a gate may not do.
    ignored = _git_ignored([tok.rstrip("/") for _, tok in candidates])
    missing = [f"{n}: `{t}`" for n, t in candidates if t.rstrip("/") not in ignored]
    if missing:
        return ("WARN", "paths referenced but not found:\n" + "\n".join(missing))
    return ("OK", "referenced paths exist")


_RUN_KEY = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")
_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_.\-]+):\s*$")
_DISABLED = re.compile(r"^    if:\s*(?:false|'false'|\"false\")\s*$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def workflow_commands(text: str) -> str:
    """Every shell command a workflow would actually run.

    Parity used to be `gate_name in file_text`, which a comment satisfies: a
    workflow whose entire content was `# Historical names only: check_all.py and
    check-all.mjs` reported that CI ran the same gate as local. So does a job
    switched off with `if: false`, and so does a name mentioned in a step's
    `name:` while the `run:` beneath it invokes something else.

    Comments are dropped, disabled jobs are dropped, and only the bodies of
    `run:` steps are returned — the text that becomes a shell command and
    nothing else.
    """
    lines = text.splitlines()
    # Job blocks first, so a job turned off with `if: false` contributes nothing.
    live, i = [], 0
    while i < len(lines):
        m = _JOB_KEY.match(lines[i])
        if not m:
            live.append(lines[i])
            i += 1
            continue
        block, i = [lines[i]], i + 1
        while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > 2):
            block.append(lines[i])
            i += 1
        if not any(_DISABLED.match(b) for b in block):
            live += block

    out, i = [], 0
    while i < len(live):
        line = live[i]
        if line.lstrip().startswith("#"):
            i += 1
            continue
        m = _RUN_KEY.match(line)
        if not m:
            i += 1
            continue
        key_indent, rest = len(m.group(1)), m.group(2).strip()
        i += 1
        if rest and rest.rstrip("+-") not in ("|", ">"):
            out.append(rest)
            continue
        # A block scalar: everything indented past the `run:` key is its body.
        while i < len(live):
            body = live[i]
            if body.strip() and _indent(body) <= key_indent:
                break
            if not body.lstrip().startswith("#"):
                out.append(body)
            i += 1
    return "\n".join(out)


# A gate step is a script committed to this repository. That is the unit the
# hook and the workflow name in the same words — `scripts/check_all.py` on both
# sides — so it is the unit the two can be compared over. A hook line that runs
# something else entirely (`npm run lint`, an inline `ruff check .`) is outside
# this net and the OK message says so rather than implying otherwise.
_GATE_SCRIPT = re.compile(r"[A-Za-z0-9_.${}/-]*\.(?:py|mjs|cjs|js|ts|sh)\b")
# `"$ROOT/scripts/check_all.py"` and `python3 scripts/check_all.py` are the same
# step written by two different callers. Strip whatever variable holds the repo
# root so they compare equal.
_ROOT_VAR = re.compile(r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/|\./)+")
# core.hooksPath first, because that is what git actually obeys; the other two
# are where a project puts hooks when it has not configured one. Failing to
# FIND the hook would silently restore the hole this comparison exists to close,
# so `test_gate_parity.py` asserts that this repository's hook is discovered.
_HOOK_DIRS = ("scripts/hooks", ".git/hooks")


def gate_scripts(text: str) -> set[str]:
    """Every script of this repository that `text` invokes, repo-relative.

    Comment lines go first, for the same reason `workflow_commands` drops them:
    a gate named in a comment is not a gate that runs. A gate named in a
    TRAILING comment is still counted, and that is deliberate — the error it
    produces is 'the hook appears to run something CI does not', a false alarm,
    and the other direction would be a false pass.
    """
    found: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for raw in _GATE_SCRIPT.findall(line):
            tok = _ROOT_VAR.sub("", raw.strip("\"'"))
            # Repo-relative and real. Without the existence test every `.js` in
            # an inline heredoc would look like a gate step.
            if "/" in tok and (ROOT / tok).is_file():
                found.add(tok)
    return found


def pre_commit_hook() -> Path | None:
    configured = sh(["git", "config", "core.hooksPath"], cwd=ROOT).stdout.strip()
    for rel in ([configured] if configured else []) + list(_HOOK_DIRS):
        hook = ROOT / rel / "pre-commit"
        if hook.is_file():
            return hook
    return None


def check_ci_parity() -> tuple[str, str]:
    """Guard the promise 'green locally ⇒ green in CI': the CI workflows must
    actually invoke the same gate script(s) this file is part of. Prevents CI
    silently drifting away from the local checks."""
    gates = []
    if (ROOT / "scripts" / "check_all.py").exists():
        gates.append("check_all.py")
    if (ROOT / "scripts" / "check-all.mjs").exists():
        gates.append("check-all.mjs")
    if not gates:
        return ("SKIP", "no local gate to compare")
    wf_dir = ROOT / ".github" / "workflows"
    files = (
        sorted(wf for pat in ("*.yml", "*.yaml") for wf in wf_dir.glob(pat))
        if wf_dir.is_dir()
        else []
    )
    # "There is no CI" and "CI runs the gate" are not the same answer. Deleting
    # the workflow directory used to produce the first and be counted as the
    # second.
    if not files:
        return (
            "FAIL",
            "a local gate exists but .github/workflows has no workflow to compare it to — "
            "parity cannot be verified, which is not the same as parity holding",
        )
    commands = "\n".join(workflow_commands(wf.read_text(errors="ignore")) for wf in files)
    absent = [g for g in gates if g not in commands]
    if absent:
        return (
            "FAIL",
            "no enabled CI job RUNS the local gate: " + ", ".join(absent) + "\n"
            "a mention in a comment, a step name or a disabled job is not an invocation",
        )

    # Everything above answers only "does CI run check_all.py and
    # check-all.mjs". It cannot see a check that exists on ONE side. A reviewer
    # added scripts/check-local-only.py, appended it to the pre-commit hook, and
    # this function still returned ('OK', '1 workflow file(s) run the same
    # gate(s) as local') — the local hook had become strictly stricter than CI
    # and the line that exists to notice that stayed green. Both directions are
    # a broken promise: a hook step CI lacks means green in CI does not mean the
    # commit would have passed locally, and a CI step the hook lacks means green
    # locally does not mean green in CI.
    hook = pre_commit_hook()
    if hook is None:
        # No hook, so nothing local can be stricter than CI: the comparison
        # above is then the whole of parity rather than a part of it.
        return ("OK", f"{len(files)} workflow file(s) run the same gate(s) as local")
    hook_scripts = gate_scripts(hook.read_text(errors="ignore"))
    ci_scripts = gate_scripts(commands)
    where = hook.name if hook.parent == ROOT else str(hook).replace(str(ROOT) + "/", "")
    drift = [
        f"  {where} runs {s}, no enabled CI job does" for s in sorted(hook_scripts - ci_scripts)
    ]
    drift += [f"  CI runs {s}, {where} does not" for s in sorted(ci_scripts - hook_scripts)]
    if drift:
        return (
            "FAIL",
            f"{where} and CI do not run the same gate scripts, so 'green locally' and "
            "'green in CI' are different promises:\n" + "\n".join(drift),
        )
    return (
        "OK",
        f"{len(files)} workflow file(s) and {where} run the same "
        f"{len(hook_scripts)} gate script(s)",
    )


# ---- security tier: catches the mechanical vulns (not a substitute for a
# human security review of auth / money / data-exposure logic) --------------


def check_secrets() -> tuple[str, str]:
    """Block commits that introduce credentials. Uses detect-secrets against a
    committed .secrets.baseline — audited existing findings are allowed, new
    ones fail. Language-agnostic; runs over all tracked files."""
    hook = None
    for p in py_projects():
        hook = _tool_for(p, "detect-secrets-hook")
        if hook:
            break
    hook = hook or shutil.which("detect-secrets-hook")
    if not hook:
        return (
            "FAIL",
            MISSING_TOOL.format(tool="detect-secrets", how="pip install detect-secrets"),
        )
    baseline = ROOT / ".secrets.baseline"
    if not baseline.exists():
        return (
            "FAIL",
            "no .secrets.baseline, so every finding would be waived — run: detect-secrets scan "
            "--exclude-files '\\.venv/' > .secrets.baseline",
        )
    files = [str(f) for f in tracked() if f.is_file()]
    r = sh([hook, "--baseline", str(baseline), *files])
    if r.returncode:
        return ("FAIL", "potential secret(s) introduced:\n" + (r.stdout + r.stderr)[-1500:])
    return ("OK", "no new secrets")


def check_security(
    projects: Sequence[Path], fix: bool = False, ratchet: bool = False
) -> tuple[str, str]:
    """bandit SAST as a ratchet: counts MEDIUM+HIGH findings (SQL/command
    injection, unsafe deserialization, weak crypto, XXE, etc.). Ceiling only
    falls. Silence a specific false positive with a `# nosec` comment."""
    budget = load("bandit.json", {"max_issues": 0})
    cap = budget.get("max_issues", 0)
    total, ran, missing, sample = 0, False, [], []
    for p in projects:
        bb = _tool_for(p, "bandit")
        if not bb:
            missing.append(p.name)
            continue
        ran = True
        r = sh([bb, "-r", ".", "-q", "-f", "json", "-x", "./.venv,./node_modules"], cwd=p)
        # `json.loads(r.stdout or "{}")` treated silence as a clean report: with
        # the binary replaced by /usr/bin/false there was no output, no
        # exception, an empty results list, and "0 MEDIUM+ security issues ≤
        # ceiling 0". A scan that produced nothing did not happen.
        try:
            report = json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            return (
                "FAIL",
                f"bandit produced no readable report for {p.name} (exit {r.returncode}):\n"
                f"{(r.stdout + r.stderr)[-800:]}",
            )
        if not isinstance(report, dict) or "results" not in report:
            return ("FAIL", f"bandit output for {p.name} has no results key:\n{r.stdout[:400]}")
        # bandit exits 1 when it found anything at all, including the LOW
        # findings this ceiling deliberately ignores, so 1 is not a failure
        # here. Anything else is the tool itself failing.
        if r.returncode not in (0, 1):
            return (
                "FAIL",
                f"bandit exited {r.returncode} for {p.name}:\n{(r.stdout + r.stderr)[-800:]}",
            )
        # Files bandit could not read are reported here rather than raised. They
        # are the same defect one level down: a file that was not scanned counts
        # as zero findings.
        if report.get("errors"):
            return ("FAIL", f"bandit could not scan every file in {p.name}:\n{report['errors']}")
        results = report["results"]
        hits = [x for x in results if x.get("issue_severity") in ("MEDIUM", "HIGH")]
        total += len(hits)
        sample += [
            f"{x['issue_severity']} {x['test_id']} "
            f"{x['filename']}:{x['line_number']} {x['issue_text'][:60]}"
            for x in hits[:5]
        ]
    if missing or not ran:
        return (
            "FAIL",
            MISSING_TOOL.format(tool="bandit", how="pip install bandit")
            + (f"\nnot found for: {', '.join(missing)}" if missing else ""),
        )
    if fix:
        budget["max_issues"] = total
        save("bandit.json", budget)
        return ("OK", f"security-issue ceiling set to {total}")
    if ratchet and total < cap:
        budget["max_issues"] = total
        save("bandit.json", budget)
        return ("OK", f"security-issue ceiling ratcheted {cap} → {total}")
    if total > cap:
        return (
            "FAIL",
            f"{total} MEDIUM+ security issues > ceiling {cap}\n" + "\n".join(sample[:10]),
        )
    nudge = f"  (ratchet ceiling down toward {total})" if cap - total > 0 else ""
    return ("OK", f"{total} MEDIUM+ security issues ≤ ceiling {cap}{nudge}")


def check_deps(projects: Sequence[Path]) -> tuple[str, str]:
    """pip-audit: fail on dependencies with known published CVEs. Needs the
    advisory DB (network); if unreachable it SKIPs rather than block offline
    commits — CI, which has network, is the real enforcement point."""
    ran, vulns, missing = False, [], []
    for p in projects:
        pa = _tool_for(p, "pip-audit")
        if not pa:
            missing.append(p.name)
            continue
        r = sh([pa, "-l", "--progress-spinner", "off"], cwd=p)
        err = r.stderr.lower()
        if r.returncode and any(
            k in err for k in ("connection", "network", "timed out", "temporary failure", "resolve")
        ):
            return ("SKIP", "pip-audit offline (advisory DB unreachable) — enforced in CI")
        ran = True
        # Any other nonzero status is a FAIL, whether the tool found a CVE or
        # fell over: an audit that did not complete has not cleared anything.
        if r.returncode:
            vulns.append(
                f"{p.name}: pip-audit exited {r.returncode}\n{(r.stdout + r.stderr)[-1200:]}"
            )
    if missing or not ran:
        return (
            "FAIL",
            MISSING_TOOL.format(tool="pip-audit", how="pip install pip-audit")
            + (f"\nnot found for: {', '.join(missing)}" if missing else ""),
        )
    if vulns:
        return ("FAIL", "vulnerable dependencies:\n" + "\n".join(vulns))
    return ("OK", "no known-vulnerable dependencies")


def main() -> int:
    fix = "--init-budgets" in sys.argv
    # --init-budgets IS THE ONE FLAG THAT CAN LOOSEN A RATCHET, and until a
    # cross-family gate review probed it, "initial baseline only" was a sentence
    # in the usage text with nothing behind it. The probe injected a single debt
    # marker, ran `--init-budgets`, and watched the debt ceiling go from 0 to 1 —
    # on a repository whose budgets were baselined months ago.
    #
    # Ratchets only tighten is the rule the whole gate rests on; a flag that
    # silently reverses it is a hole in every other check at once. So the flag
    # now refuses once budgets exist and names the tool that IS safe to run.
    # `--force-init-budgets` keeps the escape hatch, spelled out loud, for the
    # case the rule is genuinely meant to be broken.
    if fix and "--force-init-budgets" not in sys.argv:
        existing = sorted(p.name for p in BUD.glob("*.json"))
        if existing:
            print(
                f"\n✗ --init-budgets refused: {len(existing)} budget file(s) already exist "
                f"({', '.join(existing)}).\n"
                "  This flag BASELINES to the current state, so on an established repo it "
                "LOOSENS\n  whatever has since got worse — the one thing ratchets exist to "
                "prevent.\n"
                "  To tighten toward the current state, use --ratchet, which can only "
                "tighten.\n"
                "  If re-baselining is genuinely intended, say so: --force-init-budgets.\n"
            )
            return 1
    # --ratchet: tighten budgets toward current state, but ONLY tighter, never
    # looser (raise coverage floor, lower error/debt ceilings). Safe to run any
    # time; unlike --init-budgets it can never weaken a budget.
    ratchet = "--ratchet" in sys.argv
    projects = py_projects()
    # The third field is the only permission a check has to come out anything
    # other than OK. Everything else — SKIP, WARN, a tool that is not installed
    # — counts as a failure, because `✓ all checks passed` printed over a check
    # that did not run is the exact claim this gate exists to refuse.
    #
    # Two checks may legitimately not run, and both say so in their detail line:
    #   database guards — needs a live database; developers may have none, and
    #     CI sets REQUIRE_DB_TESTS=1 which removes this permission there.
    #   dependency CVEs — needs the advisory DB over the network, and an
    #     offline commit should not be blocked. Only the offline branch SKIPs;
    #     a missing pip-audit is a FAIL.
    checks: list[tuple[str, Callable[[], tuple[str, str]], bool]] = [
        ("lint", lambda: check_lint(projects), False),
        ("format", lambda: check_format(projects), False),
        ("types", lambda: check_types(projects, fix, ratchet), False),
        ("tests + coverage", lambda: check_tests(projects, fix, ratchet), False),
        ("test inventory", lambda: check_test_inventory(fix, ratchet), False),
        ("database guards", check_db_guards, True),
        ("duplicate code", check_dups, False),
        # NAMED "reported", because it is. The owner's decision is that file
        # length is measured and never enforced (see `check_file_sizes`), and
        # that decision stands — but the summary line printed `✓ file sizes OK`
        # and the detail line saying "(not enforced)" was never shown, because
        # details print only for statuses other than OK. A cross-family gate
        # review read the green tick as enforcement, which is what a reader
        # would do. The name is the one part of the line that always prints.
        ("file sizes (reported)", lambda: check_file_sizes(fix), False),
        ("debt markers", lambda: check_debt(fix, ratchet), False),
        ("architecture", lambda: arch_checks.check_architecture(ROOT, _SKIP_DIRS), False),
        ("invariant coverage", lambda: arch_checks.check_invariant_matrix(ROOT), False),
        (
            "ignore budget",
            lambda: arch_checks.check_ignore_budget(ROOT, tracked(), BUD, fix, ratchet),
            False,
        ),
        ("secrets", check_secrets, False),
        ("security (SAST)", lambda: check_security(projects, fix, ratchet), False),
        ("dependency CVEs", lambda: check_deps(projects), True),
        ("CLAUDE.md alignment", check_claude_md, False),
        ("CI parity", check_ci_parity, False),
    ]
    results: list[tuple[str, str, str, bool]] = []
    for name, fn, may_skip in checks:
        try:
            status, detail = fn()
        except Exception as e:  # a crashing check must not silently pass
            status, detail = "FAIL", f"check crashed: {e}"
        results.append((name, status, detail, may_skip))

    sym = {"OK": "✓", "WARN": "!", "SKIP": "·", "FAIL": "✗"}
    mode = " — baseline" if fix else (" — ratchet" if ratchet else "")
    print("\nagent-ready check-all" + mode)
    print("-" * 44)
    for name, status, detail, _ in results:
        print(f"  {sym.get(status, '?')} {name:22} {status}")
        if status != "OK" and detail:
            for line in detail.splitlines():
                print(f"        {line}")

    if fix:
        print("\nbudgets baselined to current state.\n")
        return 0
    failed = [n for n, s, _, may_skip in results if not (s == "OK" or (s == "SKIP" and may_skip))]
    if failed:
        print(f"\n✗ {len(failed)} check(s) failed: {', '.join(failed)}\n")
        return 1
    print("\n✓ all checks passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
