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
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync, mkdirSync, unlinkSync } from "node:fs";
import { join, relative, extname } from "node:path";

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
    "node_modules", ".git", ".venv", ".claude", ".worktrees", "worktrees",
    "coverage", "dist", "build", ".build",
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
  writeFileSync(join(BUD, name), JSON.stringify(data, null, 2) + "\n");
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
  }
  if (fails.length) return ["FAIL", fails.join("\n")];
  if (missing.length === projects.length) return ["FAIL", "biome not installed — required check cannot SKIP"];
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
  if (missing.length === projects.length) return ["FAIL", "typescript/tsconfig missing — required check cannot SKIP"];
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
    return ["FAIL", "tests failed\n" + fails.join("\n") + note];
  }
  if (total === null) return ["FAIL", "tests pass but coverage report missing — install @vitest/coverage-v8"];
  if (!fix && floor <= 0) return ["FAIL", `coverage floor is ${floor}% (unbaselined). Run --init-budgets`];
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
  if (total + 1e-9 < floor) return ["FAIL", `tests pass but coverage ${total.toFixed(2)}% < floor ${floor}%`];
  const nudge = total - floor > 1 ? `  (ratchet floor up toward ${total.toFixed(1)}%)` : "";
  return ["OK", `tests pass · coverage ${total.toFixed(2)}% >= floor ${floor}%${nudge}`];
}

function checkDups() {
  const jscpdConfig = join(ROOT, ".jscpd.node.json");
  if (!existsSync(jscpdConfig)) return ["FAIL", "no .jscpd.node.json — duplicate-code check is required"];
  const r = sh("npx", ["--yes", "jscpd", "--config", jscpdConfig], { cwd: ROOT });
  return r.status === 0 ? ["OK", "no clones above threshold"] : ["FAIL", (r.stdout + r.stderr).slice(-1800)];
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
  if (over.length) return ["FAIL", "split these files:\n" + over.map(([rel, n]) => `${rel} = ${n} lines (max ${mx})`).join("\n")];
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
  if (hits.length > cap) return ["FAIL", `${hits.length} debt markers > ceiling ${cap}\n` + hits.slice(0, 20).join("\n")];
  return ["OK", `${hits.length} debt markers <= ceiling ${cap}`];
}

function checkClaudeMd() {
  const missing = [];
  for (const name of ["CLAUDE.md", "AGENTS.md"]) {
    const cf = join(ROOT, name);
    if (!existsSync(cf)) continue;
    const text = readFileSync(cf, "utf8");
    for (const m of text.matchAll(/`([^`]+)`/g)) {
      const tok = m[1].trim();
      if (!tok.includes("/") || tok.includes(" ") || /[*<>]/.test(tok)) continue;
      if (/^(http|npm |git |localhost)/.test(tok)) continue;
      if (!existsSync(join(ROOT, tok.replace(/\/$/, "")))) missing.push(`${name}: \`${tok}\``);
    }
  }
  if (missing.length) return ["WARN", "paths referenced but not found:\n" + missing.join("\n")];
  return ["OK", "referenced paths exist"];
}

function checkCiParity() {
  const wfDir = join(ROOT, ".github", "workflows");
  if (!existsSync(wfDir)) return ["SKIP", "no .github/workflows"];
  const gates = [];
  if (existsSync(join(ROOT, "scripts", "check_all.py"))) gates.push("check_all.py");
  if (existsSync(join(ROOT, "scripts", "check-all.mjs"))) gates.push("check-all.mjs");
  if (!gates.length) return ["SKIP", "no local gate to compare"];
  let text = "";
  for (const f of readdirSync(wfDir)) {
    if (/\.ya?ml$/.test(f)) text += readFileSync(join(wfDir, f), "utf8");
  }
  if (!text) return ["SKIP", "no workflow files"];
  const absent = gates.filter((g) => !text.includes(g));
  if (absent.length) {
    return [
      "FAIL",
      `CI workflows don't run the local gate: ${absent.join(", ")}\n` +
        "add a step invoking it so local green == CI green",
    ];
  }
  return ["OK", "CI runs the same gate(s) as local"];
}

function checkDeps(projects) {
  let ran = false;
  const vulns = [];
  for (const p of projects) {
    if (!existsSync(join(p, "package.json"))) continue;
    if (!existsSync(join(p, "package-lock.json")) && !existsSync(join(p, "npm-shrinkwrap.json"))) continue;
    const r = sh("npm", ["audit", "--audit-level=high", "--json"], { cwd: p });
    const blob = (r.stdout + r.stderr).toLowerCase();
    if (r.status && /(enotfound|etimedout|network|econnrefused|offline|getaddrinfo)/.test(blob)) {
      return ["SKIP", "npm audit offline (registry unreachable) — enforced in CI"];
    }
    ran = true;
    try {
      const meta = JSON.parse(r.stdout || "{}").metadata?.vulnerabilities || {};
      const bad = (meta.high || 0) + (meta.critical || 0);
      if (bad) vulns.push(`${relative(ROOT, p) || "."}: ${bad} high/critical`);
    } catch {
      if (r.status) vulns.push(`${relative(ROOT, p) || "."}: audit failed\n${(r.stdout + r.stderr).slice(-600)}`);
    }
  }
  if (!ran) return ["SKIP", "no lockfile to audit (run npm install first)"];
  if (vulns.length) return ["FAIL", "vulnerable dependencies (high/critical):\n" + vulns.join("\n")];
  return ["OK", "no high/critical dependency CVEs"];
}

function main() {
  const fix = process.argv.includes("--init-budgets");
  const ratchet = process.argv.includes("--ratchet");
  const projects = nodeProjects();
  if (!projects.length) {
    console.log("\nno Node projects found (no package.json) — nothing to check.\n");
    return 0;
  }
  const checks = [
    ["lint", () => checkLint(projects)],
    ["typecheck", () => checkTypecheck(projects)],
    ["tests + coverage", () => checkTests(projects, fix, ratchet)],
    ["duplicate code", checkDups],
    ["file sizes", () => checkFileSizes(fix)],
    ["debt markers", () => checkDebt(fix, ratchet)],
    ["dependency CVEs", () => checkDeps(projects)],
    ["CLAUDE.md alignment", checkClaudeMd],
    ["CI parity", checkCiParity],
  ];
  const results = [];
  for (const [name, fn] of checks) {
    let status, detail;
    try {
      [status, detail] = fn();
    } catch (e) {
      status = "FAIL";
      detail = `check crashed: ${e.message}`;
    }
    results.push([name, status, detail]);
  }

  const sym = { OK: "✓", WARN: "!", SKIP: "·", FAIL: "✗" };
  const mode = fix ? " — baseline" : ratchet ? " — ratchet" : "";
  console.log(`\nagent-ready check-all (node)${mode}`);
  console.log("-".repeat(44));
  for (const [name, status, detail] of results) {
    console.log(`  ${sym[status] ?? "?"} ${name.padEnd(22)} ${status}`);
    if ((status === "FAIL" || status === "WARN") && detail) {
      for (const line of detail.split("\n")) console.log(`        ${line}`);
    }
  }

  if (fix) {
    console.log("\nbudgets baselined to current state.\n");
    return 0;
  }
  const failed = results.filter(([, s]) => s === "FAIL" || s === "SKIP").map(([n]) => n);
  if (failed.length) {
    console.log(`\n✗ ${failed.length} check(s) failed: ${failed.join(", ")}\n`);
    return 1;
  }
  console.log("\n✓ all checks passed.\n");
  return 0;
}

process.exit(main());
