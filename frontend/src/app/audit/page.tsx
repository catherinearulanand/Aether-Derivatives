"use client";

import { Chip, ErrorPanel, Loading, Panel, Stat } from "@/components/primitives";
import { api } from "@/lib/api";
import type { AuditEvent } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

/**
 * The audit trail.
 *
 * Each event hashes its own canonical content plus its predecessor's hash, so
 * altering any record invalidates every hash after it. That makes the log
 * tamper-evident: it does not prevent modification, it makes modification
 * detectable — which is the honest claim for a single-writer audit log.
 */
export default function AuditPage() {
  const [scenarioKey, setScenarioKey] = useState("stress");
  const [expanded, setExpanded] = useState<number | null>(null);

  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const run = useQuery({
    queryKey: ["run", scenarioKey],
    queryFn: () => api.runScenario(scenarioKey),
  });

  const audit = run.data?.audit;

  return (
    <div className="p-4 max-w-[1400px] mx-auto flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-4">
          <div className="eyebrow">Tamper-evident record</div>
          <h1 className="serif m-0 text-[24px] font-bold leading-tight">Audit trail</h1>
        </div>
        {scenarios.data?.map((scenario) => (
          <button
            key={scenario.key}
            onClick={() => setScenarioKey(scenario.key)}
            className={scenario.key === scenarioKey ? "primary" : ""}
          >
            {scenario.name}
          </button>
        ))}
      </div>

      {run.isLoading && <Loading label="Running the pipeline" />}
      {run.isError && <ErrorPanel error={run.error} />}

      {audit && (
        <>
          <Panel
            title="Chain verification"
            aside={
              <Chip tone={audit.verified ? "accent" : "crit"}>
                {audit.verified ? "Verified" : "Broken"}
              </Chip>
            }
          >
            <div className="grid grid-cols-2 md:grid-cols-4 gap-5 px-4 py-3.5">
              <Stat label="Events" value={audit.events.length} />
              <Stat
                label="Status"
                value={audit.verified ? "Intact" : `Broken at ${audit.break_at}`}
                tone={audit.verified ? "accent" : "crit"}
              />
              <Stat label="Chain" value={audit.chain_id} />
              <Stat
                label="Head hash"
                value={
                  <span className="text-[12px]">{audit.head_hash.slice(0, 20)}…</span>
                }
                hint="recomputed on every request"
              />
            </div>
            <p
              className="px-4 py-2.5 m-0 text-[11.5px]"
              style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
            >
              {audit.verification_message} Timestamps come from the pinned valuation
              date rather than a system clock, so an identical run reproduces an
              identical chain — asserted by a determinism test, not assumed.
            </p>
          </Panel>

          <Panel title="Events">
            <table className="grid">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Hash</th>
                  <th>Previous</th>
                </tr>
              </thead>
              <tbody>
                {audit.events.map((event) => (
                  <EventRow
                    key={event.seq}
                    event={event}
                    expanded={expanded === event.seq}
                    onToggle={() =>
                      setExpanded(expanded === event.seq ? null : event.seq)
                    }
                  />
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
    </div>
  );
}

function EventRow({
  event,
  expanded,
  onToggle,
}: {
  event: AuditEvent;
  expanded: boolean;
  onToggle: () => void;
}) {
  const tone =
    event.actor_type === "ENGINE"
      ? "accent"
      : event.actor_type === "HUMAN"
        ? "warn"
        : "default";

  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }} title="Click to inspect the payload">
        <td className="num" style={{ color: "var(--ink-faint)" }}>
          {event.seq}
        </td>
        <td>
          <Chip tone={tone}>{event.actor_type}</Chip>
        </td>
        <td className="mono text-[11.5px]">{event.action}</td>
        <td className="text-[11.5px]" style={{ color: "var(--ink-mute)" }}>
          {event.entity_type} · {event.entity_id}
        </td>
        <td className="mono text-[10.5px]" style={{ color: "var(--accent)" }}>
          {event.hash.slice(0, 16)}…
        </td>
        <td className="mono text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
          {event.prev_hash.slice(0, 16)}…
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} style={{ background: "var(--ground)" }}>
            <pre
              className="mono text-[10.5px] m-0 p-3 overflow-x-auto"
              style={{ color: "var(--ink-mid)", maxHeight: 320 }}
            >
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}
