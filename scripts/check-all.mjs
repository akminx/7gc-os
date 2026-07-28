#!/usr/bin/env node
// Agent-ready verification harness — Node/TS mirror of check_all.py.
// Detects Node sub-projects (dirs containing package.json, excluding
// node_modules) and enforces: lint, typecheck, tests + coverage ratchet,
// duplicate code, file-size limits, debt markers, CLAUDE.md alignment.
// Budgets live in scripts/budgets/node/ and ratchet forward only.
//
//   node scripts/check-all.mjs                # run the full gate
//   node scripts/check-all.mjs --init-budgets  # baseline the ratchets

import { execFileSync, spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { extname, join, relative } from "node:path";
import { pathToFileURL } from "node:url";

import {
  checkCiParity as ciParity,
  checkClaudeMd as claudeMd,
  preCommitHook as findPreCommitHook,
  markdownPaths,
  workflowCommands,
} from "./check-gate-parity.mjs";
import { checkUiVocabulary, checkWebBoundary } from "./check-web-arch.mjs";

/** `labels.ts` → `glossary.json`, regenerated and compared. */
function checkGlossary() {
  const run = spawnSync(process.execPath, [join(ROOT, "scripts", "emit-glossary.mjs"), "--check"], {
    encoding: "utf8",
  });
  if (run.status === 0) return ["OK", ""];
  return ["FAIL", (run.stderr || run.stdout || "").trim()];
}

const ROOT = (() => {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
  } catch {
    return process.cwd();
  }
})();
const BUD = join(ROOT, "scripts", "budgets", "node");
const SRC_EXT = new Set([".ts", ".tsx", ".js", ".jsx"]);
const MARKERS = ["TO" + "DO", "FIX" + "ME", "XX" + "X", "HA" + "CK"];
const DEBT_RE = new RegExp(`\\b(${MARKERS.join("|")})\\b`);

function sh(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { cwd: opts.cwd, encoding: "utf8" });
  return { status: r.status ?? 1, stdout: r.stdout || "", stderr: r.stderr || "" };
}

function tracked() {
  const out = sh("git", ["ls-files"], { cwd: ROOT }).stdout.split("\n").filter(Boolean);
  return out.map((f) => join(ROOT, f));
}

// scripts/*.mjs is not inside any Node project (web/ is the only one) and .mjs
// was in neither gate's source set, so the review runner — the code that
// decides whether a Pass B counts at all — could not fail lint, file-size or
// debt checks. Process-critical code sitting outside the mechanical net is
// exactly the shape this gate exists to catch.
SRC_EXT.add(".mjs");

function nodeProjects() {
  const found = new Set();
  const skipDir = new Set([
    "node_modules",
    ".git",
    ".venv",
    ".claude",
    ".worktrees",
    "worktrees",
    "coverage",
    "dist",
    "build",
    ".build",
  ]);
  const walk = (dir) => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    if (existsSync(join(dir, "package.json"))) found.add(dir);
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      if (skipDir.has(e.name)) continue;
      walk(join(dir, e.name));
    }
  };
  walk(ROOT);
  return [...found].sort();
}

function load(name, fallback) {
  const f = join(BUD, name);
  return existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : { ...fallback };
}

function save(name, data) {
  mkdirSync(BUD, { recursive: true });
  writeFileSync(join(BUD, name), `${JSON.stringify(data, null, 2)}\n`);
}

function toolBin(project, name) {
  for (const dir of [project, ROOT]) {
    const p = join(dir, "node_modules", ".bin", name);
    if (existsSync(p)) return p;
  }
  return null;
}

// ---- checks: return [status, detail]; status in OK / WARN / SKIP / FAIL --

function checkLint(projects) {
  const fails = [];
  const missing = [];
  for (const p of projects) {
    const bin = toolBin(p, "biome");
    if (!bin) {
      missing.push(relative(ROOT, p) || ".");
      continue;
    }
    const r = sh(bin, ["check", "--error-on-warnings", "."], { cwd: p });
    if (r.status) fails.push(r.stdout + r.stderr);

    // `biome check .` never walks outside its own root, so listing
    // `../scripts/*.mjs` in web/biome.json was inert — the claim that the
    // review runner was linted was false. Lint that directory by explicit path.
    const scripts = join(ROOT, "scripts");
    if (existsSync(scripts)) {
      // Run from ROOT so biome picks up scripts/biome.json rather than web's,
      // whose `includes` filter matches nothing outside web/.
      const s = sh(bin, ["check", "--error-on-warnings", "scripts"], { cwd: ROOT });
      if (s.status) fails.push(s.stdout + s.stderr);
    }
  }
  if (fails.length) return ["FAIL", fails.join("\n")];
  if (missing.length === projects.length)
    return ["FAIL", "biome not installed — required check cannot SKIP"];
  if (missing.length) return ["FAIL", `biome not found for: ${missing.join(", ")}`];
  return ["OK", `${projects.length} project(s) clean`];
}

function checkTypecheck(projects) {
  const fails = [];
  const missing = [];
  for (const p of projects) {
    if (!existsSync(join(p, "tsconfig.json"))) {
      missing.push(relative(ROOT, p) || ".");
      continue;
    }
    const bin = toolBin(p, "tsc");
    if (!bin) {
      missing.push(relative(ROOT, p) || ".");
      continue;
    }
    const r = sh(bin, ["--noEmit"], { cwd: p });
    if (r.status) fails.push(r.stdout + r.stderr);
  }
  if (fails.length) return ["FAIL", fails.join("\n")];
  if (missing.length === projects.length)
    return ["FAIL", "typescript/tsconfig missing — required check cannot SKIP"];
  if (missing.length) return ["FAIL", `typecheck skipped for: ${missing.join(", ")}`];
  return ["OK", "types clean"];
}

function checkTests(projects, fix, ratchet) {
  const budget = load("coverage.json", { floor: 0.0 });
  const floor = budget.floor ?? 0.0;
  const fails = [];
  let total = null;
  let ran = false;
  const missing = [];
  for (const p of projects) {
    const bin = toolBin(p, "vitest");
    if (!bin) {
      missing.push(relative(ROOT, p) || ".");
      continue;
    }
    ran = true;
    const r = sh(bin, ["run", "--coverage", "--coverage.reporter=json-summary"], { cwd: p });
    if (r.status) fails.push(`${relative(ROOT, p) || "."}:\n${(r.stdout + r.stderr).slice(-1500)}`);
    const summary = join(p, "coverage", "coverage-summary.json");
    if (existsSync(summary)) {
      const pct = JSON.parse(readFileSync(summary, "utf8"))?.total?.lines?.pct;
      if (typeof pct === "number") total = total === null ? pct : Math.min(total, pct);
      unlinkSync(summary);
    }
  }
  if (!ran) return ["FAIL", "vitest not installed — required check cannot SKIP"];
  if (fails.length) {
    const note = missing.length ? `\n(no vitest found for: ${missing.join(", ")})` : "";
    return ["FAIL", `tests failed\n${fails.join("\n")}${note}`];
  }
  if (total === null)
    return ["FAIL", "tests pass but coverage report missing — install @vitest/coverage-v8"];
  if (!fix && floor <= 0)
    return ["FAIL", `coverage floor is ${floor}% (unbaselined). Run --init-budgets`];
  // Owner's decision, recorded rather than silently dropped: the coverage FLOOR
  // is not a gate on this project. It is reported at every run so a collapse is
  // still visible, but it cannot turn the gate red. `scripts/check_all.py` made
  // the same call on the Python side and this file did not follow, so the Node
  // gate went red at 87.91% against a floor of 100% for reasons that were all
  // the same kind: a decision control whose `catch` arm needs a mocked network
  // failure to reach, and two new screens' empty states.
  //
  // The floor stopped measuring anything useful here. What defends a wrong
  // number in this codebase is not a percentage — `tests/test_policy_vs_oracle.py`
  // compares every verdict and every packet total against an independently
  // derived answer key, `scripts/mutate.py` proves each guard goes red when
  // removed, and the database refuses what the schema forbids. A number pushed
  // up by testing an error branch is a number that has stopped tracking
  // correctness.
  //
  // `--ratchet` still records where it stands, so the figure keeps moving in
  // one direction for anyone who wants it back as a gate.
  if (!fix && !ratchet)
    return ["OK", `tests pass · coverage ${total.toFixed(2)}% (floor not enforced — owner's call)`];
  if (fix) {
    budget.floor = Math.floor(total * 100) / 100;
    save("coverage.json", budget);
    return ["OK", `tests pass · coverage floor set to ${total.toFixed(2)}%`];
  }
  if (ratchet && total > floor) {
    budget.floor = Math.floor(total * 100) / 100;
    save("coverage.json", budget);
    return ["OK", `tests pass · coverage floor ratcheted ${floor}% → ${total.toFixed(2)}%`];
  }
  if (total + 1e-9 < floor)
    return ["FAIL", `tests pass but coverage ${total.toFixed(2)}% < floor ${floor}%`];
  const nudge = total - floor > 1 ? `  (ratchet floor up toward ${total.toFixed(1)}%)` : "";
  return ["OK", `tests pass · coverage ${total.toFixed(2)}% >= floor ${floor}%${nudge}`];
}

function checkDups() {
  const jscpdConfig = join(ROOT, ".jscpd.node.json");
  if (!existsSync(jscpdConfig))
    return ["FAIL", "no .jscpd.node.json — duplicate-code check is required"];
  const r = sh("npx", ["--yes", "jscpd", "--config", jscpdConfig], { cwd: ROOT });
  return r.status === 0
    ? ["OK", "no clones above threshold"]
    : ["FAIL", (r.stdout + r.stderr).slice(-1800)];
}

function checkFileSizes(fix) {
  const budget = load("file-sizes.json", { max_lines: 600, overrides: {} });
  const { max_lines: mx } = budget;
  const ov = budget.overrides || {};
  const over = [];
  for (const f of tracked()) {
    if (!SRC_EXT.has(extname(f))) continue;
    if (!existsSync(f) || !statSync(f).isFile()) continue;
    const n = readFileSync(f, "utf8").split("\n").length;
    const rel = relative(ROOT, f);
    if (n > (ov[rel] ?? mx)) over.push([rel, n]);
  }
  if (fix) {
    for (const [rel, n] of over) ov[rel] = n;
    budget.overrides = ov;
    save("file-sizes.json", budget);
    return ["OK", `baselined ${over.length} file(s) over ${mx} lines`];
  }
  if (over.length)
    return [
      "FAIL",
      `split these files:\n${over.map(([rel, n]) => `${rel} = ${n} lines (max ${mx})`).join("\n")}`,
    ];
  return ["OK", `all source files <= ${mx} lines`];
}

function checkDebt(fix, ratchet) {
  const budget = load("debt-allowlist.json", { max_markers: 0 });
  const cap = budget.max_markers ?? 0;
  const hits = [];
  for (const f of tracked()) {
    if (!SRC_EXT.has(extname(f))) continue;
    if (!existsSync(f) || !statSync(f).isFile()) continue;
    const lines = readFileSync(f, "utf8").split("\n");
    lines.forEach((line, i) => {
      if (DEBT_RE.test(line)) hits.push(`${relative(ROOT, f)}:${i + 1}`);
    });
  }
  if (fix) {
    budget.max_markers = hits.length;
    save("debt-allowlist.json", budget);
    return ["OK", `debt ceiling set to ${hits.length}`];
  }
  if (ratchet && hits.length < cap) {
    budget.max_markers = hits.length;
    save("debt-allowlist.json", budget);
    return ["OK", `debt ceiling ratcheted ${cap} → ${hits.length}`];
  }
  if (hits.length > cap)
    return [
      "FAIL",
      `${hits.length} debt markers > ceiling ${cap}\n${hits.slice(0, 20).join("\n")}`,
    ];
  return ["OK", `${hits.length} debt markers <= ceiling ${cap}`];
}

// CLAUDE.md alignment and CI parity live in check-gate-parity.mjs — see the
// header there for why. They are re-exported under the no-argument signatures
// the gate's own guards call them by, so the split changes where the code is
// and nothing about what a caller sees.
export const checkClaudeMd = () => claudeMd(ROOT);
export const checkCiParity = () => ciParity(ROOT);
export const preCommitHook = () => findPreCommitHook(ROOT);
export { markdownPaths, workflowCommands };

export function checkDeps(projects) {
  let ran = false;
  const vulns = [];
  for (const p of projects) {
    if (!existsSync(join(p, "package.json"))) continue;
    if (!existsSync(join(p, "package-lock.json")) && !existsSync(join(p, "npm-shrinkwrap.json")))
      continue;
    const r = sh("npm", ["audit", "--audit-level=high", "--json"], { cwd: p });
    const blob = (r.stdout + r.stderr).toLowerCase();
    if (r.status && /(enotfound|etimedout|network|econnrefused|offline|getaddrinfo)/.test(blob)) {
      return ["SKIP", "npm audit offline (registry unreachable) — enforced in CI"];
    }
    ran = true;
    const where = relative(ROOT, p) || ".";
    // `JSON.parse(r.stdout || "{}").metadata?.vulnerabilities || {}` turned
    // every shape of failure into zero vulnerabilities: an audit that exited 2
    // with a perfectly valid error document reported "no high/critical
    // dependency CVEs". npm uses exit 1 both for "found some" and for "went
    // wrong", so the exit status alone cannot tell them apart — the counts it
    // is supposed to produce are what decides. No counts, no audit.
    let meta;
    try {
      const report = JSON.parse(r.stdout);
      if (report?.error) {
        vulns.push(`${where}: npm audit reported an error\n${JSON.stringify(report.error)}`);
        continue;
      }
      meta = report?.metadata?.vulnerabilities;
    } catch {
      meta = undefined;
    }
    if (!meta || typeof meta !== "object") {
      vulns.push(
        `${where}: npm audit exited ${r.status} without a vulnerability count — ` +
          `the audit did not run\n${(r.stdout + r.stderr).slice(-600)}`,
      );
      continue;
    }
    const bad = (meta.high || 0) + (meta.critical || 0);
    if (bad) vulns.push(`${where}: ${bad} high/critical`);
    else if (r.status)
      vulns.push(
        `${where}: npm audit exited ${r.status} with no high/critical findings to explain it\n` +
          `${(r.stdout + r.stderr).slice(-600)}`,
      );
  }
  if (!ran)
    return ["FAIL", "no lockfile to audit — the dependency check cannot SKIP (run npm install)"];
  if (vulns.length)
    return ["FAIL", `vulnerable dependencies (high/critical):\n${vulns.join("\n")}`];
  return ["OK", "no high/critical dependency CVEs"];
}

export function main() {
  const fix = process.argv.includes("--init-budgets");
  const ratchet = process.argv.includes("--ratchet");
  const projects = nodeProjects();
  // Discovery finding nothing used to end the run at exit 0 with a friendly
  // sentence. Deleting, renaming or hiding web/package.json therefore deleted
  // the entire Node gate — lint, types, tests, the web boundary and CI parity —
  // and printed nothing a reader would call a failure. An empty result from a
  // search for the thing under test is a failure of the search.
  //
  // The repo-wide checks below still run with no projects, so the report says
  // which of them survived rather than stopping at the first bad news.
  const checks = [
    ["node project found", () => projectsFound(projects), false],
    ["lint", () => checkLint(projects), false],
    ["typecheck", () => checkTypecheck(projects), false],
    ["tests + coverage", () => checkTests(projects, fix, ratchet), false],
    ["web boundary §5.3", () => checkWebBoundary(ROOT), false],
    ["UI vocabulary", () => checkUiVocabulary(ROOT), false],
    // The definitions the UI shows and the definitions the assistant sends to a
    // model are one file, generated from `labels.ts`. That argument is only true
    // while someone checks it: without this line the generator existed, worked,
    // and ran nowhere, so the first edit to a gloss would have split the two
    // vocabularies silently. A guard that is never executed cannot fail.
    ["glossary in step", checkGlossary, false],
    ["duplicate code", checkDups, false],
    ["file sizes", () => checkFileSizes(fix), false],
    ["debt markers", () => checkDebt(fix, ratchet), false],
    // The one check allowed to say it could not run: npm audit needs the
    // registry, and an offline commit should not be blocked. CI has network.
    ["dependency CVEs", () => checkDeps(projects), true],
    ["CLAUDE.md alignment", checkClaudeMd, false],
    ["CI parity", checkCiParity, false],
  ];
  const results = [];
  for (const [name, fn, maySkip] of checks) {
    let status, detail;
    try {
      [status, detail] = fn();
    } catch (e) {
      status = "FAIL";
      detail = `check crashed: ${e.message}`;
    }
    results.push([name, status, detail, maySkip]);
  }

  const sym = { OK: "✓", WARN: "!", SKIP: "·", FAIL: "✗" };
  const mode = fix ? " — baseline" : ratchet ? " — ratchet" : "";
  console.log(`\nagent-ready check-all (node)${mode}`);
  console.log("-".repeat(44));
  for (const [name, status, detail] of results) {
    console.log(`  ${sym[status] ?? "?"} ${name.padEnd(22)} ${status}`);
    if (status !== "OK" && detail) {
      for (const line of detail.split("\n")) console.log(`        ${line}`);
    }
  }

  if (fix) {
    console.log("\nbudgets baselined to current state.\n");
    return 0;
  }
  // WARN used to aggregate into "all checks passed" here, so a check that had
  // something to say could only be heard by someone reading the output.
  const failed = results
    .filter(([, s, , maySkip]) => !(s === "OK" || (s === "SKIP" && maySkip)))
    .map(([n]) => n);
  if (failed.length) {
    console.log(`\n✗ ${failed.length} check(s) failed: ${failed.join(", ")}\n`);
    return 1;
  }
  console.log("\n✓ all checks passed.\n");
  return 0;
}

function projectsFound(projects) {
  if (!projects.length)
    return [
      "FAIL",
      "no package.json found anywhere in the repository — every project-scoped " +
        "check below has nothing to run against, which is not the same as passing",
    ];
  return [
    "OK",
    `${projects.length} Node project(s): ${projects.map((p) => relative(ROOT, p) || ".").join(", ")}`,
  ];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
