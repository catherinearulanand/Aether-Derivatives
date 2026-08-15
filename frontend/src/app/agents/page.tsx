"use client";

import { AgentSwarm, ToolRegistry } from "@/components/AgentSwarm";
import { Chip, ErrorPanel, Loading, Panel, Stat } from "@/components/primitives";
import { api } from "@/lib/api";
import type { RunResult } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

/**
 * The swarm, on its own screen.
 *
 * The Margin Desk shows what the swarm produced. This screen shows how — which agent
 * decided what, what it was allowed to pass, and what the engine handed back. The
 * separation between the two columns is the architecture.
 */
export default function AgentsPage() {
  const [scenarioKey, setScenarioKey] = useState("stress");

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const run = useQuery({
    queryKey: ["run", scenarioKey],
    queryFn: () => api.runScenario(scenarioKey),
  });

  return (
    <div className="p-4 flex flex-col gap-3 max-w-[1600px] mx-auto">
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">Scenario</span>
        {scenarios.data?.map((scenario) => (
          <button
            key={scenario.key}
            onClick={() => setScenarioKey(scenario.key)}
            className={scenario.key === scenarioKey ? "primary" : ""}
            title={scenario.summary}
          >
            {scenario.name}
          </button>
        ))}
      </div>

      <header className="panel px-4 py-3.5">
        <h1 className="serif m-0 text-[23px] font-bold leading-tight">
          Three agents, one deterministic engine
        </h1>
        <p
          className="mt-2 mb-0 text-[12.5px] leading-relaxed max-w-[85ch]"
          style={{ color: "var(--ink-mid)" }}
        >
          A Legal-Clause Agent reads the Annex and hands over typed, cited terms. A
          Risk-Engine Agent routes valuation and margin tools against a pinned market
          snapshot. A Collateral-Optimizer Agent decides whether collateral must be
          selected, runs the linear program and renders the settlement instruction.
          None of them computes anything: each chooses which deterministic tool to
          call and with which identifiers, and the engine returns every number.
        </p>
      </header>

      {run.isLoading && <Loading label="Running the swarm" />}
      {run.isError && <ErrorPanel error={run.error} />}

      {run.data && (
        <>
          <Timings result={run.data} />
          <AgentSwarm agents={run.data.agents} />
          <ToolRegistry agents={run.data.agents} />
          <Boundary />
        </>
      )}
    </div>
  );
}

function Timings({ result }: { result: RunResult }) {
  const timing = result.timing;
  const engineEvents = result.audit.events.filter((e) => e.actor_type === "ENGINE").length;
  const agentEvents = result.audit.events.filter((e) => e.actor_type === "AGENT").length;
  const humanEvents = result.audit.events.filter((e) => e.actor_type === "HUMAN").length;

  return (
    <Panel
      title="This run"
      aside={<Chip>{result.trace_id}</Chip>}
    >
      <div className="px-4 py-3.5 grid grid-cols-2 md:grid-cols-5 gap-x-6 gap-y-4">
        <Stat
          label="Wall clock"
          value={timing ? `${timing.elapsed_ms.toFixed(0)} ms` : "—"}
          hint={timing ? `${timing.stages} tool calls, end to end` : undefined}
          tone="accent"
        />
        <Stat label="Agent decisions" value={String(agentEvents)} hint="recorded in the chain" />
        <Stat label="Engine computations" value={String(engineEvents)} hint="every number" />
        <Stat
          label="Human decisions"
          value={String(humanEvents)}
          hint={humanEvents > 0 ? "confirmed and frozen" : "fixture terms, no review this session"}
        />
        <Stat
          label="Planning"
          value={result.agents.plan_source.replace(/_/g, " ").toLowerCase()}
          hint="deterministic in replay"
        />
      </div>
      {timing && (
        <p
          className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
          style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
        >
          A manual margin run across a complex CSA is commonly estimated at{" "}
          {timing.manual_baseline_hours} hours. {timing.manual_baseline_note}
        </p>
      )}
    </Panel>
  );
}

function Boundary() {
  return (
    <Panel title="Why an agent cannot produce a number">
      <div className="px-4 py-3.5 flex flex-col gap-3 text-[12.5px] leading-relaxed">
        <p className="m-0" style={{ color: "var(--ink-mid)" }}>
          The separation is enforced by a type, not by a convention. A tool call&apos;s
          arguments admit strings, integers, booleans and null — and nothing else:
        </p>
        <pre
          className="m-0 px-3 py-2.5 text-[11.5px] overflow-x-auto"
          style={{ background: "var(--surface-2)", color: "var(--ink-mid)" }}
        >{`Argument = str | int | bool | None

ToolCall(
    agent=AgentRole.RISK_ENGINE,
    tool="compute_credit_support_amount",
    arguments={"credit_support_amount": Decimal("9500000")},
)
# TypeError: argument 'credit_support_amount' is Decimal, which is not permitted.
# Agents pass references, not values.`}</pre>
        <p className="m-0" style={{ color: "var(--ink-mid)" }}>
          A model that hallucinated a figure into a plan would have that plan rejected
          before anything executed. Monetary values exist only inside typed engine
          results, which flow between tools through the run context and never through
          a plan. The audit trail then records the two sides separately, so a reader
          can check the claim event by event rather than taking it on trust.
        </p>
      </div>
    </Panel>
  );
}
