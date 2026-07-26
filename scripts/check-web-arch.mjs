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

export function checkWebBoundary(root) {
  const web = join(root, "web");
  if (!existsSync(web)) return ["OK", "no web/ project — §5.3 has nothing to constrain"];

  const tsconfig = join(web, "tsconfig.json");
  const tsDir = join(web, "node_modules", "typescript");
  // A required check that cannot run must FAIL, never SKIP. This project has
  // found six separate checks passing because they measured nothing.
  if (!existsSync(tsconfig)) return ["FAIL", "web/tsconfig.json missing — §5.3 rule cannot run"];
  if (!existsSync(tsDir))
    return ["FAIL", "typescript not installed in web/ — §5.3 rule cannot run (npm ci)"];

  const ts = require(tsDir);
  const raw = ts.readConfigFile(tsconfig, ts.sys.readFile);
  if (raw.error) return ["FAIL", `web/tsconfig.json unreadable: ${raw.error.messageText}`];
  const parsed = ts.parseJsonConfigFileContent(raw.config, ts.sys, web);
  const program = ts.createProgram(parsed.fileNames, parsed.options);
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
  for (const file of program.getSourceFiles()) {
    if (file.isDeclarationFile) continue;
    if (file.fileName.includes(`${sep}node_modules${sep}`)) continue;
    if (!file.fileName.startsWith(web + sep)) continue;
    if (isTestFile(file.fileName)) continue;
    scanned += 1;
    walk(file, file);
  }

  if (scanned === 0)
    return ["FAIL", "§5.3 rule matched no web sources — the check measured nothing"];
  if (violations.length > 0) return ["FAIL", violations.join("\n")];
  return ["OK", `${scanned} web source(s) compute nothing the API owns (SPEC §5.3)`];
}
