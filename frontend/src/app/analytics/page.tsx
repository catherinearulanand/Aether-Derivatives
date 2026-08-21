"use client";

import {
  ChangeChart,
  Composition,
  Heatmap,
  RankedBars,
  type HeatCell,
} from "@/components/Charts";
import { Chip, ErrorPanel, Panel, Skeleton, Stat } from "@/components/primitives";
import { formatMoney } from "@/lib/format";
import { useComparison, useRun } from "@/lib/hooks";
import { useAether } from "@/lib/store";
import type { Allocation, Money, RunResult } from "@/lib/types";

/**
 * Analytics.
 *
 * .. rubric:: Every chart answers a stated question
 *
 * A dashboard of charts that look impressive and answer nothing is worse than no
 * charts, because it costs the reader time and returns opinion. Each panel here
 * carries the question it exists to answer in its title strip, and every mark is
 * drawn from a figure the engine returned for a pinned snapshot.
 *
 * .. rubric:: Where the series come from
 *
 * The trend charts plot the three pinned snapshots. Three points is what this
 * system has observed, so three points is what is drawn — no smoothing, no
 * projection, no interpolated path between two valuation dates.
 */
export default function AnalyticsPage() {
  const currentKey = useAether((s) => s.currentKey);
  const comparison = useComparison();

  // All three snapshots, so the trend panels have a series rather than a point.
  // Each is the same cached query the rest of the app reads.
  const base = useRun("base");
  const stress = useRun("stress");
  const crash = useRun("crash");

  const runs = [base, stress, crash];
  const loading = runs.some((r) => r.isLoading);
  const failed = runs.find((r) => r.isError);
  const current = runs.find((r) => r.data?.scenario?.key === currentKey)?.data;

  if (failed) {
    return (
      <div className="p-4 max-w-[1500px] mx-auto">
        <ErrorPanel error={failed.error} />
      </div>
    );
  }

  const series = runs
    .map((r) => r.data)
    .filter((r): r is RunResult => Boolean(r))
    .sort((a, b) => a.as_of.localeCompare(b.as_of));

  return (
    <div className="p-4 max-w-[1500px] mx-auto flex flex-col gap-3">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <h1 className="serif m-0 text-[25px] font-bold leading-tight">Analytics</h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "84ch" }}
          >
            Six questions about this book and the collateral behind it, each
            answered from the engine&apos;s own output across the three pinned
            snapshots.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Chip tone="warn">Simulated data</Chip>
          <Chip>{series.length} snapshots</Chip>
        </div>
      </header>

      {loading || series.length === 0 ? (
        <>
          <Panel title="Exposure and margin across snapshots">
            <Skeleton rows={5} height={20} />
          </Panel>
          <Panel title="Collateral allocation">
            <Skeleton rows={5} />
          </Panel>
        </>
      ) : (
        <>
          <Headline series={series} current={current} />

          <div className="grid xl:grid-cols-2 gap-3 items-start">
            <Panel
              title="How did the market movement affect exposure?"
              aside={<Chip tone="accent">3 pinned snapshots</Chip>}
            >
              <ChangeChart
                series={[
                  {
                    label: "Net exposure",
                    emphasis: true,
                    points: series.map((run) => ({
                      x: run.snapshot.label,
                      value: run.exposure.exposure,
                    })),
                  },
                  {
                    label: "Gross positive value",
                    points: series.map((run) => ({
                      x: run.snapshot.label,
                      value: run.exposure.gross_positive,
                    })),
                  },
                ]}
                caption={
                  "Net exposure crosses zero between the rate shock and the flash " +
                  "crash: the book moves from out of the money to in the money, " +
                  "which is what reverses who owes collateral."
                }
              />
            </Panel>

            <Panel
              title="How did the margin requirement move with it?"
              aside={<Chip>Credit Support Amount and transfer</Chip>}
            >
              <ChangeChart
                series={[
                  {
                    label: "Credit Support Amount",
                    emphasis: true,
                    points: series.map((run) => ({
                      x: run.snapshot.label,
                      value: run.margin_call.credit_support_amount,
                    })),
                  },
                  {
                    label: "Transfer required",
                    points: series.map((run) => ({
                      x: run.snapshot.label,
                      value: run.margin_call.call_amount,
                    })),
                  },
                  {
                    label: "Threshold",
                    points: series.map((run) => ({
                      x: run.snapshot.label,
                      value: run.margin_call.threshold,
                    })),
                  },
                ]}
                caption={
                  "The Threshold line steps down at the flash crash because the " +
                  "Transferor changes: Party B's ratings-contingent Threshold is " +
                  "lower than Party A's."
                }
              />
            </Panel>
          </div>

          {current?.allocation ? (
            <>
              <div className="grid xl:grid-cols-2 gap-3 items-start">
                <Panel
                  title="Which collateral assets are being used?"
                  aside={
                    <Chip tone="accent">
                      {current.allocation.lines.length} of{" "}
                      {current.allocation.considered.length} eligible
                    </Chip>
                  }
                >
                  <RankedBars
                    data={current.allocation.lines
                      .slice()
                      .sort(
                        (a, b) =>
                          Number(b.effective_value.amount) -
                          Number(a.effective_value.amount),
                      )
                      .map((line) => ({
                        label: line.asset_id,
                        sublabel: line.description,
                        value: line.effective_value,
                        emphasis: true,
                        title: `${line.cost_per_effective_unit_bps}bp per effective unit`,
                      }))}
                    caption="Post-haircut collateral value delivered by each selected asset."
                    emptyMessage="No allocation ran at this snapshot."
                  />
                </Panel>

                <Panel
                  title="Which assets carry the most concentration?"
                  aside={<Chip tone="warn">against the Annex caps</Chip>}
                >
                  <Composition
                    slices={byClass(current.allocation)}
                    total={current.allocation.allocated_value}
                    caption={
                      "Share of the Credit Support Balance by asset class. The " +
                      "concentration caps in Paragraph 11(g) are what stop any " +
                      "single class filling the requirement on its own."
                    }
                  />
                </Panel>
              </div>

              <Panel
                title="What does each eligible asset cost, and why was it or was it not used?"
                aside={<Chip>{current.allocation.considered.length} eligible assets</Chip>}
              >
                <Heatmap
                  rowLabel="Asset"
                  rows={current.allocation.considered.map((l) => l.asset_id)}
                  columns={["Effective %", "Spread (bp)", "Cost / unit (bp)", "FX drag (bp)", "Posted"]}
                  cells={costHeatmap(current.allocation)}
                  caption={
                    "Cost per effective unit is the ranking that decides the " +
                    "allocation: funding spread divided by the proportion of an " +
                    "asset's value that actually counts as collateral. Intensity " +
                    "is scaled within each column, because the columns are in " +
                    "different units and a shared scale across them would be " +
                    "meaningless."
                  }
                />
              </Panel>

              <div className="grid xl:grid-cols-2 gap-3 items-start">
                <Panel
                  title="What did the optimiser save against a cash-first desk?"
                  aside={
                    <Chip tone={current.allocation.baseline_covers_requirement ? "accent" : "warn"}>
                      {current.allocation.baseline_covers_requirement
                        ? `${Number(current.allocation.saving_percentage).toFixed(1)}% lower`
                        : "not comparable"}
                    </Chip>
                  }
                >
                  <RankedBars
                    data={[
                      {
                        label: "Cash-first baseline",
                        sublabel: "exhaust cash, then sovereigns, ignoring cost",
                        value: current.allocation.baseline_cost,
                      },
                      {
                        label: "Optimised",
                        sublabel: "cheapest to deliver, all caps respected",
                        value: current.allocation.total_cost,
                        emphasis: true,
                      },
                    ]}
                    caption="Annual funding cost of encumbering the selected assets."
                  />
                  {!current.allocation.baseline_covers_requirement && (
                    <p
                      className="px-4 pb-3 m-0 text-[11.5px]"
                      style={{ color: "var(--warn)" }}
                    >
                      The baseline could not meet the requirement from cash and
                      sovereigns alone, so the two costs are not measuring the same
                      thing and the saving is not claimed.
                    </p>
                  )}
                </Panel>

                <Panel
                  title="What is each binding constraint costing?"
                  aside={
                    <Chip tone="accent">
                      {current.allocation.shadow_prices.filter((s) => s.binding).length}{" "}
                      binding
                    </Chip>
                  }
                >
                  <RankedBars
                    data={current.allocation.shadow_prices
                      .filter((price) => price.binding)
                      .map((price) => ({
                        label: price.name.replace(/^(concentration|issuer):/, ""),
                        sublabel: price.description,
                        value: {
                          amount: price.shadow_price_bps,
                          currency: "bp",
                        } as Money,
                        emphasis: true,
                      }))}
                    emptyMessage="No constraint binds at this allocation, so none is costing anything."
                    caption={
                      "Dual values from the solver, in basis points. A binding " +
                      "constraint's shadow price is what relaxing it by one unit " +
                      "would save on the objective."
                    }
                  />
                </Panel>
              </div>
            </>
          ) : (
            <Panel title="Collateral allocation">
              <p
                className="px-4 py-6 m-0 text-[12.5px]"
                style={{ color: "var(--ink-mute)" }}
              >
                The current snapshot produced no allocation — no Delivery Amount was
                due, or the counterparty owes the collateral and selects it
                themselves. Switch to the rate shock snapshot to see the allocation
                analytics.
              </p>
            </Panel>
          )}

          {comparison.data && (
            <Panel
              title="How did the optimiser change the allocation?"
              aside={
                <Chip>
                  {comparison.data.before.snapshot_label} →{" "}
                  {comparison.data.after.snapshot_label}
                </Chip>
              }
            >
              <RankedBars
                data={comparison.data.allocation_delta.map((row) => ({
                  label: row.asset_id,
                  sublabel: `${row.status.toLowerCase()} — ${row.description}`,
                  value: row.delta,
                  emphasis: row.status === "ADDED" || row.status === "INCREASED",
                }))}
                emptyMessage="Neither snapshot required an allocation, so nothing changed."
                caption="Change in market value posted, by asset, between the two snapshots."
              />
            </Panel>
          )}

          <p
            className="m-0 px-1 text-[11.5px] leading-relaxed"
            style={{ color: "var(--ink-faint)" }}
          >
            Every figure on this page was computed by the deterministic engine for a
            pinned, simulated snapshot. Nothing is projected, smoothed or
            interpolated: a line between two points connects two observations and
            says nothing about the path between them. There is no live market data
            anywhere in this system.
          </p>
        </>
      )}
    </div>
  );
}

function Headline({
  series,
  current,
}: {
  series: RunResult[];
  current: RunResult | undefined;
}) {
  const withCalls = series.filter((run) => run.margin_call.direction !== "NONE");

  return (
    <Panel title="Across the three snapshots">
      <div className="px-4 py-3.5 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-5 gap-x-6 gap-y-4">
        <Stat
          label="Snapshots analysed"
          value={String(series.length)}
          hint={series.map((s) => s.snapshot.label).join(" · ")}
        />
        <Stat
          label="Snapshots with a call"
          value={`${withCalls.length} of ${series.length}`}
          hint="Threshold and MTA gated the rest"
          tone={withCalls.length > 0 ? "warn" : "default"}
        />
        <Stat
          label="Largest transfer"
          value={formatMoney(
            withCalls
              .map((r) => r.margin_call.call_amount)
              .reduce(
                (best, value) =>
                  Number(value.amount) > Number(best.amount) ? value : best,
                { amount: "0", currency: series[0].exposure.base_currency },
              ),
          )}
          hint="across all three snapshots"
        />
        <Stat
          label="Transferor reversals"
          value={String(
            new Set(series.map((r) => r.margin_call.transferor)).size - 1,
          )}
          hint="the book crossing through zero"
        />
        <Stat
          label="Current optimisation"
          value={current?.allocation?.status ?? "not required"}
          hint={
            current?.allocation
              ? `${formatMoney(current.allocation.saving)} saved on this call`
              : "no allocation at this snapshot"
          }
          tone={current?.allocation ? "accent" : "default"}
        />
      </div>
    </Panel>
  );
}

function byClass(allocation: Allocation) {
  const groups = new Map<string, { amount: number; currency: string }>();
  for (const line of allocation.lines) {
    const key = line.asset_class.replace(/_/g, " ").toLowerCase();
    const existing = groups.get(key);
    groups.set(key, {
      amount: (existing?.amount ?? 0) + Number(line.effective_value.amount),
      currency: line.effective_value.currency,
    });
  }
  return [...groups.entries()]
    .sort((a, b) => b[1].amount - a[1].amount)
    .map(([label, group]) => ({
      label,
      value: { amount: group.amount.toFixed(2), currency: group.currency },
    }));
}

/**
 * The cost heatmap.
 *
 * Intensity is normalised **within each column**, because the columns are in
 * different units — a percentage, two basis-point figures and a monetary amount.
 * Normalising across the whole grid would make the largest column the only visible
 * one and would say nothing true.
 */
function costHeatmap(allocation: Allocation): HeatCell[] {
  const lines = allocation.considered;

  const columns: {
    name: string;
    read: (line: Allocation["considered"][number]) => number;
    display: (line: Allocation["considered"][number]) => string;
    invert?: boolean;
  }[] = [
    {
      name: "Effective %",
      read: (l) => Number(l.effective_percentage),
      display: (l) => `${(Number(l.effective_percentage) * 100).toFixed(1)}%`,
    },
    {
      name: "Spread (bp)",
      read: (l) => Number(l.funding_spread_bps),
      display: (l) => Number(l.funding_spread_bps).toFixed(0),
    },
    {
      name: "Cost / unit (bp)",
      read: (l) => Number(l.cost_per_effective_unit_bps),
      display: (l) => Number(l.cost_per_effective_unit_bps).toFixed(2),
    },
    {
      name: "FX drag (bp)",
      read: (l) => Number(l.fx_drag_bps),
      display: (l) => Number(l.fx_drag_bps).toFixed(2),
    },
    {
      name: "Posted",
      read: (l) => Number(l.market_value_posted.amount),
      display: (l) =>
        Number(l.market_value_posted.amount) === 0
          ? "—"
          : formatMoney(l.market_value_posted),
    },
  ];

  const cells: HeatCell[] = [];
  for (const column of columns) {
    const values = lines.map(column.read);
    const max = Math.max(...values, 0);
    const min = Math.min(...values, 0);
    const span = max - min || 1;

    lines.forEach((line, index) => {
      cells.push({
        row: line.asset_id,
        column: column.name,
        intensity: (values[index] - min) / span,
        display: column.display(line),
        title:
          `${line.description}\n${column.name}: ${column.display(line)}` +
          (line.selected ? "\nSelected by the optimiser." : `\n${line.not_selected_reason}`),
      });
    });
  }
  return cells;
}
