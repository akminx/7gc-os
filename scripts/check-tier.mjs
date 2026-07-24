#!/usr/bin/env node
// Path-derived risk tier check (REVIEW.md / review-policy.yaml).
// Computes the minimum tier from changed files and fails when a declared
// tier is below that floor — or when trust-critical changes lack an ack.
//
//   node scripts/check-tier.mjs              # local: changed vs HEAD + index
//   node scripts/check-tier.mjs --ci         # PR: base...HEAD + PR body tier
//   GILLY_ACK_TRUST=1                        # local ack for trust-critical
//
// Declared tier sources (first match wins):
//   1. --declare=routine|semantic|trust-critical
//   2. GILLY_DECLARE_TIER env
//   3. PR body checkboxes / "Risk tier: X" (CI only)
//   4. If none and min is routine → OK; if min is higher → FAIL (must declare)

import { execFileSync, spawnSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const ROOT = (() => {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
  } catch {
    return process.cwd();
  }
})();

const TIERS = ["routine", "semantic", "trust-critical"];
const RANK = Object.fromEntries(TIERS.map((t, i) => [t, i]));

function sh(args) {
  const r = spawnSync("git", args, { cwd: ROOT, encoding: "utf8" });
  return (r.stdout || "").split("\n").filter(Boolean);
}

function loadPolicy() {
  const f = join(ROOT, "review-policy.yaml");
  if (!existsSync(f)) {
    console.error("check-tier FAIL: review-policy.yaml missing");
    process.exit(1);
  }
  const text = readFileSync(f, "utf8");
  const trust = [];
  const semantic = [];
  const routine = [];
  let section = null;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/#.*/, "").trimEnd();
    if (/^trust_critical_paths:\s*$/.test(line.trim())) {
      section = "trust";
      continue;
    }
    if (/^semantic_paths:\s*$/.test(line.trim())) {
      section = "semantic";
      continue;
    }
    if (/^routine_paths:\s*$/.test(line.trim())) {
      section = "routine";
      continue;
    }
    if (/^[a-zA-Z_]/.test(line.trim()) && !line.trim().startsWith("-")) {
      section = null;
      continue;
    }
    const m = line.match(/^\s*-\s*"([^"]+)"\s*$/) || line.match(/^\s*-\s*'([^']+)'\s*$/);
    if (!m || !section) continue;
    ({ trust, semantic, routine })[section].push(m[1]);
  }
  return { trust, semantic, routine };
}

// Minimal glob: ** any (incl /), * any except /
//
// A leading "**/" compiles to "(?:.*/)?" — OPTIONAL. Previously it became
// ".*/" , which requires a slash BEFORE the segment, so "evidence/extract.py"
// matched neither "**/evidence*/**" nor "**/extract*/**" and silently resolved
// to `routine`. Every trust glob in this repo was affected.
function globToRegExp(glob) {
  const escaped = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  let prefix = "";
  let rest = escaped;
  if (rest.startsWith("**/")) {
    prefix = "(?:.*/)?";
    rest = rest.slice(3);
  }
  const pattern = rest.replace(/\*\*/g, "\0").replace(/\*/g, "[^/]*").replace(/\0/g, ".*");
  return new RegExp(`^${prefix}${pattern}$`);
}

function matchAny(path, globs) {
  return globs.some((g) => globToRegExp(g).test(path));
}

function changedFiles(ci) {
  if (ci) {
    const base =
      process.env.GITHUB_BASE_REF ||
      process.env.GILLY_TIER_BASE ||
      "origin/main";
    // Prefer merge-base range when available
    const range = process.env.GILLY_TIER_RANGE;
    if (range) return sh(["diff", "--name-only", range]);
    const r = spawnSync("git", ["diff", "--name-only", `${base}...HEAD`], {
      cwd: ROOT,
      encoding: "utf8",
    });
    if (r.status === 0 && (r.stdout || "").trim()) {
      return (r.stdout || "").split("\n").filter(Boolean);
    }
    // Fallback: all commits on branch vs main
    return sh(["diff", "--name-only", "HEAD~1"]);
  }
  const a = sh(["diff", "--name-only", "HEAD"]);
  const b = sh(["diff", "--cached", "--name-only"]);
  return [...new Set([...a, ...b])];
}

// Unmatched paths default to `semantic`, not `routine`. A new file in a new
// directory can no longer land unfloored just because nobody wrote a glob for
// it. `routine_paths` is the explicit allowlist for genuinely routine files.
function minTier(files, policy) {
  let min = "routine";
  const hits = { trust: [], semantic: [], unmatched: [] };
  const rank = { routine: 0, semantic: 1, "trust-critical": 2 };
  for (const f of files) {
    let tier;
    if (matchAny(f, policy.trust)) {
      tier = "trust-critical";
      hits.trust.push(f);
    } else if (matchAny(f, policy.semantic)) {
      tier = "semantic";
      hits.semantic.push(f);
    } else if (matchAny(f, policy.routine)) {
      tier = "routine";
    } else {
      tier = "semantic";
      hits.unmatched.push(f);
    }
    if (rank[tier] > rank[min]) min = tier;
  }
  return { min, hits };
}

function parseDeclared(argv, ci) {
  const flag = argv.find((a) => a.startsWith("--declare="));
  if (flag) return flag.slice("--declare=".length);
  if (process.env.GILLY_DECLARE_TIER) return process.env.GILLY_DECLARE_TIER.trim();
  if (!ci) return null;

  // PR body from GitHub Actions event payload
  const eventPath = process.env.GITHUB_EVENT_PATH;
  let body = process.env.GILLY_PR_BODY || "";
  if (!body && eventPath && existsSync(eventPath)) {
    try {
      const ev = JSON.parse(readFileSync(eventPath, "utf8"));
      body = ev.pull_request?.body || "";
    } catch {
      /* ignore */
    }
  }
  if (!body) return null;

  // Prefer checked checkboxes in PR template order (trust > semantic > routine)
  const checked = [];
  for (const t of TIERS) {
    const re = new RegExp(`^\\s*-\\s*\\[x\\]\\s*\`?${t}\`?`, "im");
    if (re.test(body)) checked.push(t);
  }
  if (checked.length) {
    // Highest declared among checked
    return checked.sort((a, b) => RANK[b] - RANK[a])[0];
  }
  const m = body.match(/risk\s*tier\s*[:\-]\s*`?(routine|semantic|trust-critical)`?/i);
  return m ? m[1].toLowerCase() : null;
}

function main() {
  const argv = process.argv.slice(2);
  const ci = argv.includes("--ci");
  const policy = loadPolicy();

  // --print-tier <path>: resolve one path. Used by scripts/test_tier_map.mjs,
  // which is what stops §5.2 from being a comment.
  const pi = argv.indexOf("--print-tier");
  if (pi !== -1) {
    console.log(minTier([argv[pi + 1]], policy).min);
    return 0;
  }
  const files = changedFiles(ci);
  const { min, hits } = minTier(files, policy);
  const declared = parseDeclared(argv, ci);

  console.log(`check-tier: ${files.length} changed file(s)`);
  console.log(`  path-derived minimum: ${min}`);
  if (hits.trust.length) {
    console.log(`  trust-critical hits:\n    - ${hits.trust.slice(0, 12).join("\n    - ")}`);
  }
  if (hits.unmatched.length) {
    console.log(`  unmatched (defaulted to semantic):\n    - ${hits.unmatched.slice(0, 12).join("\n    - ")}`);
  }
  if (hits.semantic.length) {
    console.log(`  semantic hits:\n    - ${hits.semantic.slice(0, 12).join("\n    - ")}`);
  }

  if (min === "routine" && (!declared || declared === "routine")) {
    console.log("check-tier OK (routine)");
    return 0;
  }

  if (!declared) {
    // The ack is only valid when a review packet actually exists for the unit.
    // Previously it returned 0 unconditionally, so the strongest floor in the
    // policy was one environment variable away from nothing.
    const queueDir = join(ROOT, ".captain", "review", "queue");
    const hasPacket =
      existsSync(queueDir) && readdirSync(queueDir).some((f) => f.endsWith(".md"));
    if (!ci && min === "trust-critical" && process.env.GILLY_ACK_TRUST === "1" && !hasPacket) {
      console.error(
        "check-tier FAIL: GILLY_ACK_TRUST=1 but .captain/review/queue/ has no review packet.\n" +
          "  Write the packet for this unit before acknowledging a trust-critical change.",
      );
      return 1;
    }
    if (!ci && min === "trust-critical" && process.env.GILLY_ACK_TRUST === "1") {
      // Durable trace — env ack alone used to leave no evidence.
      const logDir = join(ROOT, ".captain", "review");
      const logPath = join(logDir, "loop-log.md");
      mkdirSync(logDir, { recursive: true });
      if (!existsSync(logPath)) {
        appendFileSync(
          logPath,
          "# Review loop log\n\n| Date | Unit / PR | Tier | Reviewers used | Escaped bug? | Fixer regression? | Notes / policy change |\n|---|---|---|---|---|---|---|\n",
        );
      }
      const ts = new Date().toISOString().slice(0, 10);
      const files = hits.trust.slice(0, 8).join(", ");
      appendFileSync(
        logPath,
        `| ${ts} | local ack | trust-critical | GILLY_ACK_TRUST=1 | no | no | ack for: ${files} |\n`,
      );
      console.log(
        `check-tier OK (trust-critical locally acked via GILLY_ACK_TRUST=1; logged to ${logPath})`,
      );
      return 0;
    }
    console.error(
      `check-tier FAIL: path minimum is '${min}' but no tier was declared.\n` +
        (ci
          ? "  Check the matching risk-tier box in the PR template (≥ path minimum)."
          : min === "trust-critical"
            ? "  Re-run with GILLY_ACK_TRUST=1 or --declare=trust-critical (conscious ack)."
            : `  Re-run with --declare=${min} (or higher).`),
    );
    return 1;
  }

  if (!RANK.hasOwnProperty(declared)) {
    console.error(`check-tier FAIL: unknown declared tier '${declared}'`);
    return 1;
  }
  if (RANK[declared] < RANK[min]) {
    console.error(
      `check-tier FAIL: declared '${declared}' is below path-derived minimum '${min}'.\n` +
        "  Raise the PR risk tier (or split the trust-critical files out).",
    );
    return 1;
  }
  console.log(`check-tier OK (declared ${declared} ≥ minimum ${min})`);
  return 0;
}

process.exit(main());
