"""The gate's own guards, each proved by breaking the thing it watches.

Every defect these cover is one shape: a check that passes because it could not
run. A crashed tool reporting zero findings, a suite that skipped, a workflow
that names the gate in a comment, a project discovery that found nothing — all
of them printed a tick. So each test here does what a verification pass did by
hand: put the fault back and assert the gate goes red.

The gate scripts are not a package. `scripts/` goes on the path the same way
check_all.py itself puts it there.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# The module, never the test function by name: importing
# `test_the_product_does_not_import_its_own_answer_key` directly would bind a
# `test_`-prefixed name here and pytest would collect the same test twice, once
# against a tree this file controls and once against the real repository.
from tests import test_policy_vs_oracle as answer_key_suite

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Imported through `importlib` rather than as `import arch_checks`, because the
# path insert above has to run first and a module-level import after a statement
# is E402. The alternative was two inline lint suppressions, and the gate holds
# those at zero — a ceiling that means nothing if the first inconvenient case is
# allowed to raise it.
arch_checks = importlib.import_module("arch_checks")
check_all = importlib.import_module("check_all")

#: A binary that always fails and says nothing — the verification pass used it
#: to stand in for a crashed tool, and it is the sharpest form of the defect:
#: no output at all, so nothing the adapter recognises, so "zero findings".
FALSE = "/usr/bin/false"

#: Assembled rather than written out, because the suppression ratchet scans
#: every tracked .py file and would otherwise count this file's own fixtures.
FILE_LEVEL_MYPY = "# my" + "py: ignore-errors"
FILE_LEVEL_RUFF = "# ru" + "ff: noqa"
LINE_LEVEL_TYPE = "x = 1  # ty" + "pe: ignore"


@pytest.fixture
def crashed_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_all, "_tool_for", lambda _p, _name: FALSE)


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """check_all reads ROOT at call time, so pointing it at a tmp tree is enough."""
    monkeypatch.setattr(check_all, "ROOT", tmp_path)
    return tmp_path


# ── a crashed tool is not a clean report ─────────────────────────────────
def test_a_type_check_that_crashed_is_not_zero_type_errors(crashed_tool: None) -> None:
    status, detail = check_all.check_types([ROOT])
    assert status == "FAIL", detail
    assert "did not run" in detail


def test_a_security_scan_that_produced_nothing_is_not_zero_findings(crashed_tool: None) -> None:
    status, detail = check_all.check_security([ROOT])
    assert status == "FAIL", detail
    assert "no readable report" in detail


def test_a_dependency_audit_that_crashed_is_not_a_clean_bill(crashed_tool: None) -> None:
    status, _ = check_all.check_deps([ROOT])
    assert status == "FAIL"


@pytest.fixture
def tools_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A throwaway project has no .venv, so the gate falls back to PATH — which
    under pytest does not carry this repository's venv."""
    monkeypatch.setenv("PATH", f"{ROOT / '.venv' / 'bin'}{os.pathsep}{os.environ['PATH']}")


def test_a_working_tool_is_not_mistaken_for_a_crashed_one(
    tmp_path: Path, tools_on_path: None
) -> None:
    """The control. Without it every assertion above is satisfied by a check
    that fails all the time, which is the other way to stop measuring.

    A clean throwaway project rather than this repository, so the control says
    something about the adapter instead of about the day's type debt.
    """
    (tmp_path / "clean.py").write_text("def f(x: int) -> int:\n    return x + 1\n")
    assert check_all.check_types([tmp_path])[0] == "OK"
    assert check_all.check_security([tmp_path])[0] == "OK"


def test_type_errors_are_counted_rather_than_merely_survived(
    tmp_path: Path, tools_on_path: None
) -> None:
    (tmp_path / "wrong.py").write_text("def f(x: int) -> str:\n    return x\n")
    status, detail = check_all.check_types([tmp_path])
    assert status == "OK", detail  # one error is under this repository's ceiling
    assert detail.startswith("1 type error"), detail


# ── whole-file suppressions count ────────────────────────────────────────
@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("mypy file directive", FILE_LEVEL_MYPY),
        ("ruff file directive", FILE_LEVEL_RUFF),
        ("per-line ignore", LINE_LEVEL_TYPE),
    ],
)
def test_a_suppression_is_counted_however_it_is_spelled(
    tmp_path: Path, label: str, source: str
) -> None:
    """The two file-level forms turn mypy and Ruff off for a whole file. The
    ratchet knew only the per-line spellings, so a file containing an undefined
    name passed both checkers with the ceiling still reading zero."""
    (tmp_path / "budgets").mkdir()
    (tmp_path / "budgets" / "ignore-budget.json").write_text('{"max_ignores": 0}')
    target = tmp_path / "suppressed.py"
    target.write_text(source + "\nundefined_name + 1\n")
    status, detail = arch_checks.check_ignore_budget(tmp_path, [target], tmp_path / "budgets")
    assert status == "FAIL", f"{label} was not counted: {detail}"


def test_ordinary_code_is_not_counted_as_a_suppression(tmp_path: Path) -> None:
    (tmp_path / "budgets").mkdir()
    (tmp_path / "budgets" / "ignore-budget.json").write_text('{"max_ignores": 0}')
    target = tmp_path / "plain.py"
    target.write_text("# a comment about types and linting\nx = 1\n")
    assert arch_checks.check_ignore_budget(tmp_path, [target], tmp_path / "budgets")[0] == "OK"


# ── INV-8: no way to be outside the span rule ────────────────────────────
STATES_A_SPAN = "x = dict(span_start=0)\n"


def _producer_tree(root: Path, *, shape: str) -> None:
    """One repository per shape a file can hide in from the INV-8 scan."""
    if shape == "regular package":
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").touch()
        (root / "pkg" / "mod.py").write_text(STATES_A_SPAN)
    elif shape == "namespace package":  # PEP 420 — importable with no __init__.py
        (root / "pkg").mkdir()
        (root / "pkg" / "mod.py").write_text(STATES_A_SPAN)
    elif shape == "repository-root module":
        (root / "rootmod.py").write_text(STATES_A_SPAN)
    elif shape == "symlinked subdirectory":
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").touch()
        (root / "outside").mkdir()
        (root / "outside" / "mod.py").write_text(STATES_A_SPAN)
        (root / "pkg" / "nested").symlink_to(root / "outside")
    elif shape == "a file named citations.py":
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").touch()
        (root / "pkg" / "citations.py").write_text(STATES_A_SPAN)
    else:  # pragma: no cover — a shape nobody wrote
        raise AssertionError(shape)


@pytest.mark.parametrize(
    "shape",
    [
        "regular package",
        "namespace package",
        "repository-root module",
        "symlinked subdirectory",
        "a file named citations.py",
    ],
)
def test_a_stated_span_is_caught_wherever_the_file_sits(tmp_path: Path, shape: str) -> None:
    """Four of these five reported OK. The last is the sharpest: the exemption
    for the one file allowed to compute a span compared the basename, so any
    file called citations.py was outside INV-8 — a rule you leave by choosing a
    filename is not a rule."""
    _producer_tree(tmp_path, shape=shape)
    status, detail = arch_checks.check_architecture(tmp_path, check_all._SKIP_DIRS)
    assert status == "FAIL", f"{shape} escaped the span rule: {detail}"


def test_the_one_sanctioned_span_producer_is_exempt_by_path(tmp_path: Path) -> None:
    (tmp_path / "packages" / "contracts").mkdir(parents=True)
    (tmp_path / "packages" / "__init__.py").touch()
    (tmp_path / "packages" / "contracts" / "__init__.py").touch()
    (tmp_path / "packages" / "contracts" / "citations.py").write_text(STATES_A_SPAN)
    assert arch_checks.check_architecture(tmp_path, check_all._SKIP_DIRS)[0] == "OK"


def test_a_directory_excluded_from_the_scan_may_not_be_imported_by_the_product(
    tmp_path: Path,
) -> None:
    """`NOT_PRODUCERS` is a claim that those directories are not the product.
    Unchecked, it was also the cheapest way out of every rule: move the file.
    The claim is now the check."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").touch()
    (tmp_path / "pkg" / "mod.py").write_text("from evals import answer_key\n")
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "answer_key.py").write_text(STATES_A_SPAN)
    status, detail = arch_checks.check_architecture(tmp_path, check_all._SKIP_DIRS)
    assert status == "FAIL", detail
    assert "excluded from the producer scan" in detail


def test_the_real_repository_holds_the_span_rule() -> None:
    assert arch_checks.check_architecture(ROOT, check_all._SKIP_DIRS)[0] == "OK"


# ── G7: the answer-key scan reaches the directories it claims ────────────
#: The polite failure mode was an `import`, and for a while it was the only one
#: the guard knew. This is the impolite one: a file read, which is not an import
#: node at all, and which would satisfy every fixed-corpus comparison in the
#: suite by reading the answers off disk.
READS_THE_ANSWER_KEY = (
    'from pathlib import Path\nX = Path("evals/oracle/derived.json").read_text()\n'
)


@pytest.mark.parametrize("directory", ["policy", "api", "packet"])
def test_the_answer_key_scan_reaches_every_directory_it_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: str
) -> None:
    """The real guard, run against a tree this test builds.

    "It scans policy/, api/ and packet/" is three claims, and the scan selects
    directories with a glob character class — `[apolicyngest]*` — that no
    reader can verify by eye. Its previous version had a filter that excluded
    nothing at all for exactly that reason, and nobody noticed until the check
    grew teeth.

    So the guard is pointed at a synthetic repository rather than re-implemented
    here. A copy of the walk would agree with itself and drift from the original
    on the first edit, which is the shared-author error this project has already
    paid for once.
    """
    (tmp_path / directory).mkdir()
    (tmp_path / directory / "reader.py").write_text(READS_THE_ANSWER_KEY)
    monkeypatch.setattr(answer_key_suite, "ROOT", tmp_path)
    with pytest.raises(AssertionError, match="reaches its own answer key"):
        answer_key_suite.test_the_product_does_not_import_its_own_answer_key()


def test_the_answer_key_scan_still_lets_the_product_explain_the_oracle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control, and it is the half that makes the guard usable.

    Without it every assertion above is satisfied by a check that fails on every
    tree. And the exemption it pins is load-bearing: the product names
    `derived.json` in prose constantly, because that is how a reader learns why
    a rule is what it is. A guard that flagged those would be reworded into
    uselessness within a day.
    """
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "clean.py").write_text(
        '"""Checked against evals/oracle/derived.json by the suite, never from here."""\n'
        "# evals/oracle/derived.json is the answer key.\n"
        "X = 1\n"
    )
    monkeypatch.setattr(answer_key_suite, "ROOT", tmp_path)
    answer_key_suite.test_the_product_does_not_import_its_own_answer_key()


# ── a suite that skipped is not a suite that passed ──────────────────────
@pytest.fixture
def require_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_DB_TESTS", "1")


def test_a_suite_that_skipped_for_want_of_a_database_fails(
    require_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        check_all,
        "_TEST_REPORTS",
        {
            "proj": (
                "SKIPPED [3] tests/test_packet_export.py:483: no DATABASE_URL\n"
                "15 passed, 3 skipped in 0.60s\n"
            )
        },
    )
    status, detail = check_all.check_db_guards()
    assert status == "FAIL", detail
    assert "not sanctioned" in detail


def test_the_absent_case_study_material_is_the_one_sanctioned_skip(
    require_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Private fund data is gitignored and will never be in CI, so failing on it
    would make the gate permanently red for a state that is correct."""
    monkeypatch.setattr(
        check_all,
        "_TEST_REPORTS",
        {
            "proj": (
                "SKIPPED [2] tests/test_real_data_ledger.py:31: "
                "case-study workbooks are not in the repository\n"
                "40 passed, 2 skipped in 3.10s\n"
            )
        },
    )
    assert check_all.check_db_guards()[0] == "OK"


def test_a_new_way_of_saying_there_is_no_database_is_not_grandfathered(
    require_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The set of database-backed suites is derived from what skipped and why,
    so a suite nobody registered — and a reason nobody anticipated — still
    fails. The list this replaced was found short three times."""
    monkeypatch.setattr(
        check_all,
        "_TEST_REPORTS",
        {
            "proj": (
                "SKIPPED [1] tests/test_new.py:9: postgres is not up\n1 passed, 1 skipped in 0.1s\n"
            )
        },
    )
    assert check_all.check_db_guards()[0] == "FAIL"


def test_no_test_run_to_read_is_a_failure_not_a_pass(
    require_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_all, "_TEST_REPORTS", {})
    status, detail = check_all.check_db_guards()
    assert status == "FAIL"
    assert "no pytest output" in detail


def test_an_unreadable_tally_is_a_failure(
    require_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_all, "_TEST_REPORTS", {"proj": "something went wrong\n"})
    assert check_all.check_db_guards()[0] == "FAIL"


def test_the_database_guard_may_only_skip_where_it_is_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUIRE_DB_TESTS", raising=False)
    assert check_all.check_db_guards()[0] == "SKIP"


def test_the_skip_report_reaches_the_guard_from_the_run_that_produced_it(
    tmp_path: Path, require_db: None
) -> None:
    """End to end, because the plumbing is the part that can rot quietly: the
    guard reads the run `check_tests` already did rather than doing its own, so
    a `-rs` dropped from that command line would leave the guard reading an
    empty report. It fails on an empty report, and this proves it is not."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\nversion = '0'\n")
    (tmp_path / "test_mixed.py").write_text(
        "import pytest\n\n\n"
        "def test_runs():\n    assert True\n\n\n"
        "@pytest.mark.skip(reason='MIGRATION_DATABASE_URL not set')\n"
        "def test_needs_a_database():\n    pass\n"
    )
    assert check_all.check_tests([tmp_path])[0] == "OK"
    status, detail = check_all.check_db_guards()
    assert status == "FAIL", detail
    assert "MIGRATION_DATABASE_URL not set" in detail


def test_a_project_in_which_every_test_skipped_did_not_pass(tmp_path: Path) -> None:
    """A temporary project whose whole suite skipped returned
    `('OK', 'tests pass · coverage 100.00%')`. Nothing ran."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\nversion = '0'\n")
    (tmp_path / "test_all_skipped.py").write_text(
        "import pytest\n\n\n@pytest.mark.skip(reason='no database')\ndef test_one():\n    pass\n"
    )
    status, detail = check_all.check_tests([tmp_path])
    assert status == "FAIL", detail
    assert "none passed" in detail


def test_a_project_with_a_passing_test_passes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\nversion = '0'\n")
    (tmp_path / "test_one.py").write_text("def test_one():\n    assert True\n")
    assert check_all.check_tests([tmp_path])[0] == "OK"


def test_the_test_inventory_falls_when_a_suite_is_deleted(fake_root: Path) -> None:
    """The skip check cannot see a suite that no longer exists: a deleted file
    collects nothing, skips nothing and reads as clean. The count catches it
    without naming any file, which the list it replaced could not do."""
    (fake_root / "pyproject.toml").write_text("[project]\nname = 'x'\nversion = '0'\n")
    (fake_root / "test_a.py").write_text("def test_a():\n    assert True\n")
    (fake_root / "test_b.py").write_text("def test_b():\n    assert True\n")
    budgets = fake_root / "budgets"
    budgets.mkdir()
    (budgets / "tests.json").write_text('{"min_tests": 2}\n')
    original = check_all.BUD
    try:
        check_all.BUD = budgets
        assert check_all.check_test_inventory()[0] == "OK"
        (fake_root / "test_b.py").unlink()
        status, detail = check_all.check_test_inventory()
        assert status == "FAIL", detail
        assert "went missing" in detail
    finally:
        check_all.BUD = original


# ── CI parity is an invocation, not a mention ────────────────────────────
REAL_WORKFLOW = """name: check-all
on: [push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/check_all.py
      - run: node scripts/check-all.mjs
"""

COMMENT_ONLY = "# Historical names only: check_all.py and check-all.mjs\n"

DISABLED_JOB = """name: check-all
on: [push]
jobs:
  gate:
    if: false
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/check_all.py
      - run: node scripts/check-all.mjs
"""

NAMED_NOT_RUN = """name: check-all
on: [push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - name: run check_all.py and check-all.mjs
        run: echo nothing
"""

BLOCK_SCALAR = """name: check-all
on: [push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: |
          set -euo pipefail
          python3 scripts/check_all.py
          node scripts/check-all.mjs
"""


def _gate_repo(root: Path, workflow: str) -> None:
    (root / "scripts").mkdir()
    (root / "scripts" / "check_all.py").touch()
    (root / "scripts" / "check-all.mjs").touch()
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(workflow)


@pytest.mark.parametrize(
    ("label", "workflow", "expected"),
    [
        ("a real invocation", REAL_WORKFLOW, "OK"),
        ("a run: block scalar", BLOCK_SCALAR, "OK"),
        ("only a comment", COMMENT_ONLY, "FAIL"),
        ("a job disabled with if: false", DISABLED_JOB, "FAIL"),
        ("a step named after the gate", NAMED_NOT_RUN, "FAIL"),
    ],
)
def test_ci_parity_reads_what_runs_not_what_is_written(
    fake_root: Path, label: str, workflow: str, expected: str
) -> None:
    _gate_repo(fake_root, workflow)
    status, detail = check_all.check_ci_parity()
    assert status == expected, f"{label}: {status} {detail}"


def test_ci_parity_fails_when_there_is_no_workflow_at_all(fake_root: Path) -> None:
    """'There is no CI' and 'CI runs the gate' were the same answer."""
    (fake_root / "scripts").mkdir()
    (fake_root / "scripts" / "check_all.py").touch()
    status, detail = check_all.check_ci_parity()
    assert status == "FAIL", detail
    assert "cannot be verified" in detail


def test_the_real_workflow_runs_both_gates() -> None:
    assert check_all.ROOT == ROOT
    assert check_all.check_ci_parity()[0] == "OK"


def test_ci_gives_the_database_every_name_the_suites_resolve() -> None:
    """CI ran a Postgres service that a whole class of suites could not find.
    `dsn()` defaults to DATABASE_URL and only the schema suites ask for
    MIGRATION_DATABASE_URL; the workflow set the second alone, so eight packet
    tests skipped with `no DATABASE_URL` while the database was up, and the
    guard that reads skips reported the target permanently failing.

    Asserted here rather than trusted, because the failure is invisible from
    inside CI: everything looks configured."""
    text = (ROOT / ".github" / "workflows" / "check-all.yml").read_text()
    env: dict[str, str] = {}
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        m = re.match(r"^\s{6}([A-Z_]+):\s*(.+?)\s*(?:#.*)?$", raw)
        if m:
            env[m.group(1)] = m.group(2).strip('"')
    assert env.get("REQUIRE_DB_TESTS") == "1"
    assert env.get("LEDGER_SCHEMA") == "public"
    assert env.get("DATABASE_URL"), "the application's own DSN variable is unset in CI"
    assert env["DATABASE_URL"] == env.get("MIGRATION_DATABASE_URL"), (
        "the two DSN names must point at the same database, or half the suites "
        "run against one and half skip for want of the other"
    )


# ── the aggregation ──────────────────────────────────────────────────────
def _aggregate(status: str, may_skip: bool) -> subprocess.CompletedProcess[str]:
    """Run main() with every check stubbed but one, so only the aggregation is
    under test. A subprocess, because main() is what CI and the hook call.

    `may_skip` picks which check carries the status: the database guard is the
    one allowed to say it could not run, `secrets` is not.
    """
    under_test = "check_db_guards" if may_skip else "check_secrets"
    probe = f"""
import sys
sys.path.insert(0, {str(ROOT / "scripts")!r})
import arch_checks, check_all

for name in [n for n in dir(check_all) if n.startswith("check_")]:
    setattr(check_all, name, lambda *a, **k: ("OK", "stub"))
for name in ("check_architecture", "check_invariant_matrix", "check_ignore_budget"):
    setattr(arch_checks, name, lambda *a, **k: ("OK", "stub"))
setattr(check_all, {under_test!r}, lambda *a, **k: ({status!r}, "stub"))
sys.exit(check_all.main())
"""
    return subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT, check=False
    )


@pytest.mark.parametrize(
    ("status", "may_skip", "expected_exit"),
    [
        ("OK", False, 0),
        ("SKIP", True, 0),  # the database guard, locally — the one sanctioned skip
        ("SKIP", False, 1),
        ("WARN", False, 1),
        ("FAIL", False, 1),
    ],
)
def test_only_a_sanctioned_skip_survives_the_aggregation(
    status: str, may_skip: bool, expected_exit: int
) -> None:
    """`✓ all checks passed` printed over a SKIP or a WARN is the claim this
    whole gate exists to refuse, and it printed it for eight of its checks."""
    r = _aggregate(status, may_skip)
    assert r.returncode == expected_exit, r.stdout + r.stderr
    if expected_exit:
        assert "all checks passed" not in r.stdout


# ── the hook runs the project's interpreter or nothing ───────────────────
HOOK = ROOT / "scripts" / "hooks" / "pre-commit"


def test_the_hook_refuses_to_run_on_a_system_interpreter(tmp_path: Path) -> None:
    """It preferred .venv and fell back to a bare `python3`. In a repo without
    one that was Homebrew's 3.14, which holds none of this project's
    dependencies — an interpreter on which a check can pass by failing to
    import what it inspects."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_all.py").write_text("import sys; print(sys.executable)\n")
    r = subprocess.run(["sh", str(HOOK)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "never a system interpreter" in r.stderr


def test_the_hook_refuses_when_a_gate_script_is_missing(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check_all.py").write_text("pass\n")
    r = subprocess.run(["sh", str(HOOK)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "gate is not installed" in r.stderr


# ── the Node gate ────────────────────────────────────────────────────────
NODE_GATE = ROOT / "scripts" / "check-all.mjs"


def _node(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(not os.environ.get("PATH"), reason="no PATH")
def test_the_node_gate_fails_when_it_discovers_no_project(tmp_path: Path) -> None:
    """Discovery finding nothing ended the run at exit 0 with a friendly
    sentence, so deleting web/package.json deleted the whole Node gate."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    for name in ("check-all.mjs", "check-web-arch.mjs"):
        (tmp_path / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    r = subprocess.run(
        ["node", "scripts/check-all.mjs"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no package.json found" in r.stdout


def test_the_node_gate_reads_ci_parity_the_same_way_the_python_one_does(tmp_path: Path) -> None:
    """Two implementations of one rule drift apart unless something compares
    them. Same fixtures, same verdicts, or this fails."""
    cases = {
        "real": (REAL_WORKFLOW, "OK"),
        "block": (BLOCK_SCALAR, "OK"),
        "comment": (COMMENT_ONLY, "FAIL"),
        "disabled": (DISABLED_JOB, "FAIL"),
        "named": (NAMED_NOT_RUN, "FAIL"),
    }
    for label, (workflow, expected) in cases.items():
        repo = tmp_path / label
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        _gate_repo(repo, workflow)
        (repo / "scripts" / "check-all.mjs").write_bytes(NODE_GATE.read_bytes())
        (repo / "scripts" / "check-web-arch.mjs").write_bytes(
            (ROOT / "scripts" / "check-web-arch.mjs").read_bytes()
        )
        r = _node(
            "const m = await import('./scripts/check-all.mjs');"
            "console.log(JSON.stringify(m.checkCiParity()));",
            repo,
        )
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)[0] == expected, f"{label}: {r.stdout}"


def test_the_node_dependency_audit_fails_when_the_audit_did_not_run(tmp_path: Path) -> None:
    """A fake npm exiting 2 with a valid error document reported
    `no high/critical dependency CVEs`: npm uses the same exit status for
    'found some' and 'went wrong', so only the counts can tell them apart."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "scripts").mkdir()
    for name in ("check-all.mjs", "check-web-arch.mjs"):
        (tmp_path / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text('{"name":"p","version":"1.0.0"}')
    (proj / "package-lock.json").write_text('{"name":"p","lockfileVersion":3}')
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    npm = fake_bin / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        'echo \'{"error":{"code":"EAUDITNOPJSON","summary":"endpoint error"}}\'\n'
        "exit 2\n"
    )
    npm.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "const m = await import('./scripts/check-all.mjs');"
            f"console.log(JSON.stringify(m.checkDeps([{str(proj)!r}])));",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)[0] == "FAIL", r.stdout
