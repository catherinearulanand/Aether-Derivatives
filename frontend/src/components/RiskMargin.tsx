"use client";

import { Amount, Chip, Panel, Stat } from "@/components/primitives";
import { formatMoney } from "@/lib/format";
import type { InitialMargin, SensitivityMargin } from "@/lib/types";
import { useState } from "react";

/**
 * Two initial margin figures, side by side, neither charged to the variation call.
 *
 * The schedule number is a published grid applied to notional. The sensitivity
 * number is measured risk: every curve pillar bumped, the book repriced, the results
 * risk-weighted and aggregated through correlations. They disagree, and the
 * disagreement is the interesting part — a notional-based grid cannot see that a
 * book is hedged.
 */
export function RiskMargin({
  sensitivity,
  schedule,
}: {
  sensitivity: SensitivityMargin;
  schedule: InitialMargin;
}) {
  const [open, setOpen] = useState(false);

  const sens = Number(sensitivity.total_margin.amount);
  const sched = Number(schedule.initial_margin.amount);
  const ratio = sched > 0 ? sens / sched : 0;

  return (
    <Panel
      title="Initial margin — two methods"
      aside={<Chip tone="warn">Indicative. Not charged to the VM call.</Chip>}
    >
      <div
        className="grid sm:grid-cols-2 gap-px"
        style={{ background: "var(--rule)", borderBottom: "1px solid var(--rule)" }}
      >
        <div className="px-4 py-3.5 flex flex-col gap-3" style={{ background: "var(--surface)" }}>
          <div className="flex items-center gap-2">
            <span className="eyebrow">Risk-weighted sensitivities</span>
            <Chip tone="accent">measured</Chip>
          </div>
          <Stat
            label="Total margin"
            value={formatMoney(sensitivity.total_margin)}
            hint={`${sensitivity.sensitivities.length} material sensitivities, ${sensitivity.buckets.length} buckets`}
            tone="accent"
          />
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Rates" value={formatMoney(sensitivity.interest_rate_margin)} />
            <Stat label="FX" value={formatMoney(sensitivity.fx_margin)} />
            <Stat
              label="Vega"
              value={formatMoney(sensitivity.vega_margin)}
              hint="no optionality"
            />
          </div>
        </div>

        <div className="px-4 py-3.5 flex flex-col gap-3" style={{ background: "var(--surface)" }}>
          <div className="flex items-center gap-2">
            <span className="eyebrow">BCBS-IOSCO standardised schedule</span>
            <Chip>notional × grid</Chip>
          </div>
          <Stat
            label="Schedule IM"
            value={formatMoney(schedule.initial_margin)}
            hint={`net-to-gross ${Number(schedule.net_to_gross_ratio).toFixed(2)}, gross ${formatMoney(schedule.gross_im)}`}
          />
          <p className="m-0 text-[11.5px] leading-snug" style={{ color: "var(--ink-mute)" }}>
            {ratio > 0 && (
              <>
                The sensitivity model returns{" "}
                <strong style={{ color: "var(--ink)" }}>
                  {(ratio * 100).toFixed(0)}%
                </strong>{" "}
                of the schedule figure. A grid applied to notional cannot see that a
                book is partly hedged; measured risk can.
              </>
            )}
          </p>
        </div>
      </div>

      <button
        onClick={() => setOpen((value) => !value)}
        className="w-full text-left px-4 py-2 text-[11.5px]"
        style={{ background: "transparent", border: "none", color: "var(--accent)" }}
      >
        {open ? "▾ Hide" : "▸ Show"} the {sensitivity.sensitivities.length} sensitivities
        behind this figure
      </button>

      {open && (
        <div className="overflow-x-auto" style={{ borderTop: "1px solid var(--rule)" }}>
          <table className="grid">
            <thead>
              <tr>
                <th scope="col">Risk factor</th>
                <th scope="col">Class</th>
                <th scope="col" className="num" title="PV change for a 1bp curve bump, or a 1% FX move.">
                  Sensitivity
                </th>
                <th scope="col" className="num" title="AETHER's own risk weight. Not calibrated, not certified.">
                  Weight
                </th>
                <th scope="col" className="num">Weighted</th>
              </tr>
            </thead>
            <tbody>
              {sensitivity.sensitivities.map((s) => (
                <tr key={`${s.bucket}-${s.label}`}>
                  <td className="mono text-[11px]">{s.label}</td>
                  <td className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
                    {s.risk_class === "INTEREST_RATE" ? "rates" : "fx"}
                  </td>
                  <td className="num">
                    <Amount value={s.value} />
                  </td>
                  <td className="num tnum" style={{ color: "var(--ink-mute)" }}>
                    {s.risk_weight}
                  </td>
                  <td className="num">
                    <Amount value={s.weighted_value} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="overflow-x-auto" style={{ borderTop: "1px solid var(--rule)" }}>
            <table className="grid">
              <thead>
                <tr>
                  <th scope="col">Bucket</th>
                  <th scope="col" className="num">Sensitivities</th>
                  <th scope="col" className="num">Weighted sum</th>
                  <th scope="col" className="num" title="sqrt(w' R w) — correlated aggregation within the bucket.">
                    Bucket margin
                  </th>
                </tr>
              </thead>
              <tbody>
                {sensitivity.buckets.map((bucket) => (
                  <tr key={`${bucket.risk_class}-${bucket.bucket}`}>
                    <td className="mono text-[11px]">{bucket.bucket}</td>
                    <td className="num tnum">{bucket.sensitivity_count}</td>
                    <td className="num">
                      <Amount value={bucket.weighted_sum} />
                    </td>
                    <td className="num">
                      <Amount value={bucket.margin} signed={false} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        {sensitivity.disclaimer} {sensitivity.vega_note} Sensitivities are measured by
        full revaluation — the pricing engine is called again against a perturbed
        market state — rather than by a closed-form approximation.
      </p>
    </Panel>
  );
}
