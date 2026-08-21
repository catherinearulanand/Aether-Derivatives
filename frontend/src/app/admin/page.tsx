"use client";

import { ProcessTracker, TrackerLegend } from "@/components/ProcessTracker";
import { RoleGuard } from "@/components/RoleGuard";
import { Chip, ErrorPanel, Panel, Skeleton, Stat } from "@/components/primitives";
import { useCurrentRun, useHealth, useRun, useScenarios, useWorkflow } from "@/lib/hooks";
import { PERMISSION_LABELS, ROLES, ROLE_PROFILES, can, type Permission } from "@/lib/roles";
import { useAether } from "@/lib/store";
import { STAGE_STATE_LABELS, buildWorkflow, stageTone } from "@/lib/workflow";
import Link from "next/link";

/**
 * Platform operations.
 *
 * .. rubric:: Deliberately not a monitoring system
 *
 * What an operations lead needs first thing is one answer: which desks are waiting
 * on a person, and for what. So this screen is a status board, not a telemetry
 * console. It shows where each snapshot's workflow stopped, who owns the stage it
 * stopped at, and what the system's own configuration currently is.
 *
 * There is no CPU graph, no request histogram and no uptime counter, because none
 * of those would change what anyone did next.
 */
export default function AdminPage() {
  return (
    <RoleGuard permission="view:admin">
      <Admin />
    </RoleGuard>
  );
}

function Admin() {
  const run = useCurrentRun();
  const workflow = useWorkflow();
  const health = useHealth();
  const scenarios = useScenarios();
  const currentKey = useAether((s) => s.currentKey);

  const base = useRun("base");
  const stress = useRun("stress");
  const crash = useRun("crash");
  const all = [base, stress, crash];

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
          <h1 className="serif m-0 text-[25px] font-bold leading-tight">
            Platform operations
          </h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "80ch" }}
          >
            Where each workflow stopped, who owns the stage it stopped at, and what
            the system is currently configured to do.
          </p>
        </div>
        {health.data && (
          <div className="ml-auto flex items-center gap-2">
            <Chip tone={health.data.status === "ok" ? "accent" : "crit"}>
              API {health.data.status}
            </Chip>
            <Chip>{health.data.mode}</Chip>
            <Chip>v{health.data.engine_version}</Chip>
          </div>
        )}
      </header>

      {/* The current workflow, in full. */}
      {workflow ? (
        <Panel
          title={`Current workflow — ${run.data?.snapshot.label ?? ""}`}
          aside={
            <div className="flex items-center gap-2">
              <Chip tone={workflow.isClosed ? "accent" : "warn"}>
                {workflow.isClosed
                  ? "All stages settled"
                  : `Waiting at: ${workflow.stages.find((s) => s.id === workflow.activeStage)?.title}`}
              </Chip>
              <Link href="/workflow" className="text-[11.5px]">
                Detail →
              </Link>
            </div>
          }
        >
          <ProcessTracker workflow={workflow} compact />
          <TrackerLegend />

          <table className="grid">
            <thead>
              <tr>
                <th scope="col" style={{ width: 34 }} className="num">
                  #
                </th>
                <th scope="col" style={{ width: 200 }}>
                  Stage
                </th>
                <th scope="col" style={{ width: 150 }}>
                  State
                </th>
                <th scope="col" style={{ width: 120 }}>
                  Owner
                </th>
                <th scope="col" style={{ width: 118 }}>
                  Timestamp
                </th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {workflow.stages.map((stage) => (
                <tr key={stage.id}>
                  <td className="num" style={{ color: "var(--ink-faint)" }}>
                    {stage.index + 1}
                  </td>
                  <td className="text-[12px]">{stage.title}</td>
                  <td>
                    <Chip tone={stageTone(stage.state)}>
                      {STAGE_STATE_LABELS[stage.state]}
                    </Chip>
                  </td>
                  <td className="mono text-[10.5px]" style={{ color: "var(--ink-mute)" }}>
                    {stage.owner}
                  </td>
                  <td className="mono text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
                    {stage.occurredAt ?? "—"}
                  </td>
                  <td className="text-[11.5px] leading-snug" style={{ color: "var(--ink-mid)" }}>
                    {stage.outcome}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p
            className="px-4 py-2.5 m-0 text-[11.5px]"
            style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
          >
            Timestamps come from the pinned valuation date, except an approval,
            which carries the moment its approver signed. That is why an identical
            run reproduces an identical audit chain.
          </p>
        </Panel>
      ) : (
        <Panel title="Current workflow">
          <Skeleton rows={5} height={18} />
        </Panel>
      )}

      {/* Every snapshot, so an ops lead sees the whole desk at once. */}
      <Panel
        title="All snapshots"
        aside={<Chip>{scenarios.data?.length ?? 0} configured</Chip>}
      >
        <table className="grid">
          <thead>
            <tr>
              <th scope="col">Snapshot</th>
              <th scope="col">Decision</th>
              <th scope="col">Threshold</th>
              <th scope="col">Waiting on</th>
              <th scope="col">Approval</th>
              <th scope="col" className="num">
                Audit events
              </th>
              <th scope="col">Chain</th>
            </tr>
          </thead>
          <tbody>
            {all.map((query, index) => {
              const key = ["base", "stress", "crash"][index];
              const data = query.data;
              if (!data) {
                return (
                  <tr key={key}>
                    <td className="mono text-[11px]">{key}</td>
                    <td colSpan={6} style={{ color: "var(--ink-faint)" }}>
                      {query.isError ? "Failed to run." : "Running…"}
                    </td>
                  </tr>
                );
              }

              const flow = buildWorkflow(data);
              const waiting = flow.stages.find((s) => s.id === flow.activeStage);

              return (
                <tr
                  key={key}
                  style={
                    key === currentKey ? { background: "var(--surface-2)" } : undefined
                  }
                >
                  <td>
                    <div className="text-[12px]">{data.snapshot.label}</div>
                    <div className="mono text-[10px]" style={{ color: "var(--ink-faint)" }}>
                      {data.snapshot.snapshot_id}
                    </div>
                  </td>
                  <td>
                    <Chip
                      tone={
                        data.decision.action === "NO_ACTION"
                          ? "default"
                          : data.decision.action === "DEMAND_COLLATERAL"
                            ? "warn"
                            : "accent"
                      }
                    >
                      {data.decision.action.replace(/_/g, " ")}
                    </Chip>
                  </td>
                  <td>
                    <span
                      className={
                        data.threshold_status.state === "WITHIN"
                          ? "status-ok"
                          : data.threshold_status.state === "WARNING"
                            ? "status-warn"
                            : "status-crit"
                      }
                      style={{ fontSize: 11.5 }}
                    >
                      {data.threshold_status.state}
                    </span>
                  </td>
                  <td className="text-[11.5px]" style={{ color: "var(--ink-mid)" }}>
                    {waiting ? (
                      <>
                        {waiting.title}{" "}
                        <span className="mono text-[10px]" style={{ color: "var(--ink-faint)" }}>
                          ({waiting.owner})
                        </span>
                      </>
                    ) : (
                      <span style={{ color: "var(--ok)" }}>nothing</span>
                    )}
                  </td>
                  <td className="text-[11px]">
                    {data.approval ? (
                      <>
                        <div className="mono" style={{ color: "var(--ok)" }}>
                          {data.approval.approver}
                        </div>
                        <div style={{ color: "var(--ink-faint)" }}>
                          {data.approval.occurred_at}
                        </div>
                      </>
                    ) : data.decision.requires_human_approval ? (
                      <span style={{ color: "var(--warn)" }}>outstanding</span>
                    ) : (
                      <span style={{ color: "var(--ink-faint)" }}>not required</span>
                    )}
                  </td>
                  <td className="num">{data.audit.events.length}</td>
                  <td>
                    <Chip tone={data.audit.verified ? "accent" : "crit"}>
                      {data.audit.verified ? "verified" : "broken"}
                    </Chip>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      <div className="grid lg:grid-cols-2 gap-3 items-start">
        <Panel title="System state">
          <div className="px-4 py-3.5 grid grid-cols-2 gap-x-6 gap-y-4">
            <Stat
              label="Mode"
              value={health.data?.mode ?? "—"}
              hint={
                health.data?.mode === "replay"
                  ? "Extraction served from a cached fixture. No network."
                  : "Extraction calls the model live."
              }
              tone="accent"
            />
            <Stat
              label="Engine version"
              value={health.data?.engine_version ?? "—"}
              hint="stamped on every computed result"
            />
            <Stat
              label="Model"
              value={health.data?.model_id ?? "—"}
              hint={health.data?.live_available ? "live calls available" : "no key configured"}
            />
            <Stat
              label="Data"
              value="Simulated"
              hint="every fixture carries a provenance block"
              tone="warn"
            />
            <Stat
              label="Terms in force"
              value={
                run.data?.terms_source === "FROZEN_FROM_REVIEWED_EXTRACTION"
                  ? "Reviewed extraction"
                  : "Committed fixture"
              }
              hint={
                run.data?.terms_source === "FROZEN_FROM_REVIEWED_EXTRACTION"
                  ? "a reviewer's decision governs the calculation"
                  : "no extraction frozen this session"
              }
            />
            <Stat
              label="Connectivity"
              value="None"
              hint="no SWIFT, no custodian, no market feed"
            />
          </div>
          <p
            className="px-4 py-2.5 m-0 text-[11.5px]"
            style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
          >
            Served from the API rather than hardcoded here, so this panel cannot
            drift from what the system is actually doing. See{" "}
            <Link href="/methodology">methodology</Link> for what is and is not
            modelled.
          </p>
        </Panel>

        <Panel title="Roles and separation of duties">
          <table className="grid">
            <thead>
              <tr>
                <th scope="col" style={{ width: 90 }}>
                  Role
                </th>
                {(Object.keys(PERMISSION_LABELS) as Permission[]).map((permission) => (
                  <th
                    key={permission}
                    scope="col"
                    className="num"
                    title={PERMISSION_LABELS[permission]}
                    style={{ writingMode: "vertical-rl", height: 118, padding: "8px 4px" }}
                  >
                    {PERMISSION_LABELS[permission]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROLES.map((role) => (
                <tr key={role}>
                  <td>
                    <div className="mono text-[11px] font-bold">{role}</div>
                    <div className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                      {ROLE_PROFILES[role].title}
                    </div>
                  </td>
                  {(Object.keys(PERMISSION_LABELS) as Permission[]).map((permission) => (
                    <td key={permission} className="num">
                      {can(role, permission) ? (
                        <span className="status-ok mono">✓</span>
                      ) : (
                        <span style={{ color: "var(--ink-faint)" }}>·</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p
            className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
            style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
          >
            Prototype access control — role separation, not authentication. There
            is no password and no identity provider. Approval is the one permission
            enforced beyond this interface: the API refuses a sign-off from LEGAL or
            AUDITOR whatever the browser sends.
          </p>
        </Panel>
      </div>
    </div>
  );
}
