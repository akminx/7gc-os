#!/usr/bin/env node
// The guard on the guard (SPEC §5.4).
//
// Asserts that every real repo path resolves to its INTENDED tier. Without
// this, SPEC §5.2 is a comment: a dead glob, a renamed directory or a
// regression in the glob engine would pass silently — and did, for the whole
// design phase, because `**/x/**` cannot match a top-level `x/`.
import { execFileSync } from "node:child_process";

const CASES = [
  // trust-critical — anything producing or attesting to a reported figure
  ["policy/sufficiency_matrix.py", "trust-critical"],
  ["policy/validators/fx.py", "trust-critical"],
  ["packet/export.py", "trust-critical"],
  ["packet/manifest.py", "trust-critical"],
  ["ingest/trackers/valuation_tracker.py", "trust-critical"],
  ["evidence/retrieval.py", "trust-critical"],
  ["evidence/extract.py", "trust-critical"],
  ["packages/contracts/models.py", "trust-critical"],
  ["supabase/migrations/0001_init.sql", "trust-critical"],
  ["evals/oracle/derive.py", "trust-critical"],
  ["evals/oracle/primitives.yaml", "trust-critical"],
  // semantic
  ["ingest/documents/parse.py", "semantic"],
  ["api/orchestrator.py", "semantic"],
  ["evals/graders.py", "semantic"],
  ["scripts/check-tier.mjs", "semantic"],
  // routine
  ["web/src/Dashboard.tsx", "routine"],
  ["docs/SPEC.md", "routine"],
  ["README.md", "routine"],
  // default-deny: unmatched must NOT be routine
  ["some_new_module/thing.py", "semantic"],
  ["valuation.py", "semantic"],
];

let failed = 0;
for (const [path, want] of CASES) {
  const out = execFileSync("node", ["scripts/check-tier.mjs", "--print-tier", path], {
    encoding: "utf8",
  }).trim();
  const ok = out === want;
  if (!ok) failed++;
  console.log(`  ${ok ? "ok  " : "FAIL"} ${path.padEnd(38)} ${out}${ok ? "" : `  (want ${want})`}`);
}
console.log(failed ? `\n${failed} tier-map failure(s)` : "\nAll tier-map cases pass.");
process.exit(failed ? 1 : 0);
