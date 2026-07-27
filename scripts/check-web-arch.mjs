// SPEC §5.3 · the `web/**` boundary, enforced.
//
// "The API supplies every numeric value, aggregate, percentage, support status
// and reason code. `web/**` may apply value-preserving locale formatting and
// display ordering. It may not add, subtract, multiply, divide, round a
// canonical value, derive a percentage or status, choose policy precedence, or
// aggregate rows. Arch-lint forbids those operations on contract numeric
// fields. This is what keeps `web/**` honestly `routine`."
//
// That last sentence was the justification for the whole frontend sitting at
// the `routine` tier — the tier that needs no human review — and no such
// arch-lint existed. `scripts/arch_checks.py` had one live rule, scoped to
// `("ingest", "packages", "api", "evals")` and `.py`; the two `web` blocks
// beside it were commented-out templates. A probe that subtracted two canonical
// counts, derived a ratio through `Number()`, and aggregated rows through
// `Number.parseFloat` passed both gates green.
//
// PARSED, NOT GREPPED, and this is not a preference. `format.ts` explains at
// length why it avoids `Number(amount)` and states that "`parseFloat` appears
// nowhere in this file" — a regex over lines flags the file's own account of
// why it is clean, and the obvious repair (reword the prose) puts the guard at
// the mercy of how the next person writes a comment. `arch_checks.py` learned
// this on the Python side and says so; this is the same lesson, ported.
//
// TYPED, not just syntactic. `a - b` is forbidden on two canonical counts and
// unremarkable on two array indices, and only the type distinguishes them. So
// this builds a real `ts.Program` and asks the checker whether an operand is
// numeric, rather than banning a character.
//
// What it does NOT cover, stated so the green line is not read as more than it
// is: comparisons (`>`, `===`) are allowed, because ordering a display is
// explicitly permitted; `.length` is allowed, because "render a note when the
// list is empty" is not a derived figure; and a value laundered through a
// helper this file cannot see — `JSON.parse`, a `new Function`, an imported
// npm package — is out of reach of any static rule. Test files are exempt for
// the same reason `arch_checks.py` exempts them: they construct forbidden
// values deliberately, to prove the guards refuse them.

import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { join, relative, sep } from "node:path";

const require = createRequire(import.meta.url);

//: Turning a canonical decimal STRING into a float. `Money.amount` is typed
//: `string` precisely so this has to be written out loud; this is the rule that
//: makes writing it out loud fail.
const COERCIONS = new Set(["Number", "parseInt", "parseFloat", "BigInt"]);

//: Reducing many rows to one value or one status. `map`, `filter`, `find` and
//: `flatMap` are absent deliberately — selecting and ordering rows for display
//: is the permitted half of §5.3.
const AGGREGATORS = new Set(["reduce", "reduceRight", "every", "some"]);

//: Rounding a canonical value on the way to the screen.
const ROUNDERS = new Set(["toFixed", "toPrecision", "toExponential"]);

function isTestFile(file) {
  return /\.test\.tsx?$/.test(file);
}

//: Both rules in this file need a real `ts.Program` over `web/**`, and both
//: must FAIL rather than SKIP when they cannot build one. Returns either
//: `{ stop }` — the tuple the caller should return verbatim — or the program.
function loadWebProgram(root, rule) {
  const web = join(root, "web");
  if (!existsSync(web))
    return { stop: ["OK", `no web/ project — ${rule} has nothing to constrain`] };

  const tsconfig = join(web, "tsconfig.json");
  const tsDir = join(web, "node_modules", "typescript");
  // A required check that cannot run must FAIL, never SKIP. This project has
  // found six separate checks passing because they measured nothing.
  if (!existsSync(tsconfig))
    return { stop: ["FAIL", `web/tsconfig.json missing — ${rule} cannot run`] };
  if (!existsSync(tsDir))
    return { stop: ["FAIL", `typescript not installed in web/ — ${rule} cannot run (npm ci)`] };

  const ts = require(tsDir);
  const raw = ts.readConfigFile(tsconfig, ts.sys.readFile);
  if (raw.error)
    return { stop: ["FAIL", `web/tsconfig.json unreadable: ${raw.error.messageText}`] };
  const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, web);
  return { ts, web, program: ts.createProgram(parsed.fileNames, parsed.options) };
}

//: Every source under `web/**` that is not a declaration file, a dependency or
//: a test. Tests are exempt for the reason `arch_checks.py` exempts them: they
//: construct forbidden values deliberately, to prove the guards refuse them.
function* webSources({ web, program }) {
  for (const file of program.getSourceFiles()) {
    if (file.isDeclarationFile) continue;
    if (file.fileName.includes(`${sep}node_modules${sep}`)) continue;
    if (!file.fileName.startsWith(web + sep)) continue;
    if (isTestFile(file.fileName)) continue;
    yield file;
  }
}

export function checkWebBoundary(root) {
  const loaded = loadWebProgram(root, "§5.3");
  if (loaded.stop) return loaded.stop;
  const { ts, program } = loaded;
  const checker = program.getTypeChecker();

  const ARITHMETIC = new Map([
    [ts.SyntaxKind.PlusToken, "+"],
    [ts.SyntaxKind.MinusToken, "-"],
    [ts.SyntaxKind.AsteriskToken, "*"],
    [ts.SyntaxKind.SlashToken, "/"],
    [ts.SyntaxKind.PercentToken, "%"],
    [ts.SyntaxKind.AsteriskAsteriskToken, "**"],
    [ts.SyntaxKind.PlusEqualsToken, "+="],
    [ts.SyntaxKind.MinusEqualsToken, "-="],
    [ts.SyntaxKind.AsteriskEqualsToken, "*="],
    [ts.SyntaxKind.SlashEqualsToken, "/="],
    [ts.SyntaxKind.PercentEqualsToken, "%="],
    [ts.SyntaxKind.AsteriskAsteriskEqualsToken, "**="],
  ]);

  const numeric = (type) => {
    if (type === undefined) return false;
    if (type.isUnion?.()) return type.types.some(numeric);
    return Boolean(type.flags & (ts.TypeFlags.NumberLike | ts.TypeFlags.BigIntLike));
  };
  const numericAt = (node) => {
    try {
      return numeric(checker.getTypeAtLocation(node));
    } catch {
      // An unresolvable node is reported, not waved through: a rule that treats
      // "I could not tell" as "allowed" is how the hole gets reopened.
      return true;
    }
  };

  const violations = [];
  const walk = (node, file) => {
    const at = (what) => {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
      violations.push(`${relative(root, file.fileName)}:${line + 1} ${what}`);
    };

    if (ts.isBinaryExpression(node) && ARITHMETIC.has(node.operatorToken.kind)) {
      const op = ARITHMETIC.get(node.operatorToken.kind);
      // `"a" + b` is string building and stays legal; `count + count` is an
      // aggregate the API owns. Only the operand types tell them apart.
      if (numericAt(node.left) || numericAt(node.right))
        at(`computes \`${op}\` on a numeric value the API owns (SPEC §5.3)`);
    } else if (
      (ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
      (node.operator === ts.SyntaxKind.PlusPlusToken ||
        node.operator === ts.SyntaxKind.MinusMinusToken)
    ) {
      at("increments a numeric value in the display layer (SPEC §5.3)");
    } else if (
      ts.isPrefixUnaryExpression(node) &&
      node.operator === ts.SyntaxKind.PlusToken &&
      !ts.isNumericLiteral(node.operand)
    ) {
      at("coerces to number with unary `+` (SPEC §5.3)");
    } else if (
      ts.isNewExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      ts.isIdentifier(node.expression.expression) &&
      node.expression.expression.text === "Intl" &&
      node.expression.name.text === "NumberFormat"
    ) {
      // `new Intl.NumberFormat(...)` reaches `.format()` as a NewExpression, not
      // a call on an identifier, so the branch below never sees it. Left out, the
      // rule caught `Intl` only when a `Number()` happened to sit beside it.
      at("constructs `Intl.NumberFormat`, which formats a float (SPEC §5.3)");
    } else if (ts.isCallExpression(node)) {
      const callee = node.expression;
      if (ts.isIdentifier(callee) && COERCIONS.has(callee.text))
        at(`calls \`${callee.text}()\` on a canonical value (SPEC §5.3)`);
      else if (ts.isPropertyAccessExpression(callee)) {
        const name = callee.name.text;
        const owner = callee.expression;
        if (AGGREGATORS.has(name))
          at(`aggregates rows with \`.${name}()\` — the API owns aggregates (SPEC §5.3)`);
        else if (ROUNDERS.has(name)) at(`rounds a value with \`.${name}()\` (SPEC §5.3)`);
        else if (
          ts.isIdentifier(owner) &&
          (owner.text === "Math" || (owner.text === "Number" && COERCIONS.has(name)))
        )
          at(`calls \`${owner.text}.${name}()\` on a canonical value (SPEC §5.3)`);
        else if (ts.isIdentifier(owner) && owner.text === "Intl" && name === "NumberFormat")
          at("formats through `Intl.NumberFormat`, which parses a float first (SPEC §5.3)");
      }
    }
    ts.forEachChild(node, (child) => {
      walk(child, file);
    });
  };

  let scanned = 0;
  for (const file of webSources(loaded)) {
    scanned += 1;
    walk(file, file);
  }

  if (scanned === 0)
    return ["FAIL", "§5.3 rule matched no web sources — the check measured nothing"];
  if (violations.length > 0) return ["FAIL", violations.join("\n")];
  return ["OK", `${scanned} web source(s) compute nothing the API owns (SPEC §5.3)`];
}

//: The repository's private vocabulary, in text a reader can see.
//:
//: `INV-17` and `SPEC §6.3` are how THIS PROJECT refers to its own decisions.
//: An auditor has no copy of `INVARIANTS.md`, so on screen they are a citation
//: to a document the reader does not have — which reads as authority without
//: supplying any. The rule was stated in CLAUDE.md and nothing checked it, so
//: five leaked into shipped copy in one night: two tooltips, two constants
//: rendered by `Why`, and one reason-code gloss. `Why` puts its text in the
//: expanded body, in the `title` AND in a visually-hidden span, so a screen
//: reader says "INV-17" out loud.
//:
//: The sentences were all worth saying. Only the citation had to go, and every
//: repair was to delete the reference and keep the sentence.
const INTERNAL_VOCABULARY = /\bINV-\d+|\bSPEC\s*§/;

//: Every violation in one parsed source. Split out from the check so the
//: self-test below can run the REAL rule over a synthetic file, rather than a
//: copy of it that can drift.
//:
//: PARSED, NOT GREPPED, and here the reason is sharper than it is for §5.3:
//: this very file, `INVARIANTS.md` and the comments in `labels.ts` all discuss
//: `INV-` by name. A line-wise regex over `web/**` flags the prose that
//: explains the rule, and the obvious repair — reword the comment — puts the
//: guard at the mercy of how the next person writes English. The AST carries no
//: comments, so only text that can actually reach a reader is examined.
function vocabularyViolations(ts, file, name) {
  const found = [];
  const walk = (node) => {
    const speakable =
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      // JSX children are not string literals. Copy written directly between
      // tags — <p>INV-17 means…</p> — is the most obvious way to leak one and
      // the easiest kind of node to forget.
      ts.isJsxText(node);
    if (speakable && INTERNAL_VOCABULARY.test(node.text)) {
      const { line } = file.getLineAndCharacterOfPosition(node.getStart(file));
      found.push(
        `${name}:${line + 1} says \`${node.text.match(INTERNAL_VOCABULARY)[0]}\`` +
          " in text a reader can see — name the idea, not the invariant",
      );
    }
    ts.forEachChild(node, walk);
  };
  walk(file);
  return found;
}

//: A source that MUST be rejected, and the one construct that must not be.
//:
//: Green on a clean tree proves nothing — that is this project's most repeated
//: finding, and `scripts/test_tier_map.mjs` is a guard-on-a-guard that nothing
//: invokes. So the rule is run against this before it is trusted against
//: `web/**`, in memory, on every gate run.
//:
//: The comment is the control. It names both tokens, and a regex over lines
//: would fail this fixture — which is precisely the implementation the rule
//: must not drift back into.
const PROBE = `
// A comment naming INV-17 and SPEC §6.3 must NOT be flagged.
const TOOLTIP = "a valuation-policy act (INV-17)";
const TEMPLATED = \`bound per SPEC §6.3 to a mark revision\`;
export function Probe({ n }: { n: number }) {
  return <div title={TOOLTIP} data-t={TEMPLATED}>INV-9 says a gap is immutable. {n}</div>;
}
`;

//: Line 3 is the string literal, 4 the no-substitution template, 6 the JSX
//: text — one per node kind the rule claims to cover. Line 2, the comment, must
//: be absent.
//:
//: Asserted as the exact SET rather than as a count. A count catches a kind
//: that stopped being examined but not a kind that started matching the wrong
//: node, and "3 of something" passing while the something changed is the shape
//: of every vacuous check this project has found.
const PROBE_EXPECTS = [3, 4, 6];

function selfTest(ts) {
  const file = ts.createSourceFile(
    "probe.tsx",
    PROBE,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const lines = vocabularyViolations(ts, file, "probe.tsx")
    .map((v) => Number(v.match(/^probe\.tsx:(\d+)/)[1]))
    .sort((a, b) => a - b);
  if (String(lines) !== String(PROBE_EXPECTS))
    return (
      `self-test: planted violations on lines ${PROBE_EXPECTS}, rule reported ${lines.length ? lines : "none"}` +
      " — it does not catch what it claims to, so its green line means nothing"
    );
  return null;
}

export function checkUiVocabulary(root) {
  const loaded = loadWebProgram(root, "the UI-vocabulary rule");
  if (loaded.stop) return loaded.stop;
  const { ts } = loaded;

  const broken = selfTest(ts);
  if (broken) return ["FAIL", broken];

  const violations = [];
  let scanned = 0;
  for (const file of webSources(loaded)) {
    scanned += 1;
    violations.push(...vocabularyViolations(ts, file, relative(root, file.fileName)));
  }

  if (scanned === 0)
    return ["FAIL", "UI-vocabulary rule matched no web sources — the check measured nothing"];
  if (violations.length > 0) return ["FAIL", violations.join("\n")];
  return ["OK", `${scanned} web source(s) cite no INV- or SPEC § in visible text (self-test: 3/3)`];
}
