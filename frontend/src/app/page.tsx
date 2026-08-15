"use client";

import { AgentSwarm } from "@/components/AgentSwarm";
import { CrossBorder } from "@/components/CrossBorder";
import { Optimizer } from "@/components/Optimizer";
import { RiskMargin } from "@/components/RiskMargin";
import { Settlement } from "@/components/Settlement";
import { Waterfall } from "@/components/Waterfall";
import { Amount, Chip, ErrorPanel, Loading, Panel, Stat } from "@/components/primitives";
import { api } from "@/lib/api";
import { formatDate, formatMoney, shortHash } from "@/lib/format";
import type { Decision, RunResult } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

export default function MarginDesk() {
  const [scenarioKey, setScenarioKey] = useState("stress");

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const run = useQuery({
    queryKey: ["run", scenarioKey],
    queryFn: () => api.runScenario(scenarioKey),
  });

  return (
    <div className="p-4 flex flex-col gap-3 max-w-[1600px] mx-auto">
      {/* Scenario selector */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">Market scenario</span>
        {scenarios.data?.map((scenario) => {
          const active = scenario.key === scenarioKey;
          return (
            <button
              key={scenario.key}
              onClick={() => setScenarioKey(scenario.key)}
              className={active ? "primary" : ""}
              title={scenario.summary}
            >
              {scenario.name}
            </button>
          );
        })}
        {run.data?.scenario && (
          <span
            className="text-[12px] ml-2"
            style={{ color: "var(--ink-mute)" }}
          >
            {run.data.scenario.summary}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          {run.data && (
            <>
              {run.data.terms_source === "FROZEN_FROM_REVIEWED_EXTRACTION" && (
                <Chip
                  tone="accent"
                  title="A reviewed extraction has been frozen in this session, and the engine is computing on it rather than on the committed fixture."
                >
                  reviewed terms
                </Chip>
              )}
              {run.data.timing && (
                <Chip title={run.data.timing.measured}>
                  {run.data.timing.elapsed_ms.toFixed(0)} ms
                </Chip>
              )}
              <Chip title="Pinned market snapshot. No live feeds anywhere in this system.">
                {run.data.snapshot.snapshot_id}
              </Chip>
              <Chip>{formatDate(run.data.snapshot.as_of)}</Chip>
            </>
          )}
        </div>
      </div>

      {run.isLoading && <Loading label="Running the pipeline" />}
      {run.isError && <ErrorPanel error={run.error} />}

      {run.data && (
        <>
          <DecisionBanner decision={run.data.decision} />

          <AgentSwarm agents={run.data.agents} />

          <div className="grid xl:grid-cols-[minmax(0,1fr)_420px] gap-3">
            <Waterfall call={run.data.margin_call} />
            <ExposurePanel result={run.data} />
          </div>

          <RiskMargin
            sensitivity={run.data.sensitivity_margin}
            schedule={run.data.initial_margin}
          />

          <Optimizer allocation={run.data.allocation} />

          <CrossBorder allocation={run.data.allocation} />

          <Settlement settlement={run.data.settlement} />

          <AuditStrip result={run.data} />
        </>
      )}
    </div>
  );
}

function DecisionBanner({ decision }: { decision: Decision }) {
  const tone =
    decision.action === "POST_COLLATERAL"
      ? "accent"
      : decision.action === "ESCALATE"
        ? "crit"
        : "default";

  const accent =
    tone === "accent"
      ? "var(--accent)"
      : tone === "crit"
        ? "var(--crit)"
        : "var(--ink-mute)";

  return (
    <section
      className="panel"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="px-4 py-3.5 flex flex-wrap items-start gap-x-8 gap-y-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1.5">
            <Chip tone={tone}>{decision.action.replace(/_/g, " ")}</Chip>
            <Chip
              tone={decision.requires_human_approval ? "warn" : "default"}
              title="The pipeline proposes. Nothing moves without a human."
            >
              {decision.status.replace(/_/g, " ")}
            </Chip>
          </div>
          <h1
            className="serif m-0 leading-tight"
            style={{ fontSize: 25, fontWeight: 700 }}
          >
            {decision.headline}
          </h1>
          <ul
            className="mt-2.5 mb-0 pl-4 flex flex-col gap-1 text-[12px]"
            style={{ color: "var(--ink-mid)" }}
          >
            {decision.rationale.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-3.5 shrink-0">
          <Stat
            label="Transfer required"
            value={formatMoney(decision.amount)}
            hint={`from ${decision.transferor.replace("_", " ")}`}
            tone={tone === "crit" ? "crit" : "accent"}
          />
          <Stat
            label="Credit Support Amount"
            value={formatMoney(decision.credit_support_amount)}
            hint="before MTA and rounding"
          />
          {decision.asset_count > 0 && (
            <>
              <Stat
                label="Funding cost"
                value={formatMoney(decision.allocation_cost)}
                hint={`${decision.asset_count} assets, per annum`}
              />
              <Stat
                label="Saved vs cash-first"
                value={formatMoney(decision.saving)}
                hint={`${Number(decision.saving_percentage).toFixed(1)}% lower`}
                tone="accent"
              />
            </>
          )}
        </div>
      </div>

      <div
        className="px-4 py-2 text-[11px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        {decision.disclaimer}
      </div>
    </section>
  );
}

function ExposurePanel({ result }: { result: RunResult }) {
  const { exposure } = result;
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

      <div className="max-h-[280px] overflow-auto">
        <table className="grid">
          <thead>
            <tr>
              <th>Trade</th>
              <th className="num">Native</th>
              <th className="num">Base</th>
            </tr>
          </thead>
          <tbody>
            {exposure.trades.map((trade) => (
              <tr key={trade.trade_id} title={trade.detail}>
                <td className="mono text-[11px]">{trade.trade_id}</td>
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
        Trades net only within this netting set. Cross-Master netting is structurally
        prevented, not merely discouraged.
      </p>
    </Panel>
  );
}

function AuditStrip({ result }: { result: RunResult }) {
  const { audit } = result;
  return (
    <Panel
      title="Audit chain"
      aside={
        <div className="flex items-center gap-2">
          <Chip tone={audit.verified ? "accent" : "crit"}>
            {audit.verified ? "Verified" : `Broken at ${audit.break_at}`}
          </Chip>
          <Link href="/audit" className="text-[11.5px]">
            Full trail →
          </Link>
        </div>
      }
    >
      <div className="flex items-stretch overflow-x-auto px-4 py-3 gap-1">
        {audit.events.map((event, index) => (
          <div key={event.seq} className="flex items-center gap-1 shrink-0">
            <div
              className="px-2.5 py-1.5 rounded-sm"
              style={{
                background: "var(--surface-2)",
                border: "1px solid var(--rule)",
                minWidth: 148,
              }}
              title={`${event.hash}\nprev ${event.prev_hash}`}
            >
              <div
                className="mono text-[9px]"
                style={{
                  color:
                    event.actor_type === "ENGINE"
                      ? "var(--accent)"
                      : "var(--ink-faint)",
                }}
              >
                {event.actor_type}
              </div>
              <div className="text-[11px] truncate" style={{ color: "var(--ink-mid)" }}>
                {event.action.replace(/_/g, " ").toLowerCase()}
              </div>
              <div className="mono text-[9px]" style={{ color: "var(--ink-faint)" }}>
                {shortHash(event.hash, 10)}
              </div>
            </div>
            {index < audit.events.length - 1 && (
              <span className="mono" style={{ color: "var(--ink-faint)" }}>
                →
              </span>
            )}
          </div>
        ))}
      </div>
      <p
        className="px-4 py-2 m-0 text-[11px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        {audit.verification_message} Each event hashes its own content plus its
        predecessor, so altering any record breaks every hash after it. Tamper-evident,
        not a blockchain.
      </p>
    </Panel>
  );
}
