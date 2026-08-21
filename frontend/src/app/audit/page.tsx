"use client";

import { RoleGuard } from "@/components/RoleGuard";
import { Chip, ErrorPanel, Panel, Skeleton, Stat } from "@/components/primitives";
import { buildCsv, downloadFile } from "@/lib/csv";
import { formatDate } from "@/lib/format";
import { useCurrentRun } from "@/lib/hooks";
import { can } from "@/lib/roles";
import { useAether } from "@/lib/store";
import type { AuditEvent, RunResult } from "@/lib/types";
import { useState } from "react";

/**
 * The audit trail.
 *
 * Each event hashes its own canonical content plus its predecessor's hash, so
 * altering any record invalidates every hash after it. That makes the log
 * tamper-evident: it does not prevent modification, it makes modification
 * detectable — which is the honest claim for a single-writer audit log.
 *
 * .. rubric:: Export
 *
 * Two formats, for two readers. CSV carries every field, including the hashes, for
 * anyone who wants to re-verify the chain in a spreadsheet or a script. The
 * printable report is the same content laid out as a document, produced through
 * the browser's own print-to-PDF rather than by a bundled PDF library — which
 * guarantees that what leaves the building is exactly what was on screen.
 *
 * .. rubric:: The record is not editable here
 *
 * Nothing on this screen writes. There is no edit control, no delete, and no
 * endpoint behind them; the chain is append-only and the only thing that appends
 * to it is a completed pipeline stage or a recorded approval.
 */
export default function AuditPage() {
  return (
    <RoleGuard permission="view:audit">
      <Audit />
    </RoleGuard>
  );
}

type ActorFilter = "ALL" | "ENGINE" | "AGENT" | "HUMAN" | "SYSTEM";

function Audit() {
  const run = useCurrentRun();
  const role = useAether((s) => s.role);
  const identity = useAether((s) => s.identity);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [actor, setActor] = useState<ActorFilter>("ALL");

  const mayExport = can(role, "act:export-audit");
  const audit = run.data?.audit;
  const events = audit?.events.filter((e) => actor === "ALL" || e.actor_type === actor) ?? [];

  if (run.isError) {
    return (
      <div className="p-4 max-w-[1400px] mx-auto">
        <ErrorPanel error={run.error} />
      </div>
    );
  }

  return (
    <div className="p-4 max-w-[1400px] mx-auto flex flex-col gap-3">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <h1 className="serif m-0 text-[25px] font-bold leading-tight">Audit trail</h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "80ch" }}
          >
            Every actor in the run — agent, engine and human — chained by hash. The
            record is append-only: this screen has no control that writes to it.
          </p>
        </div>

        {run.data && mayExport && (
          <div className="ml-auto flex items-center gap-2 no-print">
            <button onClick={() => exportCsv(run.data!)}>Export CSV</button>
            <button onClick={() => window.print()} title="Produces a PDF through the browser's own print dialog.">
              Printable report
            </button>
          </div>
        )}
      </header>

      {/* The report header. Hidden on screen, printed at the top of the PDF, so
          an exported document identifies itself without cluttering the console. */}
      {run.data && (
        <div className="print-only" style={{ marginBottom: 16 }}>
          <h1 style={{ fontSize: "16pt", margin: 0 }}>
            AETHER — Audit Trail Report
          </h1>
          <p style={{ fontSize: "9pt", margin: "4pt 0 0" }}>
            Agreement {run.data.agreement.agreement_id} · Netting set{" "}
            {run.data.exposure.netting_set_id} · Snapshot{" "}
            {run.data.snapshot.snapshot_id} · Valuation date {run.data.as_of}
            <br />
            Chain {run.data.audit.chain_id} · Engine {run.data.engine_version} · Trace{" "}
            {run.data.trace_id}
            <br />
            Head hash {run.data.audit.head_hash}
            <br />
            Verification: {run.data.audit.verification_message}
            <br />
            Exported by {identity} ({role}).
            <br />
            <strong>
              SIMULATED DATA. No transaction was executed and no regulatory approval
              is claimed.
            </strong>
          </p>
        </div>
      )}

      {run.isLoading || !audit || !run.data ? (
        <Panel title="Chain verification">
          <Skeleton rows={4} height={18} />
        </Panel>
      ) : (
        <>
          <Panel
            title="Chain verification"
            aside={
              <Chip tone={audit.verified ? "accent" : "crit"}>
                {audit.verified ? "Verified" : "Broken"}
              </Chip>
            }
          >
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-x-5 gap-y-4 px-4 py-3.5">
              <Stat label="Events" value={audit.events.length} />
              <Stat
                label="Status"
                value={audit.verified ? "Intact" : `Broken at ${audit.break_at}`}
                tone={audit.verified ? "accent" : "crit"}
              />
              <Stat
                label="Agent decisions"
                value={count(audit.events, "AGENT")}
                hint="which tool, and why"
              />
              <Stat
                label="Engine computations"
                value={count(audit.events, "ENGINE")}
                hint="every number in the run"
              />
              <Stat
                label="Human decisions"
                value={count(audit.events, "HUMAN")}
                hint={
                  count(audit.events, "HUMAN") > 0
                    ? "confirmations and approvals"
                    : "none recorded this session"
                }
                tone={count(audit.events, "HUMAN") > 0 ? "accent" : "default"}
              />
              <Stat
                label="Head hash"
                value={<span className="text-[12px]">{audit.head_hash.slice(0, 18)}…</span>}
                hint="recomputed on every request"
              />
            </div>
            <p
              className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
              style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
            >
              {audit.verification_message} Timestamps come from the pinned valuation
              date rather than a system clock — except a human approval, which
              carries the moment it was signed and is replayed from that recorded
              value. An identical run therefore reproduces an identical chain, which
              a determinism test asserts rather than assumes.
            </p>
          </Panel>

          <Panel
            title="Events"
            aside={
              <div className="flex items-center gap-1.5 no-print">
                {(["ALL", "AGENT", "ENGINE", "HUMAN", "SYSTEM"] as ActorFilter[]).map(
                  (option) => (
                    <button
                      key={option}
                      onClick={() => setActor(option)}
                      className={actor === option ? "primary" : ""}
                      style={{ fontSize: 10.5, padding: "2px 8px" }}
                    >
                      {option.toLowerCase()}
                    </button>
                  ),
                )}
              </div>
            }
          >
            <div className="overflow-x-auto">
              <table className="grid">
                <thead>
                  <tr>
                    <th scope="col" className="num" style={{ width: 34 }}>
                      #
                    </th>
                    <th scope="col" style={{ width: 84 }}>
                      Actor
                    </th>
                    <th scope="col" style={{ width: 190 }}>
                      Actor id
                    </th>
                    <th scope="col" style={{ width: 200 }}>
                      Action
                    </th>
                    <th scope="col">Entity</th>
                    <th scope="col" style={{ width: 106 }}>
                      Occurred
                    </th>
                    <th scope="col" style={{ width: 130 }}>
                      Hash
                    </th>
                    <th scope="col" style={{ width: 130 }}>
                      Previous
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
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
            </div>
            {events.length === 0 && (
              <p
                className="px-4 py-6 m-0 text-[12.5px]"
                style={{ color: "var(--ink-mute)" }}
              >
                No {actor.toLowerCase()} events in this run.
              </p>
            )}
          </Panel>

          {mayExport && (
            <Panel title="What an export contains" className="no-print">
              <div className="px-4 py-3.5 grid md:grid-cols-2 gap-x-8 gap-y-3">
                <div>
                  <div className="eyebrow mb-1.5">CSV</div>
                  <p
                    className="m-0 text-[11.5px] leading-relaxed"
                    style={{ color: "var(--ink-mid)" }}
                  >
                    One row per event with sequence, actor and actor type, action,
                    entity type and id, timestamp, both hashes, and the full payload
                    as JSON. Also carries the run&apos;s provenance — agreement,
                    netting set, snapshot, valuation date, engine version and trace
                    — so a row can be traced back to the run that produced it
                    without this application.
                  </p>
                </div>
                <div>
                  <div className="eyebrow mb-1.5">Printable report</div>
                  <p
                    className="m-0 text-[11.5px] leading-relaxed"
                    style={{ color: "var(--ink-mid)" }}
                  >
                    The same events as a document, headed with the chain
                    identifier, the head hash, the verification result and who
                    exported it. Produced through the browser&apos;s print dialog,
                    so the document is exactly what was displayed — no separate
                    rendering path that could diverge from the screen.
                  </p>
                </div>
              </div>
              <p
                className="px-4 py-2.5 m-0 text-[11.5px]"
                style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
              >
                Both exports state that the data is simulated. An audit artefact
                that did not say so would be the most dangerous document this
                system could produce.
              </p>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

function count(events: AuditEvent[], type: string): number {
  return events.filter((event) => event.actor_type === type).length;
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
      <tr
        onClick={onToggle}
        style={{ cursor: "pointer" }}
        title="Click to inspect the payload that was hashed"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <td className="num" style={{ color: "var(--ink-faint)" }}>
          {event.seq}
        </td>
        <td>
          <Chip tone={tone}>{event.actor_type}</Chip>
        </td>
        <td className="mono text-[10.5px]" style={{ color: "var(--ink-mute)" }}>
          {event.actor}
        </td>
        <td className="mono text-[11px]">{event.action}</td>
        <td className="text-[11.5px]" style={{ color: "var(--ink-mute)" }}>
          {event.entity_type} · {event.entity_id}
        </td>
        <td className="mono text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
          {event.occurred_at.length > 10
            ? event.occurred_at.slice(0, 19).replace("T", " ")
            : formatDate(event.occurred_at)}
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
          <td colSpan={8} style={{ background: "var(--ground)" }}>
            <pre
              className="mono text-[10.5px] m-0 p-3 overflow-x-auto"
              style={{ color: "var(--ink-mid)", maxHeight: 340 }}
            >
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * The CSV export.
 *
 * Built from the same `audit.events` array the table renders, so the file and the
 * screen cannot disagree. Every field the chain holds is included — omitting the
 * hashes would produce a document that looks like an audit trail and cannot be
 * verified as one.
 */
function exportCsv(run: RunResult): void {
  const columns = [
    { key: "seq", header: "Sequence" },
    { key: "occurred_at", header: "Occurred at" },
    { key: "actor_type", header: "Actor type" },
    { key: "actor", header: "Actor" },
    { key: "action", header: "Action" },
    { key: "entity_type", header: "Entity type" },
    { key: "entity_id", header: "Entity id" },
    { key: "agreement_id", header: "Agreement" },
    { key: "netting_set_id", header: "Netting set" },
    { key: "snapshot_id", header: "Snapshot" },
    { key: "as_of", header: "Valuation date" },
    { key: "engine_version", header: "Engine version" },
    { key: "trace_id", header: "Trace" },
    { key: "hash", header: "Hash" },
    { key: "prev_hash", header: "Previous hash" },
    { key: "payload", header: "Payload (JSON)" },
  ];

  const rows = run.audit.events.map((event) => ({
    seq: event.seq,
    occurred_at: event.occurred_at,
    actor_type: event.actor_type,
    actor: event.actor,
    action: event.action,
    entity_type: event.entity_type,
    entity_id: event.entity_id,
    agreement_id: run.agreement.agreement_id,
    netting_set_id: run.exposure.netting_set_id,
    snapshot_id: run.snapshot.snapshot_id,
    as_of: run.as_of,
    engine_version: run.engine_version,
    trace_id: run.trace_id,
    hash: event.hash,
    prev_hash: event.prev_hash,
    payload: JSON.stringify(event.payload),
  }));

  const csv = buildCsv(columns, rows, [
    "AETHER audit trail export. SIMULATED DATA - no transaction was executed.",
    `Chain ${run.audit.chain_id} · ${run.audit.events.length} events · head ${run.audit.head_hash}`,
    `Verification: ${run.audit.verification_message}`,
    `Agreement ${run.agreement.agreement_id} · snapshot ${run.snapshot.snapshot_id} · as of ${run.as_of}`,
    "Each event hashes its own canonical content plus its predecessor's hash. " +
      "Tamper-evident, not a blockchain.",
  ]);

  downloadFile(`aether-audit-${run.trace_id}-${run.as_of}.csv`, csv);
}
