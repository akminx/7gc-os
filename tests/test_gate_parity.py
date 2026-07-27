"""Two gate checks that returned OK over a defect a reviewer had planted.

Both are the shape `tests/test_gate_guards.py` exists for — a green line
counted as evidence for something the check never measured — and both were
reproduced by hand before they were fixed:

  CI parity      a `scripts/check-local-only.py` appended to the pre-commit
                 hook left the local gate strictly stricter than CI, and parity
                 returned ('OK', '1 workflow file(s) run the same gate(s) as
                 local'). It only ever asked whether CI invoked check_all.py
                 and check-all.mjs, which is a question about CI alone.

  CLAUDE.md      appending `xyz/nonexistent` to the end of CLAUDE.md was not
  alignment      detected, while breaking a token above the Commands block was.
                 A fenced block inverts backtick pairing for everything after
                 it, so nine of the eleven sections were never read.

Each case builds a synthetic tree with the defect planted, and each has a
control proving the legitimate spelling of the same thing survives — a check
that fails on everything has stopped measuring just as thoroughly as one that
passes on everything.

Both gates carry both rules, so every fixture is run through the Python
implementation and the Node one and their verdicts are required to agree.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

check_all = importlib.import_module("check_all")

# Every module the Node gate imports at load time. check-all.mjs crossed the
# 600-line ceiling its own file-size check enforces once both rules below grew
# past one-liners, so the two now live in check-gate-parity.mjs; a synthetic
# tree missing any of these fails at `import` rather than at an assertion.
NODE_MODULES = ("check-all.mjs", "check-gate-parity.mjs", "check-web-arch.mjs")


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """check_all reads ROOT at call time, so pointing it at a tmp tree is enough."""
    monkeypatch.setattr(check_all, "ROOT", tmp_path)
    return tmp_path


def _node_verdict(repo: Path, fn: str) -> tuple[str, str]:
    """The Node gate's answer for the same tree. It resolves ROOT with
    `git rev-parse`, so the tree has to be a repository for it to look at."""
    for name in NODE_MODULES:
        (repo / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    r = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            f"const m = await import('./scripts/check-all.mjs');"
            f"console.log(JSON.stringify(m.{fn}()));",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    status, detail = json.loads(r.stdout)
    return status, detail


# ── parity is a comparison, not a question about CI alone ────────────────

WORKFLOW = """name: check-all
on: [push]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/check_all.py
      - run: node scripts/check-all.mjs
"""

WORKFLOW_WITH_EXTRA_STEP = WORKFLOW + "      - run: python3 scripts/check-ci-only.py\n"

# Written the way the real hook writes it — through a variable holding the repo
# root, and quoted — because that is the spelling parity has to recognise as the
# same step CI spells `python3 scripts/check_all.py`.
HOOK = """#!/bin/sh
set -e
ROOT="$(git rev-parse --show-toplevel)"
python3 "$ROOT/scripts/check_all.py"
node "$ROOT/scripts/check-all.mjs"
"""

HOOK_WITH_LOCAL_ONLY = HOOK + 'python3 "$ROOT/scripts/check-local-only.py"\n'

# The false-alarm control for the same fixture: a step that is only ever named
# in a comment is not a step the hook runs, and parity must not invent drift
# from it. Without this the FAIL above is satisfied by counting any mention.
HOOK_WITH_COMMENTED_STEP = HOOK + '# python3 "$ROOT/scripts/check-local-only.py"\n'


def _parity_repo(root: Path, hook: str | None, workflow: str, scripts: Sequence[str]) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    for name in scripts:
        (root / "scripts" / name).touch()
    if hook is not None:
        (root / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "hooks" / "pre-commit").write_text(hook)
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text(workflow)


BOTH_GATES = ("check_all.py", "check-all.mjs")

PARITY_CASES: list[tuple[str, str | None, str, tuple[str, ...], str]] = [
    ("hook and CI run the same steps", HOOK, WORKFLOW, BOTH_GATES, "OK"),
    (
        "the hook runs a step CI does not",
        HOOK_WITH_LOCAL_ONLY,
        WORKFLOW,
        (*BOTH_GATES, "check-local-only.py"),
        "FAIL",
    ),
    (
        "CI runs a step the hook does not",
        HOOK,
        WORKFLOW_WITH_EXTRA_STEP,
        (*BOTH_GATES, "check-ci-only.py"),
        "FAIL",
    ),
    (
        "the local-only step is commented out",
        HOOK_WITH_COMMENTED_STEP,
        WORKFLOW,
        (*BOTH_GATES, "check-local-only.py"),
        "OK",
    ),
    # No hook at all: nothing local can then be stricter than CI, so the older
    # comparison — does CI invoke the gate scripts that exist — is the whole of
    # parity rather than a part of it, and still has to pass.
    ("there is no hook to compare", None, WORKFLOW, BOTH_GATES, "OK"),
]


@pytest.mark.parametrize(("label", "hook", "workflow", "scripts", "expected"), PARITY_CASES)
def test_parity_compares_the_hook_against_ci_in_both_directions(
    fake_root: Path,
    label: str,
    hook: str | None,
    workflow: str,
    scripts: tuple[str, ...],
    expected: str,
) -> None:
    _parity_repo(fake_root, hook, workflow, scripts)
    status, detail = check_all.check_ci_parity()
    assert status == expected, f"{label}: {status} {detail}"


def test_the_drifting_step_is_named_rather_than_merely_counted(fake_root: Path) -> None:
    """A parity failure that does not say which step drifted sends the reader
    back to diffing two files by hand, which is the work this check replaces."""
    _parity_repo(fake_root, HOOK_WITH_LOCAL_ONLY, WORKFLOW, (*BOTH_GATES, "check-local-only.py"))
    status, detail = check_all.check_ci_parity()
    assert status == "FAIL"
    assert "scripts/check-local-only.py" in detail
    assert "no enabled CI job does" in detail


@pytest.mark.parametrize(("label", "hook", "workflow", "scripts", "expected"), PARITY_CASES)
def test_the_node_gate_compares_hook_and_ci_the_same_way(
    tmp_path: Path,
    label: str,
    hook: str | None,
    workflow: str,
    scripts: tuple[str, ...],
    expected: str,
) -> None:
    """Two implementations of one rule drift apart unless something compares
    them, and this rule was added to both files at once."""
    repo = tmp_path / label.replace(" ", "-")
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _parity_repo(repo, hook, workflow, scripts)
    status, detail = _node_verdict(repo, "checkCiParity")
    assert status == expected, f"{label}: {status} {detail}"


def test_this_repository_hook_is_found_where_it_actually_lives() -> None:
    """The anti-vacuity guard for everything above. If hook discovery stops
    finding this repository's pre-commit file, `check_ci_parity` silently falls
    back to the one-sided question it used to ask and every fixture above keeps
    passing, because those trees supply their own hook.
    """
    assert check_all.ROOT == ROOT
    hook = check_all.pre_commit_hook()
    assert hook is not None, "core.hooksPath is scripts/hooks; the hook was not discovered"
    assert hook == ROOT / "scripts" / "hooks" / "pre-commit"


def test_the_real_hook_and_the_real_workflow_run_the_same_gate_scripts() -> None:
    status, detail = check_all.check_ci_parity()
    assert status == "OK", detail
    # The two-way branch, not the early return that fires when no hook exists.
    assert "pre-commit" in detail, detail


# ── a fenced block must not hide the rest of the file ────────────────────

FENCE = "```"


def _doc(fence_extra: str = "", tail: str = "") -> str:
    """A CLAUDE.md shaped like this repository's: an inline path reference, then
    a fenced Commands block, then prose carrying more inline references. The
    fence is the whole point — before the fix, everything below it was invisible
    to the check while it reported "referenced paths exist"."""
    lines = [
        "# project",
        "",
        "- `evals/oracle/derived.json` — the committed snapshot.",
        "",
        "## Commands",
        "",
        FENCE + "bash",
        "python scripts/check_all.py        # the Python gate",
    ]
    if fence_extra:
        lines.append(fence_extra)
    lines += [
        FENCE,
        "",
        "Never bypass with `--no-verify`. Triage files live in `triage/`, never",
        "in `queue/`.",
    ]
    if tail:
        lines += ["", tail]
    return "\n".join(lines) + "\n"


def _doc_repo(root: Path, doc: str, name: str = "CLAUDE.md") -> None:
    (root / "evals" / "oracle").mkdir(parents=True, exist_ok=True)
    (root / "evals" / "oracle" / "derived.json").touch()
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "check_all.py").touch()
    (root / name).write_text(doc)


DOC_CASES: list[tuple[str, str, str]] = [
    ("every reference resolves", _doc(), "OK"),
    # The reviewer's exact reproduction: a token appended after the fence.
    ("a path appended below the fence", _doc(tail="See `xyz/nonexistent` for details."), "WARN"),
    # The Commands block itself was never read by any spelling of this check,
    # and it is the part of the file that tells an agent which script to run.
    ("a path inside the fenced block", _doc(fence_extra="python scripts/gone.py"), "WARN"),
    # `triage/` and `queue/` are bare directory names; the sentence beside them
    # spells the anchored form. Resolving a bare name against the repository
    # root would report drift that is not there, on a file that is correct.
    ("a bare directory name below the fence", _doc(), "OK"),
]


@pytest.mark.parametrize(("label", "doc", "expected"), DOC_CASES)
def test_a_fenced_block_does_not_hide_the_paths_beneath_it(
    fake_root: Path, label: str, doc: str, expected: str
) -> None:
    _doc_repo(fake_root, doc)
    status, detail = check_all.check_claude_md()
    assert status == expected, f"{label}: {status} {detail}"


@pytest.mark.parametrize(("label", "doc", "expected"), DOC_CASES)
def test_the_node_gate_reads_the_same_markdown_the_same_way(
    tmp_path: Path, label: str, doc: str, expected: str
) -> None:
    repo = tmp_path / label.replace(" ", "-")
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _doc_repo(repo, doc)
    status, detail = _node_verdict(repo, "checkClaudeMd")
    assert status == expected, f"{label}: {status} {detail}"


def test_the_extractor_reaches_the_inline_spans_below_a_fence() -> None:
    """The mechanism, asserted directly rather than only through a verdict.
    The old extractor paired the third backtick of the opening fence with the
    first of the closing one and spent the rest of the file pairing the PROSE
    between inline spans — every run of which contains a space, so the path
    filter discarded them all without a word."""
    toks = check_all.markdown_paths(_doc(tail="See `xyz/nonexistent` for details."))
    assert "xyz/nonexistent" in toks
    assert "--no-verify" in toks
    # The fenced body contributes its words, so a renamed script in the
    # Commands block is a finding rather than a silence.
    assert "scripts/check_all.py" in toks


def test_one_file_under_two_names_is_one_finding(fake_root: Path) -> None:
    """CLAUDE.md is a symlink to AGENTS.md here, so the loop over both names
    read one inode twice and printed every finding twice — a reader counting
    lines would think two files disagreed with the tree."""
    _doc_repo(fake_root, _doc(tail="See `xyz/nonexistent` for details."), name="AGENTS.md")
    (fake_root / "CLAUDE.md").symlink_to("AGENTS.md")
    status, detail = check_all.check_claude_md()
    assert status == "WARN", detail
    assert detail.count("xyz/nonexistent") == 1, detail


def test_a_path_git_ignores_is_not_reported_as_documentation_drift(fake_root: Path) -> None:
    """`.venv/bin/python` and everything under `.captain/` are referenced by
    this repository's CLAUDE.md, exist on a developer machine and do not exist
    in a CI checkout at all. Reporting them would make the verdict depend on
    which machine ran the gate.

    Paired with a token that is NOT ignored, because "skip the ignored ones" is
    one edit away from "skip everything that is missing".
    """
    subprocess.run(["git", "init", "-q", str(fake_root)], check=True)
    (fake_root / ".gitignore").write_text(".venv/\n")
    _doc_repo(fake_root, _doc(tail="Use `.venv/bin/python`, never the system one."))
    assert check_all.check_claude_md()[0] == "OK"

    _doc_repo(fake_root, _doc(tail="Use `tools/bin/python`, never the system one."))
    status, detail = check_all.check_claude_md()
    assert status == "WARN", detail
    assert "tools/bin/python" in detail
