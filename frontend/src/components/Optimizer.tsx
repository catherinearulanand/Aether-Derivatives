"use client";

import { formatBps, formatMoney, formatPercent, formatPercentPoints } from "@/lib/format";
import type { Allocation } from "@/lib/types";
import { Chip, Panel, Stat } from "./primitives";

/**
 * The collateral optimizer.
 *
 * Three things are on screen at once, and all three matter:
 *
 *  1. What the optimizer chose, ranked by **cost per effective unit** — the metric
 *     that explains why the cheapest headline asset is not always picked.
 *  2. What it cost against the cash-first heuristic a desk would otherwise run.
 *     The saving is measured, not asserted.
 *  3. Which constraints bind, and what they cost at the margin. Those are LP dual
 *     values; they come free from the solver and turn "here is an allocation" into
 *     "here is what your concentration cap is costing you".
 */
export function Optimizer({ allocation }: { allocation: Allocation | null }) {
  if (!allocation) {
    return (
      <Panel title="Collateral optimisation">
        <div className="px-4 py-8 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
          No allocation required — no Delivery Amount is due under this snapshot.
        </div>
      </Panel>
    );
  }

  if (allocation.status !== "OPTIMAL") {
    return (
      <Panel
        title="Collateral optimisation"
        aside={<Chip tone="crit">{allocation.status}</Chip>}
      >
        <div className="px-4 py-6 text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
          {allocation.message}
        </div>
      </Panel>
    );
  }

  const binding = allocation.shadow_prices.filter((s) => s.binding);

  return (
    <div className="flex flex-col gap-3">
      <Panel
        title="Collateral optimisation — cheapest to deliver"
        aside={<Chip tone="accent">Linear program · HiGHS</Chip>}
      >
        <div
          className="grid grid-cols-2 md:grid-cols-4 gap-5 px-4 py-3.5"
          style={{ borderBottom: "1px solid var(--rule)" }}
        >
          <Stat
            label="Optimised cost"
            value={formatMoney(allocation.total_cost)}
            hint="per annum, funding cost of encumbrance"
            tone="accent"
          />
          <Stat
            label="Cash-first baseline"
            value={formatMoney(allocation.baseline_cost)}
            hint="what a desk without an optimizer pays"
          />
          <Stat
            label="Saving"
            value={
              allocation.baseline_covers_requirement
                ? formatMoney(allocation.saving)
                : "not comparable"
            }
            hint={
              allocation.baseline_covers_requirement
                ? `${formatPercentPoints(allocation.saving_percentage)} lower on this call`
                : "cash and sovereigns alone could not cover the requirement"
            }
            tone={allocation.baseline_covers_requirement ? "accent" : "warn"}
          />
          <Stat
            label="Post-haircut delivered"
            value={formatMoney(allocation.allocated_value)}
            hint={`against ${formatMoney(allocation.required_value)} required`}
          />
        </div>

        <div className="overflow-x-auto">
          <table className="grid">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Class</th>
                <th className="num">Posted (market value)</th>
                <th className="num">Effective %</th>
                <th className="num">Collateral value</th>
                <th className="num">Spread</th>
                <th className="num">Cost / effective unit</th>
                <th className="num">Annual cost</th>
              </tr>
            </thead>
            <tbody>
              {allocation.lines.map((line) => (
                <tr key={line.asset_id}>
                  <td>
                    <div className="mono text-[11.5px]">{line.asset_id}</div>
                    <div className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
                      {line.description}
                    </div>
                  </td>
                  <td>
                    <div className="flex flex-col gap-1 items-start">
                      <Chip>{line.asset_class.replace(/_/g, " ").toLowerCase()}</Chip>
                      {line.fx_haircut_applied && (
                        <Chip tone="warn" title="Non-base currency: 8% FX haircut applied on top of the schedule percentage.">
                          FX haircut
                        </Chip>
                      )}
                    </div>
                  </td>
                  <td className="num">{formatMoney(line.market_value_posted)}</td>
                  <td className="num" style={{ color: "var(--ink-mid)" }}>
                    {formatPercent(line.effective_percentage)}
                  </td>
                  <td className="num">{formatMoney(line.effective_value)}</td>
                  <td className="num" style={{ color: "var(--ink-mute)" }}>
                    {formatBps(line.funding_spread_bps, 0)}
                  </td>
                  <td
                    className="num"
                    style={{ color: "var(--accent)", fontWeight: 600 }}
                    title="funding spread ÷ effective valuation percentage — the ranking that decides the allocation"
                  >
                    {formatBps(line.cost_per_effective_unit_bps)}
                  </td>
                  <td className="num">{formatMoney(line.annual_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p
          className="px-4 py-2.5 m-0 text-[11.5px]"
          style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
        >
          Ranked by cost per effective unit, not by headline spread. An asset with a
          low funding spread and a heavy haircut delivers less collateral per unit
          encumbered, and the optimizer prices that difference.
        </p>
      </Panel>

      <div className="grid lg:grid-cols-2 gap-3">
        <Panel
          title="Binding constraints — shadow prices"
          aside={<Chip tone="accent">{binding.length} binding</Chip>}
        >
          <table className="grid">
            <thead>
              <tr>
                <th>Constraint</th>
                <th className="num">Marginal cost</th>
              </tr>
            </thead>
            <tbody>
              {allocation.shadow_prices.map((price) => (
                <tr key={price.name} style={{ opacity: price.binding ? 1 : 0.45 }}>
                  <td>
                    <div className="flex items-center gap-2">
                      {price.binding && <Chip tone="accent">binds</Chip>}
                      <span className="text-[12px]">{price.description}</span>
                    </div>
                  </td>
                  <td
                    className="num"
                    style={{ color: price.binding ? "var(--accent)" : "var(--ink-faint)" }}
                  >
                    {formatBps(price.shadow_price_bps)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p
            className="px-4 py-2.5 m-0 text-[11.5px]"
            style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
          >
            Dual values from the solver. A binding constraint&apos;s shadow price is what
            relaxing it by one unit would save. A non-binding constraint costs nothing.
          </p>
        </Panel>

        <div className="flex flex-col gap-3">
          <Panel title="Cash-first baseline (what this is measured against)">
            <table className="grid">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th className="num">Posted</th>
                  <th className="num">Annual cost</th>
                </tr>
              </thead>
              <tbody>
                {allocation.baseline_lines.map((line) => (
                  <tr key={line.asset_id}>
                    <td className="mono text-[11.5px]">{line.asset_id}</td>
                    <td className="num">{formatMoney(line.market_value_posted)}</td>
                    <td className="num">{formatMoney(line.annual_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p
              className="px-4 py-2.5 m-0 text-[11.5px]"
              style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
            >
              Exhaust cash, then sovereigns by ascending maturity, ignoring cost. Cash
              carries the highest opportunity cost, which is why this is expensive.
            </p>
          </Panel>

          {allocation.excluded.length > 0 && (
            <Panel
              title="Excluded from the eligible set"
              aside={<Chip tone="crit">{allocation.excluded.length}</Chip>}
            >
              <div className="px-4 py-3 flex flex-col gap-2.5">
                {allocation.excluded.map((item) => (
                  <div key={item.asset_id} className="text-[12px]">
                    <span className="mono" style={{ color: "var(--crit)" }}>
                      {item.asset_id}
                    </span>
                    <div style={{ color: "var(--ink-mid)" }}>{item.reason}</div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </div>
      </div>

      <NotSelected allocation={allocation} />
    </div>
  );
}

/**
 * Why each eligible asset was or was not used.
 *
 * "Why that one and not this one?" is the question a collateral desk asks every day.
 * An optimizer that cannot answer it is a black box, so every eligible asset appears
 * here with its two rankings and, when unused, the reason drawn from the solved
 * problem rather than guessed at.
 */
function NotSelected({ allocation }: { allocation: Allocation }) {
  const rejected = allocation.considered.filter((line) => !line.selected);
  if (rejected.length === 0) return null;

  return (
    <Panel
      title="Considered and not used"
      aside={
        <Chip>
          {rejected.length} of {allocation.considered.length} eligible
        </Chip>
      }
    >
      <div className="overflow-x-auto">
        <table className="grid">
          <thead>
            <tr>
              <th>Asset</th>
              <th className="num">Available</th>
              <th className="num">Effective %</th>
              <th className="num">Cost / effective unit</th>
              <th>Why it was not used</th>
            </tr>
          </thead>
          <tbody>
            {rejected.map((line) => (
              <tr key={line.asset_id}>
                <td>
                  <div className="mono text-[11.5px]">{line.asset_id}</div>
                  <div className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
                    {line.description}
                  </div>
                </td>
                <td className="num">
                  {line.available_market_value
                    ? formatMoney(line.available_market_value)
                    : "—"}
                </td>
                <td className="num" style={{ color: "var(--ink-mid)" }}>
                  {formatPercent(line.effective_percentage)}
                </td>
                <td className="num" style={{ color: "var(--ink-mute)" }}>
                  {formatBps(line.cost_per_effective_unit_bps)}
                </td>
                <td className="text-[11.5px] leading-snug" style={{ color: "var(--ink-mid)" }}>
                  {line.not_selected_reason}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p
        className="px-4 py-2.5 m-0 text-[11.5px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Reasons are read from the solved problem: either a cap that applies to the
        asset is binding, or it costs more per unit of collateral actually delivered
        than everything that filled the requirement.
      </p>
    </Panel>
  );
}
