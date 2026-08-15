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
