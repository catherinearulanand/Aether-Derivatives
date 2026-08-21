"use client";

import { Chip, Panel, Stat } from "@/components/primitives";
import { formatMoney } from "@/lib/format";
import type { Allocation, AllocationLine } from "@/lib/types";

/**
 * The GIFT City argument, made with numbers.
 *
 * A cross-border asset can be cheaper to fund in its home market and still be the
 * wrong thing to post, because the FX haircut reduces how much of it counts as
 * collateral. This panel shows both rankings side by side and the basis-point cost
 * of the gap. Every figure comes from the optimiser; none is asserted here.
 */
export function CrossBorder({ allocation }: { allocation: Allocation | null }) {
  if (!allocation || allocation.cross_border.length === 0) return null;

  const inverted = allocation.cross_border.filter(
    (line) => line.effective_rank > line.headline_rank,
  );
  const selected = allocation.cross_border.filter((line) => line.selected);

  return (
    <Panel
      title="Cross-border collateral — IFSC economics"
      aside={
        <div className="flex items-center gap-2">
          <Chip title="Assets denominated outside the agreement's base currency.">
            {allocation.cross_border.length} non-USD assets
          </Chip>
          {inverted.length > 0 && (
            <Chip tone="warn" title="Cheaper on headline spread, dearer per unit delivered.">
              {inverted.length} ranking inversion{inverted.length > 1 ? "s" : ""}
            </Chip>
          )}
        </div>
      }
    >
      <div
        className="px-4 py-3 grid sm:grid-cols-3 gap-6"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <Stat
          label="Cross-border posted"
          value={formatMoney({
            amount: selected
              .reduce((sum, line) => sum + Number(line.effective_value.amount), 0)
              .toFixed(2),
            currency: allocation.base_currency,
          })}
          hint={`${selected.length} of ${allocation.cross_border.length} eligible, post-haircut`}
          tone={selected.length > 0 ? "accent" : "default"}
        />
        <Stat
          label="FX haircut drag"
          value={`${maxDrag(allocation.cross_border)} bp`}
          hint="highest cost per effective unit caused by FX alone"
          tone="warn"
        />
        <Stat
          label="Ranking inversions"
          value={String(inverted.length)}
          hint="cheaper on paper, dearer to deliver"
          tone={inverted.length > 0 ? "warn" : "default"}
        />
      </div>

      <div className="overflow-x-auto">
        <table className="grid">
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Ccy</th>
              <th scope="col" className="num" title="Rank by headline funding spread. 1 = cheapest on paper.">
                Rank: paper
              </th>
              <th scope="col"
                className="num"
                title="Rank by cost per effective unit. 1 = genuinely cheapest to deliver."
              >
                Rank: delivered
              </th>
              <th scope="col" className="num">Spread</th>
              <th scope="col" className="num" title="Schedule valuation × (1 − FX haircut).">
                Effective
              </th>
              <th scope="col" className="num">Cost / unit</th>
              <th scope="col" className="num" title="The portion of cost/unit caused by the FX haircut alone.">
                FX drag
              </th>
              <th scope="col">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {allocation.cross_border.map((line) => {
              const flipped = line.effective_rank > line.headline_rank;
              return (
                <tr key={line.asset_id}>
                  <td>
                    <div className="mono text-[11px]">{line.asset_id}</div>
                    <div className="text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
                      {line.description}
                    </div>
                  </td>
                  <td className="mono text-[11px]">{line.currency}</td>
                  <td className="num tnum">{line.headline_rank}</td>
                  <td className="num tnum" style={flipped ? { color: "var(--warn)" } : undefined}>
                    {line.effective_rank}
                    {flipped && " ▼"}
                  </td>
                  <td className="num tnum">{line.funding_spread_bps}bp</td>
                  <td className="num tnum">{pct(line.effective_percentage)}</td>
                  <td className="num tnum font-semibold">
                    {line.cost_per_effective_unit_bps}bp
                  </td>
                  <td className="num tnum" style={{ color: "var(--warn)" }}>
                    +{line.fx_drag_bps}bp
                  </td>
                  <td>
                    {line.selected ? (
                      <Chip tone="accent">posted</Chip>
                    ) : (
                      <span
                        className="text-[11px] leading-snug"
                        style={{ color: "var(--ink-faint)" }}
                        title={line.not_selected_reason}
                      >
                        not used
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        An IFSC banking unit funds rupee paper more cheaply at home, and the Annex
        applies an FX haircut on top of the schedule valuation because the collateral
        is not in the base currency. The optimiser prices that drag explicitly: the two
        rank columns disagree exactly where the haircut is large enough to reverse the
        ordering. This is the whole GIFT City argument, and it is arithmetic rather
        than branding.
      </p>
    </Panel>
  );
}

function pct(value: string): string {
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function maxDrag(lines: AllocationLine[]): string {
  return lines
    .reduce((worst, line) => Math.max(worst, Number(line.fx_drag_bps)), 0)
    .toFixed(2);
}
