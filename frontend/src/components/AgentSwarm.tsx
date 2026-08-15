"use client";

import { Chip, Panel } from "@/components/primitives";
import type { Agents } from "@/lib/types";

const TONE: Record<string, string> = {
  LEGAL_CLAUSE_AGENT: "var(--accent)",
  RISK_ENGINE_AGENT: "var(--warn)",
  COLLATERAL_OPTIMIZER_AGENT: "var(--pos, var(--accent))",
};

const SHORT: Record<string, string> = {
  LEGAL_CLAUSE_AGENT: "LEGAL",
  RISK_ENGINE_AGENT: "RISK",
  COLLATERAL_OPTIMIZER_AGENT: "COLLATERAL",
};

/**
 * The swarm's trace.
 *
 * The point of this panel is the `arguments` column. Every row shows what an agent
 * handed to the engine, and none of them is a number — because the type of a tool
 * call forbids it. The outcome column shows what came back. Read together, the two
 * columns are the product's central claim, visible rather than asserted.
 */
export function AgentSwarm({ agents }: { agents: Agents }) {
  return (
    <Panel
      title="Agent swarm"
      aside={
        <div className="flex items-center gap-2">
          <Chip title="How the tool sequence was chosen for this run.">
            {agents.plan_source.replace(/_/g, " ").toLowerCase()}
          </Chip>
          <Chip tone="accent">{agents.actions.length} tool calls</Chip>
        </div>
      }
    >
      <div
        className="grid md:grid-cols-3 gap-px"
        style={{ background: "var(--rule)", borderBottom: "1px solid var(--rule)" }}
      >
        {agents.roster.map((agent) => {
          const used = agents.actions.some((a) => a.agent === agent.role);
          return (
            <div
              key={agent.role}
              className="px-4 py-3 flex flex-col gap-1.5"
              style={{ background: "var(--surface)" }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="mono text-[10px] font-bold"
                  style={{ color: TONE[agent.role] ?? "var(--ink-mute)", letterSpacing: "0.1em" }}
                >
                  {SHORT[agent.role] ?? agent.role}
                </span>
                <Chip tone={used ? "accent" : "default"}>
                  {used ? "active" : "upstream"}
                </Chip>
              </div>
              <div className="text-[13px] font-semibold">{agent.title}</div>
              <p
                className="m-0 text-[11.5px] leading-snug"
                style={{ color: "var(--ink-mute)" }}
              >
                {agent.responsibility}
              </p>
            </div>
          );
        })}
      </div>

      <div className="overflow-x-auto">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 110 }}>Agent</th>
              <th style={{ width: 220 }}>Tool called</th>
              <th>Why it was called</th>
              <th style={{ width: 260 }}>Arguments passed</th>
              <th style={{ width: 300 }}>What the engine returned</th>
            </tr>
          </thead>
          <tbody>
            {agents.actions.map((action, index) => (
              <tr key={`${action.tool}-${index}`}>
                <td>
                  <span
                    className="mono text-[10px] font-bold"
                    style={{ color: TONE[action.agent] ?? "var(--ink-mute)" }}
                  >
                    {SHORT[action.agent] ?? action.agent}
                  </span>
                </td>
                <td className="mono text-[11px]">{action.tool}</td>
                <td
                  className="text-[11.5px] leading-snug"
                  style={{ color: "var(--ink-mid)" }}
                >
                  {action.intent}
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(action.arguments).length === 0 ? (
                      <span className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
                        none
                      </span>
                    ) : (
                      Object.entries(action.arguments).map(([key, value]) => (
                        <span
                          key={key}
                          className="mono text-[10px] px-1.5 py-0.5 rounded-sm"
                          style={{
                            background: "var(--surface-2)",
                            border: "1px solid var(--rule)",
                            color: "var(--ink-mute)",
                          }}
                          title="An identifier, not a value. The engine looked the data up itself."
                        >
                          {key}={String(value)}
                        </span>
                      ))
                    )}
                  </div>
                </td>
                <td className="text-[11.5px] leading-snug">{action.outcome}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        {agents.boundary}
      </p>
    </Panel>
  );
}

/** The tool registry — the complete set of engine calls an agent may make. */
export function ToolRegistry({ agents }: { agents: Agents }) {
  return (
    <Panel
      title="Deterministic tool registry"
      aside={<Chip>{agents.tools.length} tools</Chip>}
    >
      <div className="overflow-x-auto">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 250 }}>Tool</th>
              <th style={{ width: 130 }}>Owner</th>
              <th>What it computes</th>
              <th style={{ width: 220 }}>Accepts</th>
            </tr>
          </thead>
          <tbody>
            {agents.tools.map((tool) => (
              <tr key={tool.name}>
                <td className="mono text-[11px]">{tool.name}</td>
                <td>
                  <span
                    className="mono text-[10px] font-bold"
                    style={{ color: TONE[tool.owner] ?? "var(--ink-mute)" }}
                  >
                    {SHORT[tool.owner] ?? tool.owner}
                  </span>
                </td>
                <td className="text-[11.5px] leading-snug" style={{ color: "var(--ink-mid)" }}>
                  {tool.description}
                </td>
                <td className="mono text-[10px]" style={{ color: "var(--ink-faint)" }}>
                  {tool.required_arguments.join(", ")}
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
        An agent cannot reach the engine except through this table. A plan naming a
        tool that is not listed here is rejected before anything executes.
      </p>
    </Panel>
  );
}
