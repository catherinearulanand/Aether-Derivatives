/**
 * Collateral reconciliation.
 *
 * Matches the bank's internal collateral ledger against an external custodian
 * statement and classifies every difference. Pure: values in, results out, no
 * fetch, no clock, no state.
 *
 * .. rubric:: The matching key
 *
 * Positions are matched on **safekeeping account plus asset**, which is what a
 * collateral team actually reconciles on. Deliberately *not* the internal position
 * id: the custodian has never seen it. That choice is what makes a misdirected
 * booking detectable at all — collateral booked to the wrong account appears as a
 * missing external row on one account and an unexplained internal-less row on
 * another, rather than quietly matching by identifier.
 *
 * .. rubric:: Tolerance
 *
 * Two vendors pricing the same bond do not agree to the last cent. A screen with
 * no tolerance reports the whole book as broken and gets ignored by the desk. A
 * difference at or below `toleranceBps` of the internal market value is recorded
 * as matched-within-tolerance and is visible as such — absorbed, not hidden.
 *
 * .. rubric:: Currency
 *
 * Amounts in different currencies are never summed. The variance total is reported
 * per currency, because converting an INR position into USD to make one headline
 * number would require an FX rate this screen has not been given and must not
 * invent.
 */

import { abs, compare, differenceBps, isDecimal, subtract, sum } from "./decimal";

export type MatchStatus =
  | "MATCHED"
  | "MATCHED_WITHIN_TOLERANCE"
  | "VALUE_DIFFERENCE"
  | "QUANTITY_DIFFERENCE"
  | "CURRENCY_MISMATCH"
  | "MISSING_EXTERNAL"
  | "MISSING_INTERNAL";

export interface ReconciliationRow {
  key: string;
  safekeeping_account: string;
  asset_id: string;
  description: string;
  asset_class: string;
  custodian: string;
  /** Absent on a MISSING_INTERNAL row. */
  position_id: string | null;
  counterparty: string | null;

  internal_currency: string | null;
  external_currency: string | null;
  internal_nominal: string | null;
  external_nominal: string | null;
  internal_market_value: string | null;
  external_market_value: string | null;

  /** internal − external, in the internal currency. Null when one side is absent. */
  difference: string | null;
  /** Difference as basis points of the internal market value. */
  difference_bps: number | null;
  /** The custodian's pricing date, when it differs from the statement date. */
  stale_price_as_of: string | null;

  status: MatchStatus;
  explanation: string;
}

export interface CurrencyVariance {
  currency: string;
  /** Signed net: internal minus external, across breaks in this currency. */
  net: string;
  /** Sum of absolute differences — the size of the problem, not its direction. */
  gross: string;
  rows: number;
}

export interface ReconciliationSummary {
  total: number;
  matched: number;
  withinTolerance: number;
  valueDifference: number;
  quantityDifference: number;
  currencyMismatch: number;
  missingExternal: number;
  missingInternal: number;
  /** Everything a reviewer must look at. Within-tolerance rows are not exceptions. */
  exceptions: number;
  exceptionRate: number;
  variance: CurrencyVariance[];
}

export interface ReconciliationResult {
  rows: ReconciliationRow[];
  summary: ReconciliationSummary;
  toleranceBps: number;
  statementDate: string | null;
}

export const INTERNAL_COLUMNS = [
  "position_id",
  "safekeeping_account",
  "asset_id",
  "currency",
  "nominal",
  "market_value",
] as const;

export const EXTERNAL_COLUMNS = [
  "safekeeping_account",
  "asset_id",
  "currency",
  "nominal",
  "market_value",
] as const;

const STATUS_LABELS: Record<MatchStatus, string> = {
  MATCHED: "Matched",
  MATCHED_WITHIN_TOLERANCE: "Matched (within tolerance)",
  VALUE_DIFFERENCE: "Value difference",
  QUANTITY_DIFFERENCE: "Quantity difference",
  CURRENCY_MISMATCH: "Currency mismatch",
  MISSING_EXTERNAL: "Missing at custodian",
  MISSING_INTERNAL: "Missing internally",
};

export function statusLabel(status: MatchStatus): string {
  return STATUS_LABELS[status];
}

/** Exceptions require a reviewer. Matched rows, tolerance included, do not. */
export function isException(status: MatchStatus): boolean {
  return status !== "MATCHED" && status !== "MATCHED_WITHIN_TOLERANCE";
}

function keyOf(row: Record<string, string>): string {
  return `${row.safekeeping_account}::${row.asset_id}`;
}

function amount(value: string | undefined): string | null {
  if (value === undefined) return null;
  const text = value.trim();
  return isDecimal(text) ? text : null;
}

/**
 * Compare one internal position against its custodian counterpart.
 *
 * Order matters: currency is checked before value, because two amounts that read
 * as equal in different currencies are not equal, and a screen that compares the
 * numbers first would report that row as matched.
 */
function classify(
  internal: Record<string, string>,
  external: Record<string, string>,
  toleranceBps: number,
): Pick<
  ReconciliationRow,
  "status" | "explanation" | "difference" | "difference_bps"
> {
  const internalValue = amount(internal.market_value);
  const externalValue = amount(external.market_value);

  if (internalValue === null || externalValue === null) {
    return {
      status: "VALUE_DIFFERENCE",
      explanation:
        "One side has no readable market value. The row cannot be compared and " +
        "must be inspected.",
      difference: null,
      difference_bps: null,
    };
  }

  const difference = subtract(internalValue, externalValue);
  const bps = differenceBps(externalValue, internalValue);

  if (internal.currency !== external.currency) {
    return {
      status: "CURRENCY_MISMATCH",
      explanation:
        `Internal holds this position in ${internal.currency}; the custodian ` +
        `reports ${external.currency}. The amounts are not comparable until the ` +
        "discrepancy is resolved.",
      difference,
      difference_bps: bps,
    };
  }

  const internalNominal = amount(internal.nominal);
  const externalNominal = amount(external.nominal);
  if (
    internalNominal !== null &&
    externalNominal !== null &&
    compare(internalNominal, externalNominal) !== 0
  ) {
    return {
      status: "QUANTITY_DIFFERENCE",
      explanation:
        `Custodian holds a nominal of ${externalNominal} against an internal ` +
        `${internalNominal}. Typically a partial settlement.`,
      difference,
      difference_bps: bps,
    };
  }

  if (compare(difference, "0") === 0) {
    return {
      status: "MATCHED",
      explanation: "Both sides agree exactly.",
      difference,
      difference_bps: 0,
    };
  }

  if (bps !== null && Math.abs(bps) <= toleranceBps) {
    return {
      status: "MATCHED_WITHIN_TOLERANCE",
      explanation:
        `Values differ by ${bps.toFixed(2)} bp, at or inside the ` +
        `${toleranceBps} bp tolerance. Recorded, not raised.`,
      difference,
      difference_bps: bps,
    };
  }

  return {
    status: "VALUE_DIFFERENCE",
    explanation:
      bps === null
        ? "Values differ and the internal side is zero, so no relative measure applies."
        : `Values differ by ${bps.toFixed(2)} bp, beyond the ${toleranceBps} bp ` +
          "tolerance.",
    difference,
    difference_bps: bps,
  };
}

export function reconcile(
  internalRows: readonly Record<string, string>[],
  externalRows: readonly Record<string, string>[],
  toleranceBps = 5,
): ReconciliationResult {
  const externalByKey = new Map<string, Record<string, string>>();
  for (const row of externalRows) externalByKey.set(keyOf(row), row);

  const rows: ReconciliationRow[] = [];
  const seen = new Set<string>();

  for (const internal of internalRows) {
    const key = keyOf(internal);
    seen.add(key);
    const external = externalByKey.get(key);

    if (!external) {
      rows.push({
        key,
        safekeeping_account: internal.safekeeping_account,
        asset_id: internal.asset_id,
        description: internal.description ?? "",
        asset_class: internal.asset_class ?? "",
        custodian: internal.custodian ?? "",
        position_id: internal.position_id ?? null,
        counterparty: internal.counterparty ?? null,
        internal_currency: internal.currency ?? null,
        external_currency: null,
        internal_nominal: amount(internal.nominal),
        external_nominal: null,
        internal_market_value: amount(internal.market_value),
        external_market_value: null,
        difference: amount(internal.market_value),
        difference_bps: null,
        stale_price_as_of: null,
        status: "MISSING_EXTERNAL",
        explanation:
          "The internal ledger carries this position; the custodian statement " +
          "does not. Usually a delivery still in flight — but it is unconfirmed " +
          "collateral until the custodian shows it.",
      });
      continue;
    }

    const verdict = classify(internal, external, toleranceBps);
    const staleAsOf =
      external.price_as_of &&
      external.statement_date &&
      external.price_as_of !== external.statement_date
        ? external.price_as_of
        : null;

    rows.push({
      key,
      safekeeping_account: internal.safekeeping_account,
      asset_id: internal.asset_id,
      description: internal.description ?? external.description ?? "",
      asset_class: internal.asset_class ?? external.asset_class ?? "",
      custodian: internal.custodian ?? external.custodian ?? "",
      position_id: internal.position_id ?? null,
      counterparty: internal.counterparty ?? null,
      internal_currency: internal.currency ?? null,
      external_currency: external.currency ?? null,
      internal_nominal: amount(internal.nominal),
      external_nominal: amount(external.nominal),
      internal_market_value: amount(internal.market_value),
      external_market_value: amount(external.market_value),
      stale_price_as_of: staleAsOf,
      ...verdict,
      explanation: staleAsOf
        ? `${verdict.explanation} The custodian priced this line as of ${staleAsOf}, ` +
          "not the statement date."
        : verdict.explanation,
    });
  }

  for (const external of externalRows) {
    const key = keyOf(external);
    if (seen.has(key)) continue;

    rows.push({
      key,
      safekeeping_account: external.safekeeping_account,
      asset_id: external.asset_id,
      description: external.description ?? "",
      asset_class: external.asset_class ?? "",
      custodian: external.custodian ?? "",
      position_id: null,
      counterparty: null,
      internal_currency: null,
      external_currency: external.currency ?? null,
      internal_nominal: null,
      external_nominal: amount(external.nominal),
      internal_market_value: null,
      external_market_value: amount(external.market_value),
      difference: (() => {
        const value = amount(external.market_value);
        return value === null ? null : subtract("0", value);
      })(),
      difference_bps: null,
      stale_price_as_of: null,
      status: "MISSING_INTERNAL",
      explanation:
        "The custodian holds this position; the internal ledger does not carry " +
        "it. An unexpected receipt, or collateral booked to the wrong account.",
    });
  }

  rows.sort((a, b) => {
    const priority = (row: ReconciliationRow) => (isException(row.status) ? 0 : 1);
    if (priority(a) !== priority(b)) return priority(a) - priority(b);
    return a.key.localeCompare(b.key);
  });

  return {
    rows,
    summary: summarise(rows),
    toleranceBps,
    statementDate: externalRows[0]?.statement_date ?? null,
  };
}

function summarise(rows: readonly ReconciliationRow[]): ReconciliationSummary {
  const count = (status: MatchStatus) =>
    rows.filter((row) => row.status === status).length;

  const exceptions = rows.filter((row) => isException(row.status));

  // Variance is grouped by currency and never summed across them. The currency of
  // a break is whichever side reported it; a currency mismatch is attributed to
  // the internal book, which is the ledger being defended.
  const byCurrency = new Map<string, { values: string[]; rows: number }>();
  for (const row of exceptions) {
    if (row.difference === null) continue;
    const currency = row.internal_currency ?? row.external_currency ?? "—";
    const bucket = byCurrency.get(currency) ?? { values: [], rows: 0 };
    bucket.values.push(row.difference);
    bucket.rows += 1;
    byCurrency.set(currency, bucket);
  }

  const variance: CurrencyVariance[] = [...byCurrency.entries()]
    .map(([currency, bucket]) => ({
      currency,
      net: sum(bucket.values),
      gross: sum(bucket.values.map(abs)),
      rows: bucket.rows,
    }))
    .sort((a, b) => a.currency.localeCompare(b.currency));

  return {
    total: rows.length,
    matched: count("MATCHED"),
    withinTolerance: count("MATCHED_WITHIN_TOLERANCE"),
    valueDifference: count("VALUE_DIFFERENCE"),
    quantityDifference: count("QUANTITY_DIFFERENCE"),
    currencyMismatch: count("CURRENCY_MISMATCH"),
    missingExternal: count("MISSING_EXTERNAL"),
    missingInternal: count("MISSING_INTERNAL"),
    exceptions: exceptions.length,
    exceptionRate: rows.length === 0 ? 0 : exceptions.length / rows.length,
    variance,
  };
}
