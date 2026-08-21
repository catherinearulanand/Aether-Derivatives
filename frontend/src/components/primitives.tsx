"use client";

import { formatMoney, isNegative } from "@/lib/format";
import type { Money } from "@/lib/types";

/** A bordered panel with a monospace title strip. */
export function Panel({
  title,
  aside,
  children,
  className = "",
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <h2 className="panel-title">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/**
 * A monetary figure. Negatives render in parentheses and in the loss colour, which
 * is what a collateral blotter does and what a practitioner reads without thinking.
 */
export function Amount({
  value,
  className = "",
  signed = true,
}: {
  value: Money | null | undefined;
  className?: string;
  signed?: boolean;
}) {
  const negative = signed && isNegative(value);
  return (
    <span
      className={`tnum ${className}`}
      style={negative ? { color: "var(--neg)" } : undefined}
    >
      {formatMoney(value)}
    </span>
  );
}

/** A labelled statistic. The label is small and quiet; the figure carries the weight. */
export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "accent" | "warn" | "crit";
}) {
  const colour =
    tone === "accent"
      ? "var(--accent)"
      : tone === "warn"
        ? "var(--warn)"
        : tone === "crit"
          ? "var(--crit)"
          : "var(--ink)";

  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="eyebrow truncate" title={label}>
        {label}
      </span>
      <span
        className="tnum font-semibold leading-tight"
        style={{
          color: colour,
          // Long amounts step down rather than clipping. A truncated figure on a
          // collateral blotter is a defect, not a layout compromise.
          fontSize: typeof value === "string" && value.length > 18 ? 14 : 17,
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </span>
      {hint && (
        <span className="text-[11px] leading-snug" style={{ color: "var(--ink-faint)" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

export function Chip({
  children,
  tone = "default",
  title,
}: {
  children: React.ReactNode;
  tone?: "default" | "accent" | "warn" | "crit";
  title?: string;
}) {
  const cls =
    tone === "accent"
      ? "chip chip-accent"
      : tone === "warn"
        ? "chip chip-warn"
        : tone === "crit"
          ? "chip chip-crit"
          : "chip";
  return (
    <span className={cls} title={title}>
      {children}
    </span>
  );
}

export function Loading({ label = "Computing" }: { label?: string }) {
  return (
    <div
      className="flex items-center gap-2.5 px-4 py-8 text-[12.5px]"
      style={{ color: "var(--ink-mute)" }}
    >
      <span className="pulse mono" style={{ color: "var(--accent)" }}>
        ●
      </span>
      {label}…
    </div>
  );
}

export function ErrorPanel({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div
      className="panel p-4 text-[12.5px]"
      style={{ borderColor: "var(--crit)", color: "var(--ink-mid)" }}
    >
      <div className="chip chip-crit mb-2">Error</div>
      <p className="m-0">{message}</p>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-8 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
      {children}
    </div>
  );
}


/* ------------------------------------------------------------ status coding */

/**
 * A threshold status, named as well as coloured.
 *
 * Colour alone would fail every reader who cannot separate the three hues, and a
 * collateral screen is not the place to make that someone else's problem. The
 * state is always spelled out; the colour is reinforcement.
 */
export function StatusPill({
  state,
  title,
}: {
  state: "WITHIN" | "WARNING" | "BREACHED";
  title?: string;
}) {
  const config = {
    WITHIN: { label: "Within threshold", className: "status-ok" },
    WARNING: { label: "Below MTA", className: "status-warn" },
    BREACHED: { label: "Threshold exceeded", className: "status-crit" },
  }[state];

  return (
    <span className={`status-pill ${config.className}`} title={title}>
      {config.label}
    </span>
  );
}

/** The key, stated once wherever a status appears. */
export function StatusLegend({ className = "" }: { className?: string }) {
  const entries: [string, string, string][] = [
    ["status-ok", "Within threshold", "Exposure is inside the Threshold. No Credit Support Amount arises."],
    ["status-warn", "Below MTA", "Threshold exceeded, but the amount is under the Minimum Transfer Amount, so nothing transfers today."],
    ["status-crit", "Threshold exceeded", "A transfer is due under Paragraph 2."],
  ];
  return (
    <div
      className={`flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] ${className}`}
      style={{ color: "var(--ink-faint)" }}
    >
      <span className="eyebrow">Key</span>
      {entries.map(([className_, label, hint]) => (
        <span key={label} className="flex items-center gap-1.5" title={hint}>
          <span
            className={className_}
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: "currentColor",
              display: "inline-block",
            }}
          />
          {label}
        </span>
      ))}
    </div>
  );
}

/**
 * A signed change between two engine figures.
 *
 * The arrow states the direction and the sign states it again, because on a
 * collateral screen "up" is not universally good or bad — a rising requirement and
 * a rising netting benefit point opposite ways for the desk. So this renders
 * magnitude and direction, and leaves the judgement to the label beside it.
 */
export function Delta({
  value,
  direction,
  unavailable,
}: {
  value: Money | null;
  direction: "UP" | "DOWN" | "FLAT" | "NOT_COMPARABLE";
  unavailable?: string;
}) {
  if (direction === "NOT_COMPARABLE" || !value) {
    return (
      <span
        className="delta delta-flat text-[11.5px]"
        title={unavailable ?? "Not comparable."}
      >
        not comparable
      </span>
    );
  }

  const glyph = direction === "UP" ? "▲" : direction === "DOWN" ? "▼" : "—";
  const tone =
    direction === "UP" ? "delta-up" : direction === "DOWN" ? "delta-down" : "delta-flat";

  return (
    <span className={`delta ${tone}`}>
      <span aria-hidden="true" style={{ fontSize: 9 }}>
        {glyph}
      </span>
      <span className="tnum">{formatMoney(value)}</span>
    </span>
  );
}

/** A row of loading bars that matches the shape of what is coming. */
export function Skeleton({
  rows = 3,
  height = 14,
}: {
  rows?: number;
  height?: number;
}) {
  return (
    <div className="px-4 py-3.5 flex flex-col gap-2" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton"
          style={{ height, width: `${100 - i * 9}%` }}
        />
      ))}
    </div>
  );
}
