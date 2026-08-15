/**
 * Display formatting.
 *
 * Money arrives as a decimal string and is formatted by string manipulation, never
 * by parsing to a JavaScript number. `parseFloat("19469510.12")` is fine today and
 * wrong on a large enough figure; there is no reason to introduce the risk when the
 * exact digits are already in hand.
 *
 * Negatives render in parentheses, which is market convention on a collateral blotter
 * and is what a practitioner expects to see.
 */

import type { Money } from "./types";

/** Insert thousands separators into the integer part of a decimal string. */
function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

export function formatAmount(amount: string): string {
  const negative = amount.startsWith("-");
  const magnitude = negative ? amount.slice(1) : amount;
  const [whole, fraction = "00"] = magnitude.split(".");
  const formatted = `${groupDigits(whole)}.${fraction.padEnd(2, "0").slice(0, 2)}`;
  return negative ? `(${formatted})` : formatted;
}

export function formatMoney(money: Money | null | undefined): string {
  if (!money) return "—";
  const negative = money.amount.startsWith("-");
  const body = formatAmount(money.amount);
  return negative
    ? `(${money.currency} ${body.slice(1, -1)})`
    : `${money.currency} ${body}`;
}

/** Compact form for headline figures: USD 9.5m, USD 17.1k. */
export function formatCompact(money: Money | null | undefined): string {
  if (!money) return "—";
  const negative = money.amount.startsWith("-");
  const magnitude = negative ? money.amount.slice(1) : money.amount;
  const whole = magnitude.split(".")[0];
  const digits = whole.length;

  let value: string;
  let suffix: string;
  if (digits > 9) {
    value = insertPoint(whole, 9);
    suffix = "bn";
  } else if (digits > 6) {
    value = insertPoint(whole, 6);
    suffix = "m";
  } else if (digits > 3) {
    value = insertPoint(whole, 3);
    suffix = "k";
  } else {
    value = whole;
    suffix = "";
  }

  const text = `${money.currency} ${value}${suffix}`;
  return negative ? `(${text})` : text;
}

function insertPoint(whole: string, places: number): string {
  const head = whole.slice(0, whole.length - places);
  const tail = whole.slice(whole.length - places, whole.length - places + 1);
  return tail === "0" ? head : `${head}.${tail}`;
}

export function isNegative(money: Money | null | undefined): boolean {
  return Boolean(money?.amount.startsWith("-"));
}

export function formatPercent(decimalString: string, places = 2): string {
  const value = Number(decimalString) * 100;
  return `${value.toFixed(places)}%`;
}

/** A ratio already expressed in percentage points, e.g. "74.35". */
export function formatPercentPoints(value: string, places = 1): string {
  return `${Number(value).toFixed(places)}%`;
}

export function formatBps(value: string, places = 2): string {
  return `${Number(value).toFixed(places)}bp`;
}

export function formatDate(iso: string): string {
  const [year, month, day] = iso.split("T")[0].split("-");
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${day} ${months[Number(month) - 1]} ${year}`;
}

export function shortHash(hash: string, length = 12): string {
  return `${hash.slice(0, length)}…`;
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
