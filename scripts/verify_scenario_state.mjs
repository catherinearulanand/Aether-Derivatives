/**
 * Prove the scenario selector cannot ask the API for a comparison it will refuse.
 *
 * ``GET /api/v1/comparison/{before}/{after}`` returns 422 when ``before`` is dated
 * after ``after``. That guard is correct and stays. What broke was the *selector*:
 * when a click collided with the other selection, the store swapped the pair, which
 * for three scenarios can produce a pair running backwards in time. Choosing the
 * quiet market as the snapshot moved the rate shock into the baseline and asked for
 * 17 August to 14 August. The 422 was the API defending itself, not a date bug.
 *
 * So this script drives the **shipped** store — ``frontend/src/lib/store.ts``, the
 * exact module every screen imports — through every selection a user can make, and
 * asserts after each one that:
 *
 * 1. the pair runs forwards in time, judged by the engine's own ``as_of`` dates;
 * 2. clicking a snapshot makes that snapshot the active run, so the dashboard cannot
 *    display one scenario's snapshot id while another is highlighted;
 * 3. an unusable pair collapses to an identical pair, which the comparison query
 *    disables — an empty panel rather than a red error.
 *
 * Dates are read from the API rather than restated here. A copy would keep passing
 * after somebody reorders the scenarios.
 *
 * .. rubric:: Running it
 *
 *     node scripts/verify_scenario_state.mjs
 *     AETHER_API=https://d3gzusuqrty02w.cloudfront.net node scripts/verify_scenario_state.mjs
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FRONTEND = join(ROOT, "frontend");
const API = process.env.AETHER_API ?? "http://127.0.0.1:8000";

/**
 * Compile the store to a temp directory **inside** the frontend.
 *
 * Outside it, Node cannot resolve ``zustand``: bare specifiers resolve by walking
 * up from the importing file, so the emitted module has to sit under a directory
 * that has ``frontend/node_modules`` above it.
 */
function compileStore() {
  const out = mkdtempSync(join(FRONTEND, ".verify-store-"));
  execFileSync(
    process.execPath,
    [
      join(FRONTEND, "node_modules", "typescript", "bin", "tsc"),
      join("src", "lib", "store.ts"),
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

  // The emitted files are ESM but sit under the frontend's CommonJS package.json.
  // Naming the type here keeps Node from reparsing them and warning about it.
  writeFileSync(join(out, "package.json"), '{"type":"module"}\n');

  for (const name of readdirSync(out)) {
    if (!name.endsWith(".js")) continue;
    const path = join(out, name);
    writeFileSync(
      path,
      readFileSync(path, "utf8").replace(/from "(\.\/[^"]+)"/g, (match, specifier) =>
        specifier.endsWith(".js") ? match : `from "${specifier}.js"`,
      ),
    );
  }
  return out;
}

/** The store persists to sessionStorage, which does not exist outside a browser. */
function installSessionStorage() {
  const cells = new Map();
  globalThis.sessionStorage = {
    getItem: (k) => (cells.has(k) ? cells.get(k) : null),
    setItem: (k, v) => cells.set(k, String(v)),
    removeItem: (k) => cells.delete(k),
    clear: () => cells.clear(),
  };
}

const compiled = compileStore();
let failed = 0;
let checked = 0;

function assert(condition, description, detail = "") {
  checked += 1;
  if (condition) {
    console.log(`  ok    ${description}${detail ? `   ${detail}` : ""}`);
  } else {
    failed += 1;
    console.log(`  FAIL  ${description}${detail ? `   ${detail}` : ""}`);
  }
}

try {
  installSessionStorage();

  const { scenarios } = await fetch(`${API}/api/v1/scenarios`).then((r) => r.json());
  const asOf = new Map(scenarios.map((s) => [s.key, s.as_of]));
  const snapshotId = new Map(scenarios.map((s) => [s.key, s.snapshot_id]));
  const keys = scenarios.map((s) => s.key);

  const { useAether } = await import(pathToFileURL(join(compiled, "store.js")).href);

  console.log(`\n  Scenarios from ${API}`);
  for (const s of scenarios) console.log(`    ${s.key.padEnd(7)} ${s.as_of}  ${s.snapshot_id}`);

  // -------------------------------------------------- the invariant, everywhere
  console.log("\n  Every selection leaves a pair the comparison endpoint accepts\n");

  const set = (baselineKey, currentKey) => useAether.setState({ baselineKey, currentKey });
  const read = () => {
    const { baselineKey, currentKey } = useAether.getState();
    return { baselineKey, currentKey };
  };

  const forwards = ({ baselineKey, currentKey }) =>
    baselineKey === currentKey || asOf.get(baselineKey) < asOf.get(currentKey);

  for (const startBaseline of keys) {
    for (const startCurrent of keys) {
      for (const pick of keys) {
        set(startBaseline, startCurrent);
        useAether.getState().setCurrent(pick);
        const afterCurrent = read();
        assert(
          forwards(afterCurrent),
          `setCurrent(${pick}) from ${startBaseline}/${startCurrent}`,
          `-> ${afterCurrent.baselineKey}/${afterCurrent.currentKey}`,
        );
        // The click landed in the Snapshot row, so the active run must be what was
        // clicked. This is the desync: a highlighted scenario whose snapshot id the
        // dashboard never loaded.
        assert(
          afterCurrent.currentKey === pick,
          `  and ${snapshotId.get(pick)} is the active run`,
        );

        set(startBaseline, startCurrent);
        useAether.getState().setBaseline(pick);
        const afterBaseline = read();
        assert(
          forwards(afterBaseline),
          `setBaseline(${pick}) from ${startBaseline}/${startCurrent}`,
          `-> ${afterBaseline.baselineKey}/${afterBaseline.currentKey}`,
        );
        assert(
          afterBaseline.baselineKey === pick,
          `  and the baseline is ${snapshotId.get(pick)}`,
        );
      }
    }
  }

  // ------------------------------------------------------ the named cases
  console.log("\n  The cases the API is asked about directly\n");

  const compare = async (before, after) => {
    const response = await fetch(`${API}/api/v1/comparison/${before}/${after}`);
    return response.status;
  };

  assert(
    (await compare("base", "stress")) === 200,
    "base 2026-08-14 -> stress 2026-08-17 is accepted",
  );
  assert(
    (await compare("stress", "base")) === 422,
    "stress 2026-08-17 -> base 2026-08-14 is refused",
  );

  // The earliest snapshot has nothing before it. The store collapses the pair, and
  // useComparisonBetween is disabled while before === after, so the dashboard shows
  // "choose a different baseline" instead of an error.
  set("base", "stress");
  useAether.getState().setCurrent("base");
  const earliest = read();
  assert(
    earliest.baselineKey === earliest.currentKey && earliest.currentKey === "base",
    "selecting the earliest snapshot collapses the pair, disabling the comparison",
    `-> ${earliest.baselineKey}/${earliest.currentKey}`,
  );

  // ------------------------------------------- a stored pair from before the fix
  console.log("\n  A session persisted before the ordering rule existed\n");

  globalThis.sessionStorage.setItem(
    "aether.session",
    JSON.stringify({
      state: { role: null, identity: null, signedInAt: null, baselineKey: "stress", currentKey: "base" },
      version: 0,
    }),
  );
  useAether.persist.rehydrate();
  const rehydrated = read();
  assert(
    forwards(rehydrated),
    "a backwards pair is repaired on rehydrate rather than replayed",
    `-> ${rehydrated.baselineKey}/${rehydrated.currentKey}`,
  );
} finally {
  rmSync(compiled, { recursive: true, force: true });
}

console.log(
  failed === 0
    ? `\n  PASS  ${checked} assertions\n`
    : `\n  FAIL  ${failed} of ${checked} assertions\n`,
);
process.exit(failed === 0 ? 0 : 1);
