"use client";

/**
 * Charts, drawn as inline SVG.
 *
 * No charting library. Four marks are needed — a ranked bar, a two-point change
 * line, a composition bar and a heatmap — and each is thirty lines of SVG. Pulling
 * in a 90kB dependency to draw a rectangle would be a worse trade than writing the
 * rectangle.
 *
 * .. rubric:: Rules these charts follow
 *
 * Every mark comes from a figure the engine returned. Nothing is smoothed,
 * interpolated or extrapolated: a line between two pinned snapshots connects two
 * observations and does not imply the path between them. Magnitudes are scaled
 * against the largest value present and the scale is stated, so a bar cannot
 * flatter a small number by filling its track.
 *
 * Colour is a single sequential ramp of one hue. A categorical rainbow would
 * invent groupings the data does not have.
 */

import { formatCompact } from "@/lib/format";
import type { Money } from "@/lib/types";

/** Parse for *display geometry only* — never for a figure shown as a value. */
function magnitude(amount: string): number {
  const parsed = Number(amount);
  return Number.isFinite(parsed) ? parsed : 0;
}

export interface BarDatum {
  label: string;
  sublabel?: string;
  value: Money;
  /** 0–1. Drives the ramp; defaults to the value's share of the maximum. */
  intensity?: number;
  emphasis?: boolean;
  title?: string;
}

/**
 * A ranked horizontal bar chart.
 *
 * Horizontal because the labels are asset identifiers and asset identifiers do not
 * fit under a vertical bar without rotating them, and rotated axis labels are a
 * tax on the reader.
 */
export function RankedBars({
  data,
  caption,
  emptyMessage = "No data for this run.",
}: {
  data: BarDatum[];
  caption?: string;
  emptyMessage?: string;
}) {
  if (data.length === 0) {
    return (
      <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
        {emptyMessage}
      </p>
    );
  }

  const max = Math.max(...data.map((d) => Math.abs(magnitude(d.value.amount))), 1);

  return (
    <div className="px-4 py-3.5 flex flex-col gap-2.5">
      {data.map((datum) => {
        const share = Math.abs(magnitude(datum.value.amount)) / max;
        return (
          <div key={datum.label} className="flex items-center gap-3" title={datum.title}>
            <div className="min-w-0" style={{ width: 168 }}>
              <div className="mono text-[11px] truncate">{datum.label}</div>
              {datum.sublabel && (
                <div
                  className="text-[10px] truncate"
                  style={{ color: "var(--ink-faint)" }}
                >
                  {datum.sublabel}
                </div>
              )}
            </div>

            <div
              className="flex-1 h-[18px] relative rounded-sm overflow-hidden"
              style={{ background: "var(--surface-3)", minWidth: 60 }}
            >
              <div
                className="h-full transition-[width] duration-300 ease-out"
                style={{
                  width: `${Math.max(share * 100, 1.5)}%`,
                  background: datum.emphasis ? "var(--accent)" : "var(--accent-dim)",
                }}
              />
            </div>

            <span
              className="tnum text-[11.5px] text-right shrink-0"
              style={{ width: 108, color: datum.emphasis ? "var(--ink)" : "var(--ink-mid)" }}
            >
              {formatCompact(datum.value)}
            </span>
          </div>
        );
      })}

      {caption && (
        <p className="m-0 mt-1 text-[11px]" style={{ color: "var(--ink-faint)" }}>
          {caption} Bars are scaled against the largest value shown
          {` (${formatCompact(
            data.reduce((best, d) =>
              Math.abs(magnitude(d.value.amount)) > Math.abs(magnitude(best.value.amount))
                ? d
                : best,
            ).value,
          )})`}
          .
        </p>
      )}
    </div>
  );
}

export interface CompositionSlice {
  label: string;
  value: Money;
  title?: string;
}

/**
 * A single stacked bar showing composition.
 *
 * Chosen over a donut because comparing angular segments is measurably harder than
 * comparing lengths along a shared axis, and because a stacked bar leaves room for
 * labels beside it rather than in a floating legend.
 */
export function Composition({
  slices,
  total,
  caption,
}: {
  slices: CompositionSlice[];
  total?: Money;
  caption?: string;
}) {
  const sum = slices.reduce((acc, s) => acc + Math.abs(magnitude(s.value.amount)), 0);

  if (slices.length === 0 || sum === 0) {
    return (
      <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
        Nothing was allocated in this run, so there is no composition to show.
      </p>
    );
  }

  const ramp = [
    "var(--heat-6)",
    "var(--heat-5)",
    "var(--heat-4)",
    "var(--heat-3)",
    "var(--heat-2)",
    "var(--heat-1)",
  ];

  return (
    <div className="px-4 py-3.5 flex flex-col gap-3">
      <div
        className="flex h-[26px] rounded-sm overflow-hidden"
        style={{ background: "var(--surface-3)" }}
        role="img"
        aria-label={`Composition across ${slices.length} groups`}
      >
        {slices.map((slice, index) => {
          const share = Math.abs(magnitude(slice.value.amount)) / sum;
          return (
            <div
              key={slice.label}
              title={slice.title ?? `${slice.label}: ${(share * 100).toFixed(1)}%`}
              style={{
                width: `${share * 100}%`,
                background: ramp[index % ramp.length],
                borderRight: "1px solid var(--ground)",
              }}
            />
          );
        })}
      </div>

      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5">
        {slices.map((slice, index) => {
          const share = Math.abs(magnitude(slice.value.amount)) / sum;
          return (
            <div key={slice.label} className="flex items-center gap-2 text-[11.5px]">
              <span
                style={{
                  width: 9,
                  height: 9,
                  background: ramp[index % ramp.length],
                  borderRadius: 1,
                  flexShrink: 0,
                }}
              />
              <span className="truncate" style={{ color: "var(--ink-mid)" }}>
                {slice.label}
              </span>
              <span
                className="tnum ml-auto shrink-0"
                style={{ color: "var(--ink-faint)" }}
              >
                {(share * 100).toFixed(1)}%
              </span>
              <span className="tnum shrink-0" style={{ width: 84, textAlign: "right" }}>
                {formatCompact(slice.value)}
              </span>
            </div>
          );
        })}
      </div>

      {total && (
        <div
          className="flex items-baseline justify-between pt-2 text-[12px]"
          style={{ borderTop: "1px solid var(--rule)" }}
        >
          <span className="eyebrow">Total</span>
          <span className="tnum font-semibold">{formatCompact(total)}</span>
        </div>
      )}

      {caption && (
        <p className="m-0 text-[11px]" style={{ color: "var(--ink-faint)" }}>
          {caption}
        </p>
      )}
    </div>
  );
}

export interface ChangeSeries {
  label: string;
  points: { x: string; value: Money }[];
  emphasis?: boolean;
}

/**
 * Change across pinned snapshots.
 *
 * Points are drawn as points and joined with a straight segment, because AETHER
 * observed those snapshots and nothing in between. A smoothed curve would imply
 * intraday knowledge this system does not have.
 */
export function ChangeChart({
  series,
  height = 168,
  caption,
}: {
  series: ChangeSeries[];
  height?: number;
  caption?: string;
}) {
  const xs = series[0]?.points.map((p) => p.x) ?? [];
  if (xs.length < 2) {
    return (
      <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
        At least two snapshots are needed to show a change.
      </p>
    );
  }

  const values = series.flatMap((s) => s.points.map((p) => magnitude(p.value.amount)));
  const rawMax = Math.max(...values);
  const rawMin = Math.min(...values, 0);
  const span = rawMax - rawMin || 1;
  const max = rawMax + span * 0.12;
  const min = rawMin - span * 0.12;

  const width = 640;
  const padLeft = 62;
  const padRight = 16;
  const padTop = 12;
  const padBottom = 26;

  const x = (index: number) =>
    padLeft + (index / (xs.length - 1)) * (width - padLeft - padRight);
  const y = (value: number) =>
    padTop + (1 - (value - min) / (max - min)) * (height - padTop - padBottom);

  const gridlines = [0, 0.25, 0.5, 0.75, 1].map((t) => min + t * (max - min));

  return (
    <div className="px-4 py-3.5">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label={`Change across ${xs.length} snapshots`}
      >
        <g className="chart-grid">
          {gridlines.map((value) => (
            <line key={value} x1={padLeft} x2={width - padRight} y1={y(value)} y2={y(value)} />
          ))}
        </g>

        <g className="chart-axis">
          {gridlines.map((value) => (
            <text key={value} x={padLeft - 8} y={y(value) + 3} textAnchor="end">
              {compactNumber(value)}
            </text>
          ))}
          {xs.map((label, index) => (
            <text key={label} x={x(index)} y={height - 8} textAnchor="middle">
              {label}
            </text>
          ))}
        </g>

        {/* Zero line, drawn only when the range crosses it — an axis at zero is
            meaningful for a signed mark-to-market and noise otherwise. */}
        {min < 0 && max > 0 && (
          <line
            x1={padLeft}
            x2={width - padRight}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--ink-faint)"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        )}

        {series.map((s, seriesIndex) => {
          const colour = s.emphasis
            ? "var(--accent)"
            : ["var(--warn)", "var(--heat-4)", "var(--ink-mute)"][seriesIndex % 3];
          const path = s.points
            .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(magnitude(p.value.amount))}`)
            .join(" ");
          return (
            <g key={s.label}>
              <path
                d={path}
                fill="none"
                stroke={colour}
                strokeWidth={s.emphasis ? 2 : 1.5}
                strokeLinejoin="round"
              />
              {s.points.map((p, i) => (
                <circle
                  key={p.x}
                  cx={x(i)}
                  cy={y(magnitude(p.value.amount))}
                  r={s.emphasis ? 4 : 3}
                  fill="var(--surface)"
                  stroke={colour}
                  strokeWidth={2}
                >
                  <title>{`${s.label} — ${p.x}: ${p.value.currency} ${p.value.amount}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2">
        {series.map((s, index) => (
          <span key={s.label} className="flex items-center gap-1.5 text-[11px]">
            <span
              style={{
                width: 14,
                height: 2,
                background: s.emphasis
                  ? "var(--accent)"
                  : ["var(--warn)", "var(--heat-4)", "var(--ink-mute)"][index % 3],
                display: "inline-block",
              }}
            />
            <span style={{ color: "var(--ink-mid)" }}>{s.label}</span>
          </span>
        ))}
      </div>

      {caption && (
        <p className="m-0 mt-2 text-[11px]" style={{ color: "var(--ink-faint)" }}>
          {caption}
        </p>
      )}
    </div>
  );
}

export interface HeatCell {
  row: string;
  column: string;
  /** 0–1, already normalised by the caller against a stated basis. */
  intensity: number;
  /** What the cell actually holds, shown on hover. */
  display: string;
  title?: string;
}

/**
 * A heatmap over one sequential ramp.
 *
 * The intensity is supplied normalised, because only the caller knows what the
 * denominator should be — a concentration heatmap normalised against the wrong
 * total is a chart that lies quietly.
 */
export function Heatmap({
  cells,
  rows,
  columns,
  caption,
  rowLabel = "",
}: {
  cells: HeatCell[];
  rows: string[];
  columns: string[];
  caption?: string;
  rowLabel?: string;
}) {
  if (rows.length === 0 || columns.length === 0) {
    return (
      <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
        No data to map for this run.
      </p>
    );
  }

  const byKey = new Map(cells.map((cell) => [`${cell.row}::${cell.column}`, cell]));
  const ramp = [
    "var(--heat-0)",
    "var(--heat-1)",
    "var(--heat-2)",
    "var(--heat-3)",
    "var(--heat-4)",
    "var(--heat-5)",
    "var(--heat-6)",
  ];
  const shade = (intensity: number) =>
    ramp[Math.min(ramp.length - 1, Math.max(0, Math.round(intensity * (ramp.length - 1))))];

  return (
    <div className="px-4 py-3.5 overflow-x-auto">
      <table className="grid" style={{ minWidth: 520 }}>
        <thead>
          <tr>
            <th scope="col">{rowLabel}</th>
            {columns.map((column) => (
              <th key={column} scope="col" className="num">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row}>
              <td className="text-[11.5px]" style={{ whiteSpace: "nowrap" }}>
                {row}
              </td>
              {columns.map((column) => {
                const cell = byKey.get(`${row}::${column}`);
                return (
                  <td
                    key={column}
                    className="num"
                    style={{
                      background: cell ? shade(cell.intensity) : "transparent",
                      color: cell && cell.intensity > 0.55 ? "#08120f" : "var(--ink-mid)",
                      fontWeight: cell && cell.intensity > 0.55 ? 600 : 400,
                    }}
                    title={cell?.title ?? `${row} · ${column}`}
                  >
                    {cell ? cell.display : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex items-center gap-2 mt-3 text-[11px]" style={{ color: "var(--ink-faint)" }}>
        <span className="eyebrow">Low</span>
        <span className="flex">
          {ramp.map((colour) => (
            <span key={colour} style={{ width: 22, height: 10, background: colour }} />
          ))}
        </span>
        <span className="eyebrow">High</span>
      </div>

      {caption && (
        <p className="m-0 mt-2 text-[11px]" style={{ color: "var(--ink-faint)" }}>
          {caption}
        </p>
      )}
    </div>
  );
}

function compactNumber(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}bn`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}m`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}k`;
  return `${sign}${abs.toFixed(0)}`;
}
