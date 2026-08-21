/**
 * Score the reconciliation classifier against the dataset's answer key.
 *
 * `scripts/generate_reconciliation_data.py` builds two CSVs by injecting a known,
 * enumerated set of differences and writes every one of them to
 * `injection_manifest.json`. This script runs the **shipped** classifier —
 * `frontend/src/lib/reconcile.ts`, the exact module the reconciliation screen
 * imports — over those files and checks what it found against what was injected.
 *
 * That combination is what makes the dataset a benchmark rather than a demo prop:
 * a missed break and a false positive are both measurable, and neither can hide.
 *
 * .. rubric:: What counts as correct
 *
 * Each injection class maps to the status a correct classifier must return.
 * ``STALE_PRICE`` accepts more than one, because a prior-day price may or may not
 * move a given asset beyond the tolerance — the ambiguity is real and the
 * classifier is not asked to resolve it, only to surface the evidence.
 *
 * A misdirected booking must produce **two** rows: the expected account short, and
 * the receiving account holding something the ledger does not know about. A
 * classifier that nets those into one matched row has hidden the finding, so the
 * pair is asserted explicitly.
 *
 * .. rubric:: Running it
 *
 * No new dependency: the two modules under test are pure and are compiled with the
 * frontend's own TypeScript.
 *
 *     node scripts/verify_reconciliation.mjs
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURES = join(ROOT, "fixtures", "reconciliation");
const FRONTEND = join(ROOT, "frontend");

/** Compile the two pure modules to JS in a temporary directory. */
function compileClassifier() {
  const out = mkdtempSync(join(tmpdir(), "aether-recon-"));
  // Node runs TypeScript's own entry point directly. Going through `npx` would
  // mean spawning a shell wrapper, which behaves differently on Windows and is an
  // extra failure mode for no benefit.
  execFileSync(
    process.execPath,
    [
      join(FRONTEND, "node_modules", "typescript", "bin", "tsc"),
      join("src", "lib", "decimal.ts"),
      join("src", "lib", "reconcile.ts"),
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

  // tsc emits the extensionless specifier the source uses; Node's ESM loader
  // requires the extension. Rewriting it here keeps `allowImportingTsExtensions`
  // out of the application's tsconfig for the sake of one script.
  const path = join(out, "reconcile.js");
  writeFileSync(path, readFileSync(path, "utf8").replace('from "./decimal"', 'from "./decimal.js"'));
  return out;
}

/** Minimal CSV reader: quoted fields, `#` banner lines skipped. */
function parseCsv(text) {
  const lines = text
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .filter((line) => line.trim() && !line.startsWith("#"));

  const split = (line) => {
    const fields = [];
    let field = "";
    let quoted = false;
    for (let i = 0; i < line.length; i += 1) {
      const char = line[i];
      if (quoted) {
        if (char === '"') {
          if (line[i + 1] === '"') {
            field += '"';
            i += 1;
          } else quoted = false;
        } else field += char;
      } else if (char === '"') quoted = true;
      else if (char === ",") {
        fields.push(field);
        field = "";
      } else field += char;
    }
    fields.push(field);
    return fields.map((value) => value.trim());
  };

  const headers = split(lines[0]);
  return lines.slice(1).map((line) => {
    const values = split(line);
    return Object.fromEntries(headers.map((header, i) => [header, values[i]]));
  });
}

/** What a correct classifier must return for each injected class. */
const EXPECTED = {
  PRICE_NOISE_WITHIN_TOLERANCE: ["MATCHED_WITHIN_TOLERANCE"],
  VALUATION_BREAK: ["VALUE_DIFFERENCE"],
  QUANTITY_BREAK: ["QUANTITY_DIFFERENCE"],
  MISSING_EXTERNAL: ["MISSING_EXTERNAL"],
  STALE_PRICE: ["VALUE_DIFFERENCE", "MATCHED_WITHIN_TOLERANCE", "MATCHED"],
  ACCOUNT_MISDIRECTION: ["MISSING_EXTERNAL"],
  CURRENCY_MISLABEL: ["CURRENCY_MISMATCH"],
  MISSING_INTERNAL: ["MISSING_INTERNAL"],
};

const compiled = compileClassifier();
let failed = false;

try {
  const { reconcile } = await import(pathToFileURL(join(compiled, "reconcile.js")).href);

  const internal = parseCsv(readFileSync(join(FIXTURES, "internal_ledger.csv"), "utf8"));
  const external = parseCsv(readFileSync(join(FIXTURES, "custodian_statement.csv"), "utf8"));
  const manifest = JSON.parse(readFileSync(join(FIXTURES, "injection_manifest.json"), "utf8"));

  const result = reconcile(internal, external, Number(manifest.tolerance_bps));
  const byKey = new Map(
    result.rows.map((row) => [`${row.safekeeping_account}::${row.asset_id}`, row]),
  );

  const expectedAccount = (injected) =>
    injected.injection === "ACCOUNT_MISDIRECTION"
      ? injected.extra.expected_account
      : injected.safekeeping_account;

  const failures = [];
  let correct = 0;

  for (const injected of manifest.breaks) {
    const key = `${expectedAccount(injected)}::${injected.asset_id}`;
    const row = byKey.get(key);
    const permitted = EXPECTED[injected.injection];

    if (!row) {
      failures.push(`${injected.injection} ${key}: absent from the classifier's output`);
    } else if (permitted.includes(row.status)) {
      correct += 1;
    } else {
      failures.push(
        `${injected.injection} ${key}: returned ${row.status}, expected one of ` +
          permitted.join(" | "),
      );
    }
  }

  // A misdirected booking must surface on the receiving account too.
  let pairs = 0;
  for (const injected of manifest.breaks) {
    if (injected.injection !== "ACCOUNT_MISDIRECTION") continue;
    const landed = byKey.get(`${injected.extra.actual_account}::${injected.asset_id}`);
    if (landed?.status === "MISSING_INTERNAL") pairs += 1;
    else
      failures.push(
        `ACCOUNT_MISDIRECTION: the receiving account ${injected.extra.actual_account} ` +
          "did not surface as MISSING_INTERNAL — netting the two sides would hide it",
      );
  }

  // Anything raised that was never injected is a false positive.
  const injectedKeys = new Set();
  for (const injected of manifest.breaks) {
    injectedKeys.add(`${expectedAccount(injected)}::${injected.asset_id}`);
    if (injected.injection === "ACCOUNT_MISDIRECTION") {
      injectedKeys.add(`${injected.extra.actual_account}::${injected.asset_id}`);
    }
  }
  const falsePositives = result.rows.filter(
    (row) =>
      row.status !== "MATCHED" &&
      row.status !== "MATCHED_WITHIN_TOLERANCE" &&
      !injectedKeys.has(row.key),
  );

  console.log("  AETHER reconciliation — classifier vs answer key");
  console.log("  " + "-".repeat(58));
  console.log(`  positions compared        ${result.summary.total}`);
  console.log(`  exceptions raised         ${result.summary.exceptions}`);
  console.log(`  matched within tolerance  ${result.summary.withinTolerance}`);
  console.log(`  matched exactly           ${result.summary.matched}`);
  console.log("");
  console.log(`  breaks in the answer key  ${manifest.breaks.length}`);
  console.log(`  classified as expected    ${correct}`);
  console.log(`  misclassified             ${manifest.breaks.length - correct}`);
  console.log(`  misdirection pairs found  ${pairs}`);
  console.log(`  false positives           ${falsePositives.length}`);
  console.log("");
  console.log("  variance, by currency (never summed across them):");
  for (const entry of result.summary.variance) {
    console.log(
      `    ${entry.currency}  net ${entry.net.padStart(16)}  ` +
        `gross ${entry.gross.padStart(16)}  ${entry.rows} rows`,
    );
  }

  for (const fp of falsePositives) {
    failures.push(`false positive: ${fp.key} raised as ${fp.status}`);
  }

  if (failures.length > 0) {
    console.log("");
    console.log("  FAILURES");
    for (const failure of failures) console.log(`    ${failure}`);
    failed = true;
  } else {
    console.log("");
    console.log("  PASS — every injected break was classified as documented, and");
    console.log("         nothing was raised that was not injected.");
  }
} finally {
  rmSync(compiled, { recursive: true, force: true });
}

process.exit(failed ? 1 : 0);
