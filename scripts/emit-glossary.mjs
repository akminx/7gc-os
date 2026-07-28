/**
 * `web/src/labels.ts` → `packages/contracts/glossary.json`.
 *
 * The definitions an auditor reads and the definitions a language model is
 * given must be the same sentences, and there is exactly one place they are
 * written carefully: `labels.ts`. Copying them into Python would create a
 * second wording, and the copy nobody looks at is the one that goes stale —
 * which here means the model restating a finding from a definition the UI no
 * longer agrees with.
 *
 * So this reads the TypeScript and emits JSON. Run with `--check` it emits
 * nothing and fails when the committed JSON has drifted, which is how the gate
 * notices that someone edited a gloss and did not regenerate.
 *
 * Read from the AST rather than by importing the module: `labels.ts` imports
 * types from `./contracts`, so importing it needs a TypeScript runtime, and
 * `new Function` over a source file is the construct `check-web-arch.mjs`
 * exists to refuse. A static read of an object literal cannot execute anything.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const LABELS = join(ROOT, "web", "src", "labels.ts");
const OUT = join(ROOT, "packages", "contracts", "glossary.json");

/** The maps worth exporting: a code an auditor sees, and what it means. */
const WANTED = ["REASON_CODE", "NEXT_ACTION", "REQUIREMENT", "VERDICT", "SHORTFALL_ORIGIN"];

function ts() {
  const dir = join(ROOT, "web", "node_modules", "typescript");
  return require(dir);
}

/** Every string-valued property of an object literal, flattened one level. */
function readObject(t, node) {
  const out = {};
  for (const prop of node.properties ?? []) {
    if (!t.isPropertyAssignment(prop)) continue;
    const key = prop.name.text ?? prop.name.escapedText;
    if (key === undefined) continue;
    const value = prop.initializer;
    if (t.isStringLiteral(value) || t.isNoSubstitutionTemplateLiteral(value)) {
      out[key] = value.text;
    } else if (t.isObjectLiteralExpression(value)) {
      out[key] = readObject(t, value);
    }
    // Anything else — a template with interpolation, a call — is skipped
    // rather than approximated. A gloss this cannot read statically must not
    // arrive in the JSON as a half-rendered string.
  }
  return out;
}

function extract() {
  const t = ts();
  const source = t.createSourceFile(
    "labels.ts",
    readFileSync(LABELS, "utf8"),
    t.ScriptTarget.Latest,
    true,
    t.ScriptKind.TS,
  );
  const found = {};
  const visit = (node) => {
    if (t.isVariableDeclaration(node) && node.name.text && WANTED.includes(node.name.text)) {
      let init = node.initializer;
      // `X: Record<K, Term> = { … }` parses the annotation separately, but a
      // `satisfies` or `as` wrapper would hide the literal one level down.
      while (init && (t.isAsExpression(init) || t.isSatisfiesExpression?.(init))) {
        init = init.expression;
      }
      if (init && t.isObjectLiteralExpression(init)) {
        found[node.name.text] = readObject(t, init);
      }
    }
    t.forEachChild(node, visit);
  };
  visit(source);

  const missing = WANTED.filter((name) => found[name] === undefined);
  if (missing.length > 0) {
    console.error(
      `labels.ts no longer exports readable object literals for: ${missing.join(", ")}`,
    );
    process.exit(1);
  }
  return found;
}

const rendered = `${JSON.stringify(extract(), null, 2)}\n`;

if (process.argv.includes("--check")) {
  let committed = null;
  try {
    committed = readFileSync(OUT, "utf8");
  } catch {
    console.error(`${OUT} is missing — run: node scripts/emit-glossary.mjs`);
    process.exit(1);
  }
  if (committed !== rendered) {
    console.error(
      "packages/contracts/glossary.json is stale: labels.ts has been edited since it was " +
        "generated. The UI and the assistant would be reading different definitions.\n" +
        "  Regenerate with: node scripts/emit-glossary.mjs",
    );
    process.exit(1);
  }
  process.exit(0);
}

writeFileSync(OUT, rendered, "utf8");
console.log(`wrote ${OUT}`);
