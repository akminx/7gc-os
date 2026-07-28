// The two gate checks that ask whether this project's own prose and its CI
// still describe what actually runs: CLAUDE.md path alignment, and parity
// between the pre-commit hook and the workflows.
//
// Split out of check-all.mjs, which crossed the 600-line ceiling its own
// file-size check enforces once both checks stopped being one-liners. The
// alternative was an entry in scripts/budgets/node/file-sizes.json, which is
// the gate waiving its own rule for the file that implements it.
//
// ROOT is a parameter rather than a module-level constant: check-all.mjs owns
// the single `git rev-parse` that finds the tree, and the Python twin's
// check_all.ROOT is monkeypatched by the guards in tests/test_gate_parity.py,
// so both sides stay pointable at a synthetic tree.

import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, realpathSync } from "node:fs";
import { join, relative } from "node:path";

const git = (args, cwd) => spawnSync("git", args, { cwd, encoding: "utf8" }).stdout || "";

const FENCE = /^\s{0,3}(`{3,}|~{3,})/;
const FENCED_WORD = /[A-Za-z0-9_./-]+/g;

// Every token in a markdown file that could be naming a path.
//
// The extractor was `text.matchAll(/`([^`]+)`/g)` over the whole file, and a
// fenced code block silently inverts what that pairs. An opening fence is three
// backticks: the scanner consumes the third as an opening delimiter, closes it
// on the FIRST backtick of the closing fence, and from there on it pairs the
// prose BETWEEN inline spans rather than the spans themselves. Every one of
// those prose runs contains a space, so the filter below discarded them without
// a word — and every real inline path below the fence was never looked at.
//
// In this repository that hid nine of the eleven sections: appending
// `xyz/nonexistent` to the end of CLAUDE.md was not detected, while breaking a
// token above the Commands block was. The check printed "referenced paths
// exist" having read a quarter of the file.
//
// So fences are separated from prose before anything is paired. Prose
// contributes its inline spans. A fence contributes its own words, because the
// Commands block lists the scripts an agent is told to run and it was the one
// part of the file this check had never read at all.
export function markdownPaths(text) {
  const prose = [];
  const fenced = [];
  let fence = "";
  for (const line of text.split("\n")) {
    const m = FENCE.exec(line);
    const marker = m ? m[1][0].repeat(3) : "";
    if (!fence) {
      if (marker) fence = marker;
      else prose.push(line);
    } else if (marker === fence) {
      fence = "";
    } else {
      fenced.push(line);
    }
  }
  const toks = [...prose.join("\n").matchAll(/`([^`]+)`/g)].map((m) => m[1]);
  return toks.concat(fenced.join("\n").match(FENCED_WORD) ?? []);
}

// Which of these repository-relative paths git ignores. Tracked paths are never
// reported, which is what `check-ignore` does by default.
function gitIgnored(ROOT, rels) {
  if (!rels.length) return new Set();
  const out = git(["check-ignore", "--", ...rels], ROOT);
  return new Set(
    out
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean),
  );
}

// The paths CLAUDE.md points an agent at still exist. Its failure mode is a doc
// that survives a rename and quietly misdirects every reader after it.
export function checkClaudeMd(ROOT) {
  const candidates = [];
  const seen = new Set();
  for (const name of ["CLAUDE.md", "AGENTS.md"]) {
    const cf = join(ROOT, name);
    if (!existsSync(cf)) continue;
    // In this repository CLAUDE.md is a symlink to AGENTS.md, so the two names
    // are one inode and every finding was reported twice — a reader counting
    // the lines would think two files disagreed with the tree. A repository
    // where the two are genuinely separate files still gets both, because this
    // compares what they resolve to and not their names.
    const real = realpathSync(cf);
    if (seen.has(real)) continue;
    seen.add(real);
    for (const raw of markdownPaths(readFileSync(cf, "utf8"))) {
      const tok = raw.trim();
      if (tok.includes(" ") || /[*<>]/.test(tok)) continue;
      // A leading separator is an absolute path or the scheme-relative tail of
      // a URL (`//example.com/x`, once the charset above has dropped the
      // colon). Neither is a path in this repository.
      if (/^(http|npm |git |localhost|\/)/.test(tok)) continue;
      // A separator BETWEEN two segments is what makes a token a
      // repository-relative path. `triage/` and `queue/` in the review section
      // are bare directory names — the sentence beside them spells the anchored
      // form, `.captain/review/triage/` — and resolving a bare name against the
      // root reports drift that is not there. The cost is that a bare `web/`
      // goes unchecked; no token this check has ever verified is of that shape.
      if (!tok.replace(/^\/+|\/+$/g, "").includes("/")) continue;
      if (existsSync(join(ROOT, tok.replace(/\/$/, "")))) continue;
      candidates.push([name, tok]);
    }
  }
  // A path git ignores is present on some machines and absent on others:
  // `.venv/bin/python` and everything under `.captain/` exist locally and do not
  // exist in a CI checkout at all. Reporting those as documentation drift would
  // make this check's verdict depend on which machine ran it, which is the one
  // thing a gate may not do.
  const ignored = gitIgnored(
    ROOT,
    candidates.map(([, t]) => t.replace(/\/$/, "")),
  );
  const missing = candidates
    .filter(([, t]) => !ignored.has(t.replace(/\/$/, "")))
    .map(([n, t]) => `${n}: \`${t}\``);
  if (missing.length) return ["WARN", `paths referenced but not found:\n${missing.join("\n")}`];
  return ["OK", "referenced paths exist"];
}

const RUN_KEY = /^(\s*)(?:-\s+)?run:\s*(.*)$/;
const JOB_KEY = /^ {2}([A-Za-z0-9_.-]+):\s*$/;
const DISABLED = /^ {4}if:\s*(?:false|'false'|"false")\s*$/;
const indentOf = (line) => line.length - line.trimStart().length;

// Every shell command a workflow would actually run. Parity used to be
// `text.includes(gateName)`, which a comment satisfies: a workflow whose whole
// content was `# Historical names only: check_all.py and check-all.mjs` reported
// that CI ran the same gate as local. So does a job switched off with
// `if: false`, and so does a gate named in a step's `name:` while the `run:`
// below it invokes something else. Comments go, disabled jobs go, and what is
// left is the text that becomes a shell command.
export function workflowCommands(text) {
  const lines = text.split("\n");
  const live = [];
  for (let i = 0; i < lines.length; ) {
    if (!JOB_KEY.test(lines[i])) {
      live.push(lines[i]);
      i += 1;
      continue;
    }
    const block = [lines[i]];
    i += 1;
    while (i < lines.length && (!lines[i].trim() || indentOf(lines[i]) > 2)) {
      block.push(lines[i]);
      i += 1;
    }
    if (!block.some((b) => DISABLED.test(b))) live.push(...block);
  }

  const out = [];
  for (let i = 0; i < live.length; ) {
    const line = live[i];
    const m = line.trimStart().startsWith("#") ? null : RUN_KEY.exec(line);
    if (!m) {
      i += 1;
      continue;
    }
    const keyIndent = m[1].length;
    const rest = m[2].trim();
    i += 1;
    if (rest && !["|", ">"].includes(rest.replace(/[+-]+$/, ""))) {
      out.push(rest);
      continue;
    }
    while (i < live.length) {
      const body = live[i];
      if (body.trim() && indentOf(body) <= keyIndent) break;
      if (!body.trimStart().startsWith("#")) out.push(body);
      i += 1;
    }
  }
  return out.join("\n");
}

// A gate step is a script committed to this repository. That is the unit the
// hook and the workflow name in the same words — `scripts/check_all.py` on both
// sides — so it is the unit the two can be compared over. A hook line that runs
// something else entirely (`npm run lint`, an inline `ruff check .`) is outside
// this net and the OK message says so rather than implying otherwise.
const GATE_SCRIPT = /[A-Za-z0-9_.${}/-]*\.(py|mjs|cjs|js|ts|sh)\b/g;
// `"$ROOT/scripts/check_all.py"` and `python3 scripts/check_all.py` are the same
// step written by two different callers. Strip whatever variable holds the repo
// root so they compare equal.
const ROOT_VAR = /^(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\/|\.\/)+/;
// core.hooksPath first, because that is what git actually obeys; the other two
// are where a project puts hooks when it has not configured one. Failing to FIND
// the hook would silently restore the hole this comparison exists to close, so
// tests/test_gate_parity.py asserts that this repository's hook is discovered.
const HOOK_DIRS = ["scripts/hooks", ".git/hooks"];

// Every script of this repository that `text` invokes, repo-relative.
//
// Comment lines go first, for the same reason workflowCommands drops them: a
// gate named in a comment is not a gate that runs. A gate named in a TRAILING
// comment is still counted, and that is deliberate — the error it produces is
// "the hook appears to run something CI does not", a false alarm, and the other
// direction would be a false pass.
export function gateScripts(ROOT, text) {
  const found = new Set();
  for (const line of text.split("\n")) {
    if (line.trimStart().startsWith("#")) continue;
    for (const m of line.matchAll(GATE_SCRIPT)) {
      const tok = m[0].replace(/^["']|["']$/g, "").replace(ROOT_VAR, "");
      // Repo-relative and real. Without the existence test every `.js` in an
      // inline heredoc would look like a gate step.
      if (tok.includes("/") && existsSync(join(ROOT, tok))) found.add(tok);
    }
  }
  return found;
}

export function preCommitHook(ROOT) {
  const configured = git(["config", "core.hooksPath"], ROOT).trim();
  for (const rel of (configured ? [configured] : []).concat(HOOK_DIRS)) {
    const hook = join(ROOT, rel, "pre-commit");
    if (existsSync(hook)) return hook;
  }
  return null;
}

export function checkCiParity(ROOT) {
  const gates = [];
  if (existsSync(join(ROOT, "scripts", "check_all.py"))) gates.push("check_all.py");
  if (existsSync(join(ROOT, "scripts", "check-all.mjs"))) gates.push("check-all.mjs");
  if (!gates.length) return ["SKIP", "no local gate to compare"];
  const wfDir = join(ROOT, ".github", "workflows");
  const files = existsSync(wfDir) ? readdirSync(wfDir).filter((f) => /\.ya?ml$/.test(f)) : [];
  // "There is no CI" and "CI runs the gate" are not the same answer. Deleting
  // the workflow directory used to produce the first and be counted as the
  // second.
  if (!files.length) {
    return [
      "FAIL",
      "a local gate exists but .github/workflows has no workflow to compare it to — " +
        "parity cannot be verified, which is not the same as parity holding",
    ];
  }
  const commands = files
    .map((f) => workflowCommands(readFileSync(join(wfDir, f), "utf8")))
    .join("\n");
  const absent = gates.filter((g) => !commands.includes(g));
  if (absent.length) {
    return [
      "FAIL",
      `no enabled CI job RUNS the local gate: ${absent.join(", ")}\n` +
        "a mention in a comment, a step name or a disabled job is not an invocation",
    ];
  }

  // Everything above answers only "does CI run check_all.py and check-all.mjs".
  // It cannot see a check that exists on ONE side. A reviewer added
  // scripts/check-local-only.py, appended it to the pre-commit hook, and this
  // function still returned ["OK", "1 workflow file(s) run the same gate(s) as
  // local"] — the local hook had become strictly stricter than CI and the line
  // that exists to notice that stayed green. Both directions are a broken
  // promise: a hook step CI lacks means green in CI does not mean the commit
  // would have passed locally, and a CI step the hook lacks means green locally
  // does not mean green in CI.
  const hook = preCommitHook(ROOT);
  // No hook, so nothing local can be stricter than CI: the comparison above is
  // then the whole of parity rather than a part of it.
  if (!hook) return ["OK", `${files.length} workflow file(s) run the same gate(s) as local`];
  const hookScripts = gateScripts(ROOT, readFileSync(hook, "utf8"));
  const ciScripts = gateScripts(ROOT, commands);
  const where = relative(ROOT, hook);
  const drift = [...hookScripts]
    .filter((s) => !ciScripts.has(s))
    .sort()
    .map((s) => `  ${where} runs ${s}, no enabled CI job does`)
    .concat(
      [...ciScripts]
        .filter((s) => !hookScripts.has(s))
        .sort()
        .map((s) => `  CI runs ${s}, ${where} does not`),
    );
  if (drift.length) {
    return [
      "FAIL",
      `${where} and CI do not run the same gate scripts, so 'green locally' and ` +
        "'green in CI' are different promises:\n" +
        drift.join("\n"),
    ];
  }
  return [
    "OK",
    `${files.length} workflow file(s) and ${where} run the same ` +
      `${hookScripts.size} gate script(s)`,
  ];
}
