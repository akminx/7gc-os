#!/usr/bin/env node
// Run an adversarial review pass in a non-Anthropic family and record provenance.
//
//   node scripts/adversary.mjs schema-passB --prompt semantic-adversary.md --model grok
//
// Why this exists
// ---------------
// The two-pane review loop works because Pass B runs in a different model
// family than the author. Manually, "which pane" and "which family" are the
// same fact, so it is hard to get wrong. Automating the invocation breaks that:
// the author now picks the model, runs the tool, and reads the result, and the
// only remaining signal is a line of prose the model writes about itself.
//
// A self-report cannot catch the failure that matters. If --model silently
// falls back — unavailable, quota, a typo in the model string — the run still
// emits a findings file that looks exactly like a valid one. It fails open and
// it fails green, which is the same shape as a glob engine that matches nothing
// or a health check that never reaches its database.
//
// So this script trusts the CLI's own metadata, never the model's claim about
// itself, and refuses to write findings when provenance cannot be established.
// A pass that cannot prove its family is not a pass.

import { spawnSync } from "node:child_process";
import { appendFileSync, existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const ROOT = spawnSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).stdout.trim();
const QUEUE = join(ROOT, ".captain", "review", "queue");
const PROMPTS = join(ROOT, ".captain", "review", "prompts");
const LOG = join(ROOT, ".captain", "review", "loop-log.md");

// Substrings that mean "this is the author's own family". Matched against the
// model identifier the CLI reports, not against anything the model says.
const ANTHROPIC = /claude|anthropic|opus|sonnet|haiku/i;

// Family-neutral aliases resolve server-side to whatever the account defaults
// to — possibly a Claude model. They are not Anthropic *strings*, so the filter
// above passes them, and if the session store is unavailable the recorded
// provenance is just the alias. A Pass B that actually ran on Claude would then
// look provenance-clean, which is the precise false green this script exists to
// prevent. Only concrete model ids count.
const ALIAS = /^(auto|default|composer[\w.-]*)$/i;

// A family we can positively identify. An id matching none of these is unknown,
// and unknown must refuse rather than be assumed foreign.
//
// Token-anchored, not substring: a bare /sol/ also matches "absolute",
// "resolution" and "console", so a made-up id like `console-ai` would have been
// certified as proven foreign. The o-series is listed explicitly because
// `o3`/`o4-mini` are genuinely foreign and matched nothing before — a false red
// is less dangerous than a false green, but it still breaks the tool.
const FAMILY_TOKENS =
  "gpt|grok|gemini|sol|terra|codex|llama|mistral|qwen|deepseek|kimi|glm|o[1345]";
const KNOWN_FOREIGN = new RegExp(`(^|[-_/. ])(${FAMILY_TOKENS})([-_/. \\d]|$)`, "i");

function die(msg) {
  console.error(`\n✗ ${msg}\n`);
  process.exit(1);
}

function arg(flag, fallback = null) {
  const i = process.argv.indexOf(flag);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

/**
 * Second, independent provenance source: Cursor's own session store.
 *
 * Every assistant message it writes carries
 * `providerOptions.cursor.modelName`. This is recorded by the client for its
 * own purposes, not for us, which is exactly what makes it useful — it is not a
 * field the reviewing model can influence. Cross-checking the stream against it
 * means a single misreported field cannot fake a family.
 */
function modelsFromSessionStore(sessionId) {
  const chats = join(homedir(), ".cursor", "chats");
  if (!sessionId || !existsSync(chats)) return [];
  for (const bucket of readdirSync(chats)) {
    const db = join(chats, bucket, sessionId, "store.db");
    if (!existsSync(db)) continue;
    const blob = readFileSync(db, "latin1");
    const found = new Set();
    for (const m of blob.matchAll(/"modelName"\s*:\s*"([^"]+)"/g)) found.add(m[1]);
    return [...found];
  }
  return [];
}

/** Find every value under a "model"-ish key, at any depth, in the CLI's JSON. */
function modelsIn(node, found = new Set()) {
  if (node === null || typeof node !== "object") return found;
  if (Array.isArray(node)) {
    for (const v of node) modelsIn(v, found);
    return found;
  }
  for (const [k, v] of Object.entries(node)) {
    if (/^model(_?name|_?id)?$/i.test(k) && typeof v === "string" && v.trim()) found.add(v.trim());
    else modelsIn(v, found);
  }
  return found;
}

/** The assistant's prose, wherever the CLI put it. */
function textIn(node, parts = []) {
  if (node === null || typeof node !== "object") return parts;
  if (Array.isArray(node)) {
    for (const v of node) textIn(v, parts);
    return parts;
  }
  for (const [k, v] of Object.entries(node)) {
    if ((k === "text" || k === "content" || k === "result") && typeof v === "string") parts.push(v);
    else textIn(v, parts);
  }
  return parts;
}

const unit = process.argv[2];
if (!unit || unit.startsWith("--"))
  die("usage: adversary.mjs <unit>-<pass> --prompt <f> --model <m>");

const model = arg("--model");
if (!model) die("--model is required; a default would hide which family actually ran");
if (ANTHROPIC.test(model)) {
  die(
    `refusing to run: "${model}" is the author's own family.\n` +
      `  Pass B exists to produce an uncorrelated sample. Running it on the\n` +
      `  author's family turns two independent reviews into one and reports green.`,
  );
}
if (ALIAS.test(model)) {
  die(
    `refusing to run: "${model}" is a server-resolved alias, not a model.\n` +
      `  It can resolve to a Claude model while the recorded provenance still\n` +
      `  reads "${model}". Name the concrete model id instead.`,
  );
}
if (!KNOWN_FOREIGN.test(model)) {
  die(
    `refusing to run: "${model}" is not a recognised non-Anthropic model.\n` +
      `  An unrecognised id cannot be shown to be a different family, and an\n` +
      `  unverifiable pass looks identical to a verified one.`,
  );
}

const promptFile = join(PROMPTS, arg("--prompt", "semantic-adversary.md"));
const packet = join(QUEUE, `${unit}.md`);
for (const f of [promptFile, packet]) if (!existsSync(f)) die(`missing input: ${f}`);

const findingsPath = join(QUEUE, `${unit}.findings.md`);
const provPath = join(QUEUE, `${unit}.provenance.json`);
const rawPath = join(QUEUE, `${unit}.raw.json`);

// The packet is the only input. Passing the prompt and packet by path (rather
// than pasting prior context) is what keeps Pass B blind to Pass A.
const instruction =
  `Read @${promptFile} and follow it exactly.\n` +
  `The unit under review is described in @${packet}. That packet is your only brief.\n` +
  `Read whatever repository files the packet points you at.\n` +
  `Write your findings as markdown to your final message. Do not edit any file.`;

console.log(`\nadversary pass · ${unit}`);
console.log(`  prompt   ${arg("--prompt", "semantic-adversary.md")}`);
console.log(`  model    ${model}  (requested)`);
console.log(`  packet   ${packet}`);
console.log(`\nrunning — this reads the repo and can take several minutes…\n`);

const started = new Date().toISOString();
const r = spawnSync(
  "cursor-agent",
  // stream-json, not json: only the streaming format emits the `system`/`init`
  // event carrying the model the CLI actually resolved. Plain `json` returns
  // the result text and token usage with no model field at all, which would
  // leave the self-report as the only signal — the exact thing this avoids.
  //
  // --trust skips the workspace-trust prompt so the run is non-interactive.
  //
  // --plan blocks Shell outright, so a reviewer in plan mode can only reason
  // from source: it cannot run the tests or probe the database. That produced a
  // verdict explicitly caveated as "not independently re-run", which is weaker
  // than the review was asked for. --shell trades containment for evidence.
  // Check `git status` after using it — --plan did not reliably prevent writes
  // either, since a prior run left a probe script behind through a subagent.
  [
    "--print",
    "--output-format",
    "stream-json",
    process.argv.includes("--shell") ? "--force" : "--plan",
    "--trust",
    "--model",
    model,
    instruction,
  ],
  { cwd: ROOT, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
);

if (r.error) die(`cursor-agent failed to start: ${r.error.message}`);
writeFileSync(rawPath, r.stdout || "");
if (r.status !== 0) die(`cursor-agent exited ${r.status}\n${(r.stderr || "").slice(-2000)}`);

const events = [];
for (const line of (r.stdout || "").split("\n")) {
  const t = line.trim();
  if (!t) continue;
  try {
    events.push(JSON.parse(t));
  } catch {
    /* partial line — the result event is what matters and arrives whole */
  }
}
if (!events.length) {
  die(
    `cursor-agent produced no parseable events. Raw output kept at ${rawPath}\n` +
      `  Provenance cannot be established, so no findings were written.`,
  );
}

const sessionId = events.find((e) => e.session_id)?.session_id ?? null;
const streamModels = [...modelsIn(events.filter((e) => e.type === "system"))];
const storeModels = modelsFromSessionStore(sessionId);
const models = [...new Set([...streamModels, ...storeModels])];

if (models.length === 0) {
  die(
    `neither the event stream nor the session store names a model.\n` +
      `  Raw output kept at ${rawPath}\n` +
      `  Refusing to write findings: an unverifiable pass is worse than no pass,\n` +
      `  because it looks identical to a verified one.`,
  );
}

// Provenance must positively identify a foreign family, not merely fail to
// contain an Anthropic substring. An alias echoed back by the stream proves
// nothing about what actually ran.
const aliasOnly = models.every((m) => ALIAS.test(m) || !KNOWN_FOREIGN.test(m));
if (aliasOnly) {
  die(
    `the run reports only unresolved model identifiers: ${models.join(", ")}\n` +
      `  Raw output kept at ${rawPath}\n` +
      `  Refusing to write findings: this cannot be shown to be a cross-family pass.`,
  );
}

const anthropic = models.filter((m) => ANTHROPIC.test(m));
if (anthropic.length) {
  die(
    `MIS-ROUTED PASS — the CLI reports it ran on: ${anthropic.join(", ")}\n` +
      `  Requested "${model}". No findings written. Re-run on a non-Anthropic model.`,
  );
}

// In --plan mode the deliverable is routed into a PLAN artifact, not the
// assistant message, and `result.result` holds only the narration. Reading just
// the result made a complete verdict look like a review that had failed to run.
// The plan wins when present, because that is where the reviewer put its work.
const plan = events
  .filter((e) => e.type === "interaction_query" && e.subtype === "request")
  .map((e) => e.query?.createPlanRequestQuery?.args?.plan)
  .filter(Boolean)
  .pop();
const result = events.find((e) => e.type === "result");
const body = (
  plan ??
  result?.result ??
  textIn(events.filter((e) => e.type === "assistant")).join("\n\n")
).trim();
if (!body) die(`no assistant text in the response. Raw output kept at ${rawPath}`);

// The model's own claim, kept for comparison — never used as the check.
const claim = (body.match(/^Model family used:\s*(.+)$/im) || [])[1]?.trim() ?? null;

writeFileSync(findingsPath, body.endsWith("\n") ? body : `${body}\n`);
writeFileSync(
  provPath,
  `${JSON.stringify(
    {
      unit,
      prompt: arg("--prompt", "semantic-adversary.md"),
      requested_model: model,
      // Authoritative: what the CLI and its session store say ran, never what
      // the model says it is. Two independent sources; both must be clean.
      reported_models: models,
      stream_models: streamModels,
      session_store_models: storeModels,
      self_reported_family: claim,
      session_id: sessionId,
      packet,
      started,
      finished: new Date().toISOString(),
      cursor_agent_version: spawnSync("cursor-agent", ["--version"], {
        encoding: "utf8",
      }).stdout.trim(),
    },
    null,
    2,
  )}\n`,
);

// Append-only. Once the author can invoke the adversary, the author can also
// re-run until the verdict is agreeable. Every attempt lands here so that
// re-rolling is visible rather than silent.
appendFileSync(
  LOG,
  `\n- ${started} · ${unit} · requested \`${model}\` · ran \`${models.join(", ")}\`` +
    `${claim ? ` · self-reported \`${claim}\`` : ""}\n`,
);

const mismatch = claim && !models.some((m) => m.toLowerCase().includes(claim.toLowerCase()));
console.log(`✓ findings    ${findingsPath}`);
console.log(`✓ provenance  ${provPath}   ran: ${models.join(", ")}`);
if (mismatch) {
  console.log(`\n!  self-report "${claim}" does not obviously match ${models.join(", ")}.`);
  console.log(`   The CLI metadata governs; read the findings with that in mind.`);
}
console.log();
