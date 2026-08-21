"use client";

import { RiskMargin } from "@/components/RiskMargin";
import { Waterfall } from "@/components/Waterfall";
import {
  Amount,
  Chip,
  ErrorPanel,
  Panel,
  Skeleton,
  Stat,
  StatusLegend,
  StatusPill,
} from "@/components/primitives";
import { formatMoney } from "@/lib/format";
import { useCurrentRun } from "@/lib/hooks";
import type { RunResult } from "@/lib/types";

/**
 * Exposure & margin.
 *
 * The two stages that turn a book of trades into an amount of money someone owes:
 * mark-to-market with netting, then the CSA waterfall through Threshold, MTA and
 * rounding. Both were previously crowded onto the dashboard, where the waterfall
 * had to compete with the optimiser for attention; here each has room to be read.
 */
export default function ExposurePage() {
  const run = useCurrentRun();

  if (run.isError) {
    return (
      <div className="p-4 max-w-[1500px] mx-auto">
        <ErrorPanel error={run.error} />
      </div>
    );
  }

  return (
    <div className="p-4 max-w-[1500px] mx-auto flex flex-col gap-3">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <h1 className="serif m-0 text-[25px] font-bold leading-tight">
            Exposure &amp; margin
          </h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "82ch" }}
          >
            Every trade repriced against the pinned snapshot, netted within one
            netting set, then carried through the Annex to a transfer amount. Each
            step names the paragraph it comes from.
          </p>
        </div>
        {run.data && (
          <div className="ml-auto flex items-center gap-2">
            <StatusPill
              state={run.data.threshold_status.state}
              title={run.data.threshold_status.message}
            />
            <Chip>{run.data.snapshot.snapshot_id}</Chip>
          </div>
        )}
      </header>

      {run.isLoading || !run.data ? (
        <>
          <Panel title="Margin waterfall">
            <Skeleton rows={6} />
          </Panel>
        </>
      ) : (
        <>
          <ThresholdBand run={run.data} />

          <div className="grid xl:grid-cols-[minmax(0,1fr)_minmax(0,440px)] gap-3 items-start">
            <Waterfall call={run.data.margin_call} />
            <ExposurePanel run={run.data} />
          </div>

          <RiskMargin
            sensitivity={run.data.sensitivity_margin}
            schedule={run.data.initial_margin}
          />
        </>
      )}
    </div>
  );
}

/**
 * Where this run sits against the Threshold, with the two gates named.
 *
 * A bar is used rather than a gauge because the reader needs to compare two
 * amounts on the same scale — exposure against Threshold — and a gauge makes that
 * comparison harder for no gain.
 */
function ThresholdBand({ run }: { run: RunResult }) {
  const { threshold_status: status, margin_call: call } = run;

  // Display geometry only. Every figure printed on this panel is the engine's own
  // decimal string, formatted — none is derived from these numbers.
  const exposure = Math.abs(Number(call.exposure.amount));
  const threshold = Math.abs(Number(call.threshold.amount));
  const scale = Math.max(exposure, threshold, 1) * 1.1;
  const exposureShare = Math.min(100, (exposure / scale) * 100);
  const thresholdShare = Math.min(100, (threshold / scale) * 100);

  const surface =
    status.state === "WITHIN"
      ? "panel panel-ok"
      : status.state === "WARNING"
        ? "panel panel-warn"
        : "panel panel-warn";

  return (
    <section className={surface}>
      <div className="px-4 py-3.5 flex flex-col gap-3.5">
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill state={status.state} />
          <span
            className="text-[12.5px] leading-snug"
            style={{ color: "var(--ink-mid)", maxWidth: "78ch" }}
          >
            {status.message}
          </span>
        </div>

        <div className="flex flex-col gap-1.5">
          <div
            className="relative h-[22px] rounded-sm overflow-hidden"
            style={{ background: "var(--surface-3)" }}
            role="img"
            aria-label={`Exposure ${formatMoney(call.exposure)} against a Threshold of ${formatMoney(call.threshold)}`}
          >
            <div
              className="h-full transition-[width] duration-300"
              style={{
                width: `${exposureShare}%`,
                background:
                  status.state === "WITHIN" ? "var(--ok)" : "var(--warn)",
                opacity: 0.85,
              }}
            />
            {/* The Threshold marker. A line rather than a second bar, because the
                Threshold is a boundary and not a quantity of the same kind. */}
            <div
              className="absolute top-0 bottom-0"
              style={{
                left: `${thresholdShare}%`,
                width: 2,
                background: "var(--ink)",
              }}
              title={`Threshold ${formatMoney(call.threshold)}`}
            />
          </div>

          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-[11px]">
            <span style={{ color: "var(--ink-mute)" }}>
              Exposure{" "}
              <span className="tnum" style={{ color: "var(--ink)" }}>
                {formatMoney(call.exposure)}
              </span>
            </span>
            <span style={{ color: "var(--ink-mute)" }}>
              Threshold{" "}
              <span className="tnum" style={{ color: "var(--ink)" }}>
                {formatMoney(call.threshold)}
              </span>
            </span>
            <span style={{ color: "var(--ink-mute)" }}>
              Minimum Transfer Amount{" "}
              <span className="tnum" style={{ color: "var(--ink)" }}>
                {formatMoney(call.minimum_transfer_amount)}
              </span>
            </span>
            <span style={{ color: "var(--ink-faint)" }}>
              Transferor {call.transferor.replace("_", " ")}
            </span>
          </div>
        </div>

        <StatusLegend />
      </div>
    </section>
  );
}

/** The netting set, trade by trade. */
function ExposurePanel({ run }: { run: RunResult }) {
  const { exposure } = run;

  return (
    <Panel
      title="Netting-set exposure"
      aside={<Chip>{exposure.netting_set_id}</Chip>}
    >
      <div
        className="grid grid-cols-2 gap-4 px-4 py-3"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <Stat label="Net exposure" value={<Amount value={exposure.exposure} />} />
        <Stat
          label="Netting benefit"
          value={formatMoney(exposure.netting_benefit)}
          hint={`gross ${formatMoney(exposure.gross_positive)}`}
        />
      </div>

      <div className="max-h-[340px] overflow-auto">
        <table className="grid">
          <thead>
            <tr>
              <th scope="col">Trade</th>
              <th scope="col" className="num">
                Native
              </th>
              <th scope="col" className="num">
                Base
              </th>
            </tr>
          </thead>
          <tbody>
            {exposure.trades.map((trade) => (
              <tr key={trade.trade_id} title={trade.detail}>
                <td>
                  <div className="mono text-[11px]">{trade.trade_id}</div>
                  <div className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                    {trade.trade_type.replace(/_/g, " ").toLowerCase()}
                  </div>
                </td>
                <td className="num">
                  <Amount value={trade.native_value} />
                </td>
                <td className="num">
                  <Amount value={trade.base_value} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p
        className="px-4 py-2 m-0 text-[11px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Trades net only within this netting set. Cross-Master netting is
        structurally prevented, not merely discouraged.
      </p>
    </Panel>
  );
}
