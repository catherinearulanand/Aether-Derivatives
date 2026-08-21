"use client";

import { Chip, Delta, Panel, StatusPill } from "@/components/primitives";
import { formatDate, formatMoney } from "@/lib/format";
import type { Comparison, ComparisonMetric, ComparisonSide } from "@/lib/types";

/**
 * Before the market moved, and after.
 *
 * .. rubric:: Why this is one panel and not two screens
 *
 * The claim AETHER makes is causal: a market event moved exposure, which moved the
 * margin requirement, which moved what had to be posted. A reader cannot check a
 * causal claim by holding two screens in their head. So both states sit on one
 * surface, in the same row order, with the delta between them — and the market
 * movement is drawn as the rule that separates them, because that is what it is.
 *
 * .. rubric:: Where the arithmetic happened
 *
 * Not here. Every delta on this panel was subtracted in Python with `Decimal` and
 * arrives as a string. The browser formats it. A metric whose two sides are not
 * comparable renders "not comparable" and never a stand-in zero, because reporting
 * an unasked question as zero is the specific lie this panel must not tell.
 */
export function BeforeAfter({ comparison }: { comparison: Comparison }) {
  const headline = ["portfolio_mtm", "credit_support_amount", "call_amount"];
  const primary = comparison.metrics.filter((m) => headline.includes(m.id));
  const rest = comparison.metrics.filter((m) => !headline.includes(m.id));

  return (
    <div className="flex flex-col gap-3">
      <Panel
        title="Before market movement → after"
        aside={
          <div className="flex items-center gap-2">
            {comparison.transferor_changed && (
              <Chip
                tone="warn"
                title="The book crossed through zero: the party that owes collateral is now the other one, so their Threshold governs."
              >
                Transferor reversed
              </Chip>
            )}
            <Chip tone="accent">{comparison.metrics.length} measures</Chip>
          </div>
        }
      >
        <div className="grid lg:grid-cols-[1fr_auto_1fr] items-stretch">
          <SideHeader side={comparison.before} label="Before" />

          <div
            className="flex lg:flex-col items-center justify-center gap-2 px-5 py-4"
            style={{
              borderInline: "1px solid var(--rule)",
              background: "var(--surface-2)",
              minWidth: 150,
            }}
          >
            <span className="eyebrow text-center">Market movement</span>
            <span
              className="mono hidden lg:block"
              style={{ color: "var(--accent)", fontSize: 22, lineHeight: 1 }}
              aria-hidden="true"
            >
              ↓
            </span>
            <span
              className="mono lg:hidden"
              style={{ color: "var(--accent)", fontSize: 22 }}
              aria-hidden="true"
            >
              →
            </span>
            <span
              className="text-[11px] text-center leading-snug"
              style={{ color: "var(--ink-mute)" }}
            >
              {daysBetween(comparison.before.as_of, comparison.after.as_of)}
            </span>
          </div>

          <SideHeader side={comparison.after} label="After" emphasise />
        </div>

        {/* Three figures carry the story. They get their own band. */}
        <div
          className="grid sm:grid-cols-3 gap-px"
          style={{ background: "var(--rule)", borderBlock: "1px solid var(--rule)" }}
        >
          {primary.map((metric) => (
            <HeadlineMetric key={metric.id} metric={metric} />
          ))}
        </div>

        <div className="overflow-x-auto">
          <table className="grid">
            <thead>
              <tr>
                <th scope="col" style={{ minWidth: 240 }}>
                  Measure
                </th>
                <th scope="col" className="num">
                  Before — {comparison.before.snapshot_label}
                </th>
                <th scope="col" className="num">
                  After — {comparison.after.snapshot_label}
                </th>
                <th scope="col" className="num" style={{ width: 200 }}>
                  Change
                </th>
              </tr>
            </thead>
            <tbody>
              {rest.map((metric) => (
                <tr key={metric.id} title={metric.basis}>
                  <td>
                    <div className="text-[12px]">{metric.label}</div>
                    <div
                      className="text-[10.5px] leading-snug mt-0.5"
                      style={{ color: "var(--ink-faint)", maxWidth: "58ch" }}
                    >
                      {metric.basis}
                    </div>
                  </td>
                  <td className="num" style={{ color: "var(--ink-mid)" }}>
                    {metric.before_available ? (
                      formatMoney(metric.before)
                    ) : (
                      <span style={{ color: "var(--ink-faint)" }}>not computed</span>
                    )}
                  </td>
                  <td className="num">
                    {metric.after_available ? (
                      formatMoney(metric.after)
                    ) : (
                      <span style={{ color: "var(--ink-faint)" }}>not computed</span>
                    )}
                  </td>
                  <td className="num">
                    <Delta
                      value={metric.delta}
                      direction={metric.direction}
                      unavailable={metric.unavailable_reason}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p
          className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
          style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
        >
          {comparison.method} Two measures show &ldquo;not computed&rdquo; on the
          quiet-market side: no Delivery Amount was due there, so the optimiser was
          never invoked. That is a different statement from a figure of zero, and
          the panel refuses to conflate them.
        </p>
      </Panel>

      <AllocationResponse comparison={comparison} />
    </div>
  );
}

function SideHeader({
  side,
  label,
  emphasise = false,
}: {
  side: ComparisonSide;
  label: string;
  emphasise?: boolean;
}) {
  return (
    <div
      className="px-4 py-3.5 flex flex-col gap-2"
      style={emphasise ? { background: "var(--surface-2)" } : undefined}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow">{label}</span>
        <Chip>{side.snapshot_id}</Chip>
        <span className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
          {formatDate(side.as_of)}
        </span>
      </div>

      <h3
        className="serif m-0 leading-tight"
        style={{ fontSize: 18, fontWeight: 700 }}
      >
        {side.snapshot_label}
      </h3>

      <p
        className="m-0 text-[11.5px] leading-snug"
        style={{ color: "var(--ink-mute)", maxWidth: "52ch" }}
      >
        {side.summary}
      </p>

      <div className="flex flex-wrap items-center gap-2 mt-0.5">
        <StatusPill
          state={side.threshold_status.state}
          title={side.threshold_status.message}
        />
        <Chip>{side.decision.replace(/_/g, " ")}</Chip>
        <Chip title="Which party owes collateral under this snapshot.">
          {side.transferor.replace("_", " ")}
        </Chip>
      </div>
    </div>
  );
}

function HeadlineMetric({ metric }: { metric: ComparisonMetric }) {
  return (
    <div
      className="px-4 py-3.5 flex flex-col gap-1.5"
      style={{ background: "var(--surface)" }}
      title={metric.basis}
    >
      <span className="eyebrow">{metric.label}</span>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span
          className="tnum"
          style={{ fontSize: 12.5, color: "var(--ink-faint)" }}
        >
          {metric.before_available ? formatMoney(metric.before) : "—"}
        </span>
        <span className="mono" style={{ color: "var(--ink-faint)", fontSize: 10 }}>
          →
        </span>
        <span
          className="tnum font-semibold"
          style={{ fontSize: 17, overflowWrap: "anywhere" }}
        >
          {metric.after_available ? formatMoney(metric.after) : "—"}
        </span>
      </div>
      <Delta
        value={metric.delta}
        direction={metric.direction}
        unavailable={metric.unavailable_reason}
      />
    </div>
  );
}

/**
 * How the optimiser responded.
 *
 * The market moved and the requirement moved with it; this table is what the
 * optimiser did about it, asset by asset. Every row is classified against the
 * baseline allocation rather than described in prose.
 */
function AllocationResponse({ comparison }: { comparison: Comparison }) {
  const rows = comparison.allocation_delta;

  if (rows.length === 0) {
    return (
      <Panel title="How the optimiser responded">
        <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
          Neither snapshot required a collateral delivery, so the optimiser did not
          run on either side. There is no allocation change to show.
        </p>
      </Panel>
    );
  }

  const tone = (status: string) =>
    status === "ADDED"
      ? "accent"
      : status === "REMOVED"
        ? "crit"
        : status === "UNCHANGED"
          ? "default"
          : "warn";

  return (
    <Panel
      title="How the optimiser responded"
      aside={
        <div className="flex items-center gap-2">
          <Chip>{comparison.before.asset_count} assets before</Chip>
          <Chip tone="accent">{comparison.after.asset_count} after</Chip>
        </div>
      }
    >
      <div className="overflow-x-auto">
        <table className="grid">
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Class</th>
              <th scope="col" className="num">
                Posted before
              </th>
              <th scope="col" className="num">
                Posted after
              </th>
              <th scope="col" className="num">
                Change
              </th>
              <th scope="col" style={{ width: 130 }}>
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.asset_id}>
                <td>
                  <div className="mono text-[11.5px]">{row.asset_id}</div>
                  <div className="text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
                    {row.description}
                  </div>
                </td>
                <td className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
                  {row.asset_class.replace(/_/g, " ").toLowerCase()}
                </td>
                <td className="num" style={{ color: "var(--ink-mid)" }}>
                  {formatMoney(row.before)}
                </td>
                <td className="num">{formatMoney(row.after)}</td>
                <td className="num">
                  <Delta
                    value={row.delta}
                    direction={
                      row.status === "UNCHANGED"
                        ? "FLAT"
                        : row.delta.amount.startsWith("-")
                          ? "DOWN"
                          : "UP"
                    }
                  />
                </td>
                <td>
                  <Chip tone={tone(row.status)}>{row.status.toLowerCase()}</Chip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Market values posted, before haircut. Each row compares the two solved
        allocations directly — the optimiser was re-run against the new
        requirement rather than the old allocation being scaled up.
      </p>
    </Panel>
  );
}

/** Elapsed calendar days between two pinned valuation dates. */
function daysBetween(before: string, after: string): string {
  const from = Date.parse(`${before}T00:00:00Z`);
  const to = Date.parse(`${after}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) return "";
  const days = Math.round((to - from) / 86_400_000);
  return days === 1 ? "1 calendar day" : `${days} calendar days`;
}
