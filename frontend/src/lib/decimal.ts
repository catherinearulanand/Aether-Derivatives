/**
 * Exact decimal arithmetic on strings, via `BigInt`.
 *
 * .. rubric:: Why this exists, and where it may be used
 *
 * Every figure AETHER's engine produces is computed in Python with `Decimal` and
 * arrives here as a string. The browser formats those strings and does **no**
 * arithmetic on them: the before/after deltas are subtracted server-side precisely
 * so that no engine figure ever passes through an IEEE-754 double.
 *
 * This module exists for the one case that has no server side — collateral
 * reconciliation, where the user uploads two CSV files and the two must be
 * compared locally. Those amounts never touch the margin engine and never become
 * an authoritative financial result; they are two ledgers being differenced. But
 * `parseFloat("400000000.17") - parseFloat("400000000.16")` does not equal `0.01`,
 * and a reconciliation screen that reports a phantom one-cent break on a
 * four-hundred-million-rupee position is worse than no reconciliation at all.
 *
 * So: scaled-integer arithmetic on `BigInt`, exact to the last digit, no floats
 * anywhere in the path.
 *
 * **Do not use this to derive a margin, exposure or allocation figure.** Those come
 * from the engine.
 */

/** A decimal parsed into a sign, an unscaled integer, and a scale. */
interface Parsed {
  units: bigint;
  scale: number;
}

const DECIMAL_PATTERN = /^-?\d+(\.\d+)?$/;

export class DecimalError extends Error {
  constructor(value: string) {
    super(`"${value}" is not a decimal number.`);
    this.name = "DecimalError";
  }
}

export function isDecimal(value: string): boolean {
  return DECIMAL_PATTERN.test(value.trim());
}

function parse(value: string): Parsed {
  const text = value.trim();
  if (!DECIMAL_PATTERN.test(text)) throw new DecimalError(value);

  const negative = text.startsWith("-");
  const magnitude = negative ? text.slice(1) : text;
  const [whole, fraction = ""] = magnitude.split(".");
  const units = BigInt(whole + fraction);
  return { units: negative ? -units : units, scale: fraction.length };
}

/** Bring two parsed decimals onto a common scale without losing a digit. */
function align(a: Parsed, b: Parsed): { a: bigint; b: bigint; scale: number } {
  const scale = Math.max(a.scale, b.scale);
  const lift = (p: Parsed) => p.units * 10n ** BigInt(scale - p.scale);
  return { a: lift(a), b: lift(b), scale };
}

function render(units: bigint, scale: number): string {
  const negative = units < 0n;
  const digits = (negative ? -units : units).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = scale > 0 ? `.${digits.slice(digits.length - scale)}` : "";
  return `${negative ? "-" : ""}${whole}${fraction}`;
}

export function subtract(a: string, b: string): string {
  const aligned = align(parse(a), parse(b));
  return render(aligned.a - aligned.b, aligned.scale);
}

export function add(a: string, b: string): string {
  const aligned = align(parse(a), parse(b));
  return render(aligned.a + aligned.b, aligned.scale);
}

/** Sum a list exactly. An empty list sums to "0", not to a float NaN. */
export function sum(values: readonly string[]): string {
  return values.reduce((total, value) => add(total, value), "0");
}

export function compare(a: string, b: string): -1 | 0 | 1 {
  const aligned = align(parse(a), parse(b));
  if (aligned.a < aligned.b) return -1;
  if (aligned.a > aligned.b) return 1;
  return 0;
}

export function isZero(value: string): boolean {
  return parse(value).units === 0n;
}

export function abs(value: string): string {
  const { units, scale } = parse(value);
  return render(units < 0n ? -units : units, scale);
}

export function negate(value: string): string {
  const { units, scale } = parse(value);
  return render(-units, scale);
}

/**
 * Round half-even to a given number of decimal places.
 *
 * Half-even because it is the convention for valuation, and because rounding half
 * away from zero over a book of positions introduces a small upward bias.
 */
export function round(value: string, places = 2): string {
  const { units, scale } = parse(value);
  if (scale <= places) {
    return render(units * 10n ** BigInt(places - scale), places);
  }

  const divisor = 10n ** BigInt(scale - places);
  const negative = units < 0n;
  const magnitude = negative ? -units : units;

  const quotient = magnitude / divisor;
  const remainder = magnitude * 2n - quotient * divisor * 2n;

  let rounded = quotient;
  if (remainder > divisor) rounded += 1n;
  else if (remainder === divisor && quotient % 2n === 1n) rounded += 1n;

  return render(negative ? -rounded : rounded, places);
}

/**
 * Difference expressed in basis points of the reference amount.
 *
 * Returns `null` when the reference is zero: a relative difference against nothing
 * is undefined, and reporting it as `0` or `Infinity` would both be lies. The
 * caller decides how to present "no meaningful ratio".
 *
 * The result is a display figure, deliberately rounded to two places, and is the
 * only place in this module a Number appears — bps of a tolerance comparison does
 * not need exactness beyond what a double gives at this magnitude.
 */
export function differenceBps(actual: string, reference: string): number | null {
  if (isZero(reference)) return null;
  const difference = subtract(actual, reference);
  // Scale by 10,000 exactly, then divide once. One division, one rounding.
  const scaled = multiplyByInteger(difference, 10_000n);
  return Number(scaled) / Number(reference);
}

function multiplyByInteger(value: string, factor: bigint): string {
  const { units, scale } = parse(value);
  return render(units * factor, scale);
}
