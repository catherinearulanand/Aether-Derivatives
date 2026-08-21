/**
 * Prove the assistant cannot disagree with the screens.
 *
 * AETHER's whole argument is that one number is traceable end to end. An assistant
 * that answered "the collateral requirement is X" while the dashboard displayed Y
 * would destroy that argument more effectively than any missing feature.
 *
 * So this script runs the **shipped** retrieval layer — `frontend/src/lib/assistant.ts`,
 * the exact module the floating assistant imports — against a live API response,
 * and asserts that every figure it returns is character-for-character a value the
 * engine put in that response. Not "close to", not "derived from": the same string.
 *
 * It also checks the two refusals that matter:
 *
 * - a question the retrieval layer does not cover returns ``UNKNOWN`` rather than a
 *   confident paragraph;
 * - a question needing a permission the role lacks returns ``NOT_PERMITTED``.
 *
 * .. rubric:: Running it
 *
 * The API must be up::
 *
 *     python -m uvicorn aether.api.main:app --port 8000
 *     node scripts/verify_assistant.mjs
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FRONTEND = join(ROOT, "frontend");
const API = process.env.AETHER_API ?? "http://127.0.0.1:8000";

function compileAssistant() {
  const out = mkdtempSync(join(tmpdir(), "aether-assistant-"));
  execFileSync(
    process.execPath,
    [
      join(FRONTEND, "node_modules", "typescript", "bin", "tsc"),
      join("src", "lib", "assistant.ts"),
      "--outDir",
      out,
      "--module",
      "esnext",
      "--target",
      "es2020",
      "--moduleResolution",
      "bundler",
      "--skipLibCheck",
    ],
    { cwd: FRONTEND, stdio: "pipe" },
  );

  // tsc emits the extensionless specifiers the sources use; Node's ESM loader
  // requires the extension. Rewriting the emitted files keeps
  // `allowImportingTsExtensions` out of the application's tsconfig.
  for (const name of readdirSync(out)) {
    if (!name.endsWith(".js")) continue;
    const path = join(out, name);
    writeFileSync(
      path,
      readFileSync(path, "utf8").replace(
        /from "(\.\/[^"]+)"/g,
        (match, specifier) => (specifier.endsWith(".js") ? match : `from "${specifier}.js"`),
      ),
    );
  }
  return out;
}

/**
 * Every monetary string the engine put in this response.
 *
 * Walked rather than enumerated, so a retriever reaching a field this script did
 * not think of is still covered.
 */
function engineFigures(node, into = new Set()) {
  if (node === null || typeof node !== "object") return into;
  if (Array.isArray(node)) {
    for (const item of node) engineFigures(item, into);
    return into;
  }
  if (typeof node.amount === "string" && typeof node.currency === "string") {
    into.add(`${node.currency} ${node.amount}`);
  }
  for (const value of Object.values(node)) engineFigures(value, into);
  return into;
}

const MONEY = /\b([A-Z]{3}) (-?\d+\.\d{2})\b/g;

const compiled = compileAssistant();
let failed = false;

try {
  const { ask, SUGGESTIONS } = await import(
    pathToFileURL(join(compiled, "assistant.js")).href
  );

  const run = await fetch(`${API}/api/v1/scenarios/stress/run`, { method: "POST" }).then(
    (r) => r.json(),
  );
  const comparison = await fetch(`${API}/api/v1/comparison/base/stress`).then((r) =>
    r.json(),
  );

  const truth = engineFigures(run);
  engineFigures(comparison, truth);

  const context = {
    run,
    comparison,
    role: "RISK",
    scenarioName: "Rate shock",
    baselineName: "Quiet market",
  };

  const failures = [];
  let checked = 0;
  let figuresVerified = 0;

  console.log("  AETHER assistant — figures vs the engine's own response");
  console.log("  " + "-".repeat(58));

  for (const question of SUGGESTIONS) {
    const answer = ask(question, context);
    checked += 1;

    if (answer.status !== "ANSWERED") {
      failures.push(`"${question}" returned ${answer.status}, expected ANSWERED`);
      continue;
    }

    // Every money-shaped string, in the prose and in the fields alike, must be a
    // figure the engine emitted in this very response.
    const text = [answer.text, ...answer.fields.map((f) => `${f.label} ${f.value}`)].join(
      "  ",
    );
    for (const [, currency, amount] of text.matchAll(MONEY)) {
      const figure = `${currency} ${amount}`;
      if (truth.has(figure)) figuresVerified += 1;
      else failures.push(`"${question}" cited ${figure}, which the engine did not return`);
    }

    if (!answer.source || answer.source === "—") {
      failures.push(`"${question}" answered without naming the panel it came from`);
    }
    if (answer.paths.length === 0) {
      failures.push(`"${question}" answered without declaring the fields it read`);
    }

    console.log(
      `  ✓ ${question.padEnd(46)} ${String(answer.fields.length).padStart(2)} fields  ` +
        `from ${answer.source}`,
    );
  }

  // The refusals.
  const nonsense = ask("What will the market do next week?", context);
  checked += 1;
  if (nonsense.status !== "UNKNOWN") {
    failures.push(
      `An unsupported question returned ${nonsense.status} rather than UNKNOWN. ` +
        "The assistant must decline, not improvise.",
    );
  } else if (nonsense.fields.length > 0) {
    failures.push("An unsupported question returned figures alongside its refusal.");
  } else {
    console.log(`  ✓ ${"declines what it does not hold".padEnd(46)} UNKNOWN`);
  }

  const forbidden = ask(
    "What terms did the agent extract from the CSA?",
    { ...context, role: "RISK" },
  );
  const auditorOnDesk = ask("Why was this collateral selected?", {
    ...context,
    role: "AUDITOR",
  });
  checked += 2;
  if (forbidden.status !== "ANSWERED") {
    failures.push("RISK holds view:contract and should have been answered.");
  }
  if (auditorOnDesk.status !== "ANSWERED") {
    failures.push("AUDITOR holds view:desk and should have been answered.");
  }

  const noRole = ask("Is the audit chain verified?", { ...context, role: null });
  checked += 1;
  if (noRole.status !== "NOT_PERMITTED") {
    failures.push(
      `A question asked with no role returned ${noRole.status} rather than NOT_PERMITTED.`,
    );
  } else {
    console.log(`  ✓ ${"refuses without a role".padEnd(46)} NOT_PERMITTED`);
  }

  console.log("");
  console.log(`  questions exercised       ${checked}`);
  console.log(`  figures cross-checked     ${figuresVerified}`);
  console.log(`  engine figures available  ${truth.size}`);
  console.log(`  discrepancies             ${failures.length}`);

  if (failures.length > 0) {
    console.log("");
    console.log("  FAILURES");
    for (const failure of failures) console.log(`    ${failure}`);
    failed = true;
  } else {
    console.log("");
    console.log("  PASS — every figure the assistant quoted is a string the engine");
    console.log("         returned in the same response the screens render.");
  }
} catch (error) {
  console.error(`  Could not run: ${error.message}`);
  console.error(`  Is the API up at ${API}?`);
  failed = true;
} finally {
  rmSync(compiled, { recursive: true, force: true });
}

process.exit(failed ? 1 : 0);
