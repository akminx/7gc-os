#!/usr/bin/env python3
"""Agent-ready verification harness — one deterministic gate the agent cannot bypass.

Detects Python sub-projects (dirs containing pyproject.toml) and enforces:
lint, format, types (mypy), tests + coverage floor, database guards actually
running rather than skipping (REQUIRE_DB_TESTS=1), duplicate code, file-size
limits, debt markers, architecture invariants (INVARIANTS.md, via arch_checks),
suppression budget, secrets (detect-secrets), security SAST (bandit), dependency
CVEs (pip-audit), CLAUDE.md path alignment, and CI parity. Budgets live in
scripts/budgets/ and ratchet forward — they only get stricter.

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
from pathlib import Path

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


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def tracked():
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


def py_projects():
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


def load(name, default):
    f = BUD / name
    return json.loads(f.read_text()) if f.exists() else dict(default)


def save(name, data):
    (BUD / name).write_text(json.dumps(data, indent=2) + "\n")


def venv_bin(p):
    """Per-project .venv/bin, if the project has one — else None."""
    for name in ("bin", "Scripts"):
        vb = p / ".venv" / name
        if vb.is_dir():
            return vb
    return None


def project_python(p):
    vb = venv_bin(p)
    if vb:
        for exe in ("python", "python.exe"):
            if (vb / exe).exists():
                return str(vb / exe)
    return sys.executable


def _tool_for(p, name):
    vb = venv_bin(p)
    search_path = f"{vb}{os.pathsep}{os.environ.get('PATH', '')}" if vb else None
    return shutil.which(name, path=search_path)


def ruff_for(p):
    return _tool_for(p, "ruff")


def check_lint(projects):
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
    if missing and len(missing) == len(projects):
        return ("SKIP", "ruff not installed (pip install ruff, or add it to a project .venv)")
    if missing:
        return ("WARN", f"ruff not found for: {', '.join(missing)}")
    return ("OK", f"{len(projects)} project(s) clean")


def check_format(projects):
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
    if missing and len(missing) == len(projects):
        return ("SKIP", "ruff not installed")
    if missing:
        return ("WARN", f"ruff not found for: {', '.join(missing)}")
    return ("OK", "formatted")


def check_types(projects, fix=False, ratchet=False):
    """mypy as a ratchet: the type-error count is a ceiling that only falls.
    Existing untyped code is baselined so it doesn't block, but no new type
    error can slip in. Tighten per-project strictness in [tool.mypy]."""
    budget = load("mypy.json", {"max_errors": 0})
    cap = budget.get("max_errors", 0)
    total, ran, missing, sample = 0, False, [], []
    for p in projects:
        mb = _tool_for(p, "mypy")
        if not mb:
            missing.append(p.name)
            continue
        ran = True
        r = sh(
            [
                mb,
                ".",
                "--ignore-missing-imports",
                "--no-error-summary",
                "--exclude",
                r"(\.venv|node_modules|build|dist)/",
            ],
            cwd=p,
        )
        errs = [ln for ln in (r.stdout + r.stderr).splitlines() if ": error:" in ln]
        total += len(errs)
        sample += errs[:5]
    if not ran:
        return ("SKIP", "mypy not installed (pip install mypy, or add it to a project .venv)")
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


def check_tests(projects, fix=False, ratchet=False):
    budget = load("coverage.json", {"floor": 0.0})
    floor = budget.get("floor", 0.0)
    fails, total, ran, missing = [], None, False, []
    for p in projects:
        py = project_python(p)
        if sh([py, "-c", "import pytest"]).returncode:
            missing.append(p.name)
            continue
        ran = True
        has_cov = sh([py, "-c", "import pytest_cov"]).returncode == 0
        cmd = [py, "-m", "pytest", "-q"]
        jp = p / ".coverage.json"
        if has_cov:
            cmd += [f"--cov={p}", f"--cov-report=json:{jp}", "--cov-report="]
        r = sh(cmd, cwd=p)
        if r.returncode:
            fails.append(f"{p.name}:\n{(r.stdout + r.stderr)[-1500:]}")
        if has_cov and jp.exists():
            pc = json.loads(jp.read_text()).get("totals", {}).get("percent_covered", 0)
            jp.unlink()
            total = pc if total is None else min(total, pc)
    if not ran:
        return ("SKIP", "pytest not installed (pip install pytest, or add it to a project .venv)")
    if fails:
        detail = "tests failed\n" + "\n".join(fails)
        if missing:
            detail += f"\n(no pytest found for: {', '.join(missing)})"
        return ("FAIL", detail)
    if total is None:
        return ("OK", "tests pass (coverage off: pip install pytest-cov)")
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


# Every test in these targets is skipif'd on MIGRATION_DATABASE_URL. Without a
# DSN they do not fail — they vanish, and "tests + coverage" above still prints
# OK. That is the whole defect: a skipped guard reads exactly like a passing
# one, so the claim "invariants enforced as database constraints" was unexercised
# in CI while both gates reported green.
DB_GUARD_TARGETS = (
    "tests/test_schema_invariants.py",
    "tests/test_schema_approval.py",
    # Added late, and its absence here was finding #9 recurring on a new file:
    # the whole packet-sealing suite could skip in CI and the gate would report
    # green. A new schema suite that is not listed here is not guarded.
    "tests/test_schema_packet.py",
    "tests/test_schema_held_at_date.py",
    # Split out of test_schema_approval.py at the file-size budget. A split is
    # exactly when this list goes stale: the tests still run locally, and the
    # half that moved stops being guarded in CI without anything going red.
    "tests/test_schema_cross_class.py",
    # The real corpus against the live schema. Skips without a DSN *or* without
    # the workbooks — two ways to vanish, and CI has both.
    "tests/test_real_data_ledger.py",
    "tests/test_contracts.py::test_python_enums_match_the_postgres_types_in_both_directions",
)
# pytest's own tally line — "40 passed, 1 skipped in 0.31s". Read rather than
# trusted: a line this cannot parse is a FAIL, because an unreadable summary must
# never resolve to "nothing was skipped".
DB_GUARD_TALLY = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)\b")


def check_db_guards() -> tuple[str, str]:
    """Fail when a database guard skips. Gated on REQUIRE_DB_TESTS=1, which CI
    sets alongside a Postgres service; locally, without a database, this reports
    SKIP with its reason rather than blocking a commit.

    Runs on this interpreter — the one already executing the gate, which the hook
    and CI both point at the environment holding pytest. A bare interpreter
    without pytest yields no tally, and no tally is a FAIL, so the wrong
    interpreter cannot come out green.
    """
    if os.environ.get("REQUIRE_DB_TESTS") != "1":
        return ("SKIP", "REQUIRE_DB_TESTS is not 1 — guards optional here; CI sets it")
    absent = [t for t in DB_GUARD_TARGETS if not (ROOT / t.split("::")[0]).exists()]
    if absent:
        return ("FAIL", "database guard suite(s) missing: " + ", ".join(absent))
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", *DB_GUARD_TARGETS],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    out = (r.stdout + r.stderr)[-1500:]
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    tally = {kind: int(n) for n, kind in DB_GUARD_TALLY.findall(lines[-1] if lines else "")}
    if not tally:
        return ("FAIL", "pytest printed no tally — refusing to assume nothing skipped\n" + out)
    ran, skipped = sum(tally.values()), tally.get("skipped", 0)
    problems = []
    if skipped:
        reasons = [ln for ln in lines if ln.startswith("SKIPPED")]
        problems.append(
            f"{skipped} of {ran} database guard test(s) SKIPPED — a skipped guard is not a "
            "passing guard. Point MIGRATION_DATABASE_URL at a database with "
            "supabase/migrations applied.\n" + "\n".join(reasons[:10])
        )
    if r.returncode:
        problems.append("pytest exited non-zero\n" + out)
    if problems:
        return ("FAIL", "\n".join(problems))
    return ("OK", f"{ran} database guard test(s) ran, none skipped")


def check_dups():
    if not (ROOT / ".jscpd.json").exists():
        return ("SKIP", "no .jscpd.json")
    if not shutil.which("npx"):
        return ("SKIP", "npx/node not available for jscpd")
    r = sh(["npx", "--yes", "jscpd", "--config", str(ROOT / ".jscpd.json")], cwd=ROOT)
    return (
        ("OK", "no clones above threshold")
        if r.returncode == 0
        else (
            "FAIL",
            (r.stdout + r.stderr)[-1800:],
        )
    )


def check_file_sizes(fix=False):
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
    if over:
        lines = [f"{rel} = {n} lines (max {mx})" for rel, n in over]
        return ("FAIL", "split these files:\n" + "\n".join(lines))
    return ("OK", f"all source files ≤ {mx} lines")


def check_debt(fix=False, ratchet=False):
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


def check_claude_md():
    missing = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        cf = ROOT / name
        if not cf.exists():
            continue
        for tok in re.findall(r"`([^`]+)`", cf.read_text()):
            tok = tok.strip()
            if "/" not in tok or " " in tok or any(c in tok for c in "*<>"):
                continue
            if tok.startswith(("http", "npm ", "git ", "localhost")):
                continue
            if not (ROOT / tok.rstrip("/")).exists():
                missing.append(f"{name}: `{tok}`")
    if missing:
        return ("WARN", "paths referenced but not found:\n" + "\n".join(missing))
    return ("OK", "referenced paths exist")


def check_ci_parity():
    """Guard the promise 'green locally ⇒ green in CI': if a CI workflow
    exists, it must actually invoke the same gate script(s) this file is part
    of. Prevents CI silently drifting away from the local checks."""
    wf_dir = ROOT / ".github" / "workflows"
    if not wf_dir.is_dir():
        return ("SKIP", "no .github/workflows")
    gates = []
    if (ROOT / "scripts" / "check_all.py").exists():
        gates.append("check_all.py")
    if (ROOT / "scripts" / "check-all.mjs").exists():
        gates.append("check-all.mjs")
    if not gates:
        return ("SKIP", "no local gate to compare")
    text = "".join(
        wf.read_text(errors="ignore") for pat in ("*.yml", "*.yaml") for wf in wf_dir.glob(pat)
    )
    if not text:
        return ("SKIP", "no workflow files")
    absent = [g for g in gates if g not in text]
    if absent:
        return (
            "FAIL",
            "CI workflows don't run the local gate: " + ", ".join(absent) + "\n"
            "add a step invoking it so local green == CI green",
        )
    return ("OK", "CI runs the same gate(s) as local")


# ---- security tier: catches the mechanical vulns (not a substitute for a
# human security review of auth / money / data-exposure logic) --------------


def check_secrets():
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
        return ("SKIP", "detect-secrets not installed (pip install detect-secrets)")
    baseline = ROOT / ".secrets.baseline"
    if not baseline.exists():
        return (
            "WARN",
            "no .secrets.baseline — run: detect-secrets scan "
            "--exclude-files '\\.venv/' > .secrets.baseline",
        )
    files = [str(f) for f in tracked() if f.is_file()]
    r = sh([hook, "--baseline", str(baseline), *files])
    if r.returncode:
        return ("FAIL", "potential secret(s) introduced:\n" + (r.stdout + r.stderr)[-1500:])
    return ("OK", "no new secrets")


def check_security(projects, fix=False, ratchet=False):
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
        try:
            results = json.loads(r.stdout or "{}").get("results", [])
        except json.JSONDecodeError:
            return (
                "FAIL",
                f"bandit output unparseable for {p.name}:\n{(r.stdout + r.stderr)[-800:]}",
            )
        hits = [x for x in results if x.get("issue_severity") in ("MEDIUM", "HIGH")]
        total += len(hits)
        sample += [
            f"{x['issue_severity']} {x['test_id']} "
            f"{x['filename']}:{x['line_number']} {x['issue_text'][:60]}"
            for x in hits[:5]
        ]
    if not ran:
        return ("SKIP", "bandit not installed (pip install bandit)")
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


def check_deps(projects):
    """pip-audit: fail on dependencies with known published CVEs. Needs the
    advisory DB (network); if unreachable it SKIPs rather than block offline
    commits — CI, which has network, is the real enforcement point."""
    ran, vulns = False, []
    for p in projects:
        pa = _tool_for(p, "pip-audit")
        if not pa:
            continue
        r = sh([pa, "-l", "--progress-spinner", "off"], cwd=p)
        err = r.stderr.lower()
        if r.returncode and any(
            k in err for k in ("connection", "network", "timed out", "temporary failure", "resolve")
        ):
            return ("SKIP", "pip-audit offline (advisory DB unreachable) — enforced in CI")
        ran = True
        if r.returncode:
            vulns.append(f"{p.name}:\n{(r.stdout + r.stderr)[-1200:]}")
    if not ran:
        return ("SKIP", "pip-audit not installed (pip install pip-audit)")
    if vulns:
        return ("FAIL", "vulnerable dependencies:\n" + "\n".join(vulns))
    return ("OK", "no known-vulnerable dependencies")


def main():
    fix = "--init-budgets" in sys.argv
    # --ratchet: tighten budgets toward current state, but ONLY tighter, never
    # looser (raise coverage floor, lower error/debt ceilings). Safe to run any
    # time; unlike --init-budgets it can never weaken a budget.
    ratchet = "--ratchet" in sys.argv
    projects = py_projects()
    checks = [
        ("lint", lambda: check_lint(projects)),
        ("format", lambda: check_format(projects)),
        ("types", lambda: check_types(projects, fix, ratchet)),
        ("tests + coverage", lambda: check_tests(projects, fix, ratchet)),
        ("database guards", check_db_guards),
        ("duplicate code", check_dups),
        ("file sizes", lambda: check_file_sizes(fix)),
        ("debt markers", lambda: check_debt(fix, ratchet)),
        ("architecture", lambda: arch_checks.check_architecture(ROOT, _SKIP_DIRS)),
        ("invariant coverage", lambda: arch_checks.check_invariant_matrix(ROOT)),
        (
            "ignore budget",
            lambda: arch_checks.check_ignore_budget(ROOT, tracked(), BUD, fix, ratchet),
        ),
        ("secrets", check_secrets),
        ("security (SAST)", lambda: check_security(projects, fix, ratchet)),
        ("dependency CVEs", lambda: check_deps(projects)),
        ("CLAUDE.md alignment", check_claude_md),
        ("CI parity", check_ci_parity),
    ]
    results = []
    for name, fn in checks:
        try:
            status, detail = fn()
        except Exception as e:  # a crashing check must not silently pass
            status, detail = "FAIL", f"check crashed: {e}"
        results.append((name, status, detail))

    sym = {"OK": "✓", "WARN": "!", "SKIP": "·", "FAIL": "✗"}
    mode = " — baseline" if fix else (" — ratchet" if ratchet else "")
    print("\nagent-ready check-all" + mode)
    print("-" * 44)
    for name, status, detail in results:
        print(f"  {sym.get(status, '?')} {name:22} {status}")
        if status in ("FAIL", "WARN") and detail:
            for line in detail.splitlines():
                print(f"        {line}")

    if fix:
        print("\nbudgets baselined to current state.\n")
        return 0
    failed = [n for n, s, _ in results if s == "FAIL"]
    if failed:
        print(f"\n✗ {len(failed)} check(s) failed: {', '.join(failed)}\n")
        return 1
    print("\n✓ all checks passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
