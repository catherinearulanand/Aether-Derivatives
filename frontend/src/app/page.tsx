"use client";

import { BeforeAfter } from "@/components/BeforeAfter";
import { Composition } from "@/components/Charts";
import { ProcessTracker, StageDetail, TrackerLegend } from "@/components/ProcessTracker";
import {
  Chip,
  ErrorPanel,
  Panel,
  Skeleton,
  Stat,
  StatusLegend,
  StatusPill,
} from "@/components/primitives";
import { useApproval, useComparison, useCurrentRun, useWorkflow } from "@/lib/hooks";
import { formatDate, formatMoney } from "@/lib/format";
import { can } from "@/lib/roles";
import { useAether } from "@/lib/store";
import type { Allocation, Decision, RunResult } from "@/lib/types";
import type { StageId } from "@/lib/workflow";
import Link from "next/link";
import { useState } from "react";

/**
 * The margin desk.
 *
 * .. rubric:: What this screen has to answer
 *
 * Six questions, in this order, because that is the order a collateral manager
 * asks them: What is happening? What changed? How much is required? What should be
 * posted? Why that? What happens next?
 *
 * The layout follows those questions rather than following the data model. Status
 * strip, then the market event and its consequences, then the distribution, then
 * the process tracker, then the reasoning, then the decision that awaits a human.
 */
export default function Dashboard() {
  const run = useCurrentRun();
  const comparison = useComparison();
  const workflow = useWorkflow();
  const [openStage, setOpenStage] = useState<StageId | null>(null);

  if (run.isError) {
    return (
      <div className="p-4 max-w-[1600px] mx-auto">
        <ErrorPanel error={run.error} />
      </div>
    );
  }

  return (
    <div className="p-4 flex flex-col gap-3 max-w-[1600px] mx-auto">
      {run.isLoading || !run.data ? (
        <>
          <Panel title="Running the pipeline">
            <Skeleton rows={4} height={18} />
          </Panel>
          <Panel title="Before market movement → after">
            <Skeleton rows={5} />
          </Panel>
        </>
      ) : (
        <>
          {/* 1. What is happening? */}
          <StatusStrip run={run.data} />

          {/* 2. What changed? */}
          {comparison.isError ? (
            <ErrorPanel error={comparison.error} />
          ) : comparison.isLoading ? (
            <Panel title="Before market movement → after">
              <Skeleton rows={5} />
            </Panel>
          ) : comparison.data ? (
            <BeforeAfter comparison={comparison.data} />
          ) : (
            <Panel title="Before market movement → after">
              <p
                className="px-4 py-6 m-0 text-[12.5px]"
                style={{ color: "var(--ink-mute)" }}
              >
                The baseline and the current snapshot are the same. Choose a
                different baseline in the bar above to see what a market movement
                did.
              </p>
            </Panel>
          )}

          {/* 3 and 4. How much, and what to post. */}
          <Distribution run={run.data} />

          {/* 5. Where are we in the process? */}
          {workflow && (
            <Panel
              title="Process"
              aside={
                <div className="flex items-center gap-2">
                  <Chip tone={workflow.isClosed ? "accent" : "warn"}>
                    {workflow.completedCount} of {workflow.stages.length} settled
                  </Chip>
                  <Link href="/workflow" className="text-[11.5px]">
                    Open each stage →
                  </Link>
                </div>
              }
            >
              <ProcessTracker
                workflow={workflow}
                selected={openStage}
                onSelect={(id) => setOpenStage(openStage === id ? null : id)}
              />
              {openStage && (
                <StageDetail
                  stage={workflow.stages.find((s) => s.id === openStage)!}
                />
              )}
              <TrackerLegend />
            </Panel>
          )}

          {/* 6. Why this decision, and what happens next. */}
          <WhyThisDecision run={run.data} />
          <DecisionPanel run={run.data} />
        </>
      )}
    </div>
  );
}

/**
 * The status strip.
 *
 * Six figures that together say what state the desk is in. Threshold status leads
 * because it is the one that decides whether anything else on the screen matters
 * today.
 */
function StatusStrip({ run }: { run: RunResult }) {
  const { threshold_status: threshold, margin_call: call, allocation, decision } = run;

  const surface =
    threshold.state === "BREACHED"
      ? "panel panel-warn"
      : threshold.state === "WARNING"
        ? "panel panel-warn"
        : "panel panel-ok";

  return (
    <section className={surface} aria-live="polite">
      <div
        className="px-4 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <StatusPill state={threshold.state} title={threshold.message} />
        <span
          className="text-[12px] leading-snug"
          style={{ color: "var(--ink-mid)", maxWidth: "78ch" }}
        >
          {threshold.message}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Chip title="Pinned market snapshot. No live feeds anywhere in this system.">
            {run.snapshot.snapshot_id}
          </Chip>
          <Chip>{formatDate(run.as_of)}</Chip>
          {run.timing && (
            <Chip title={run.timing.measured}>
              {run.timing.elapsed_ms.toFixed(0)} ms
            </Chip>
          )}
        </div>
      </div>

      <div className="px-4 py-3.5 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-x-6 gap-y-4">
        <Stat
          label="Market status"
          value={run.snapshot.label}
          hint={`${run.exposure.trade_count} trades repriced`}
        />
        <Stat
          label="Net exposure"
          value={formatMoney(run.exposure.exposure)}
          hint={`netting saves ${formatMoney(run.exposure.netting_benefit)}`}
        />
        <Stat
          label="Margin requirement"
          value={formatMoney(call.credit_support_amount)}
          hint="Credit Support Amount, Paragraph 2(c)"
          tone={threshold.state === "BREACHED" ? "warn" : "default"}
        />
        <Stat
          label="Collateral required"
          value={formatMoney(call.call_amount)}
          hint={
            call.direction === "NONE"
              ? "no transfer today"
              : `${call.direction.toLowerCase()} from ${call.transferor.replace("_", " ")}`
          }
          tone={call.direction === "NONE" ? "default" : "accent"}
        />
        <Stat
          label="Threshold"
          value={formatMoney(call.threshold)}
          hint={`MTA ${formatMoney(call.minimum_transfer_amount)}`}
        />
        <Stat
          label="Optimisation"
          value={
            allocation
              ? allocation.status
              : decision.action === "NO_ACTION"
                ? "Not required"
                : "Counterparty selects"
          }
          hint={
            allocation
              ? `${allocation.lines.length} assets, ${formatMoney(allocation.total_cost)} p.a.`
              : "no allocation ran at this snapshot"
          }
          tone={allocation?.status === "OPTIMAL" ? "accent" : "default"}
        />
      </div>

      <div className="px-4 pb-2.5">
        <StatusLegend />
      </div>
    </section>
  );
}

/** The final collateral distribution — what would actually be delivered. */
function Distribution({ run }: { run: RunResult }) {
  const allocation = run.allocation;

  if (!allocation || allocation.status !== "OPTIMAL") {
    return (
      <Panel title="Final collateral distribution">
        <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
          {run.decision.action === "DEMAND_COLLATERAL"
            ? "The counterparty owes this collateral, so they choose what to deliver. " +
              "AETHER generates the call; their proposal comes back in reply."
            : "No Delivery Amount is due under this snapshot, so nothing is allocated."}
        </p>
      </Panel>
    );
  }

  return (
    <div className="grid xl:grid-cols-[minmax(0,1fr)_minmax(0,420px)] gap-3 items-start">
      <Panel
        title="Final collateral distribution"
        aside={
          <div className="flex items-center gap-2">
            <Chip tone="accent">{allocation.lines.length} assets</Chip>
            <Link href="/optimisation" className="text-[11.5px]">
              Full working →
            </Link>
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="grid">
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Class</th>
                <th scope="col" className="num">
                  Market value posted
                </th>
                <th scope="col" className="num">
                  Haircut
                </th>
                <th scope="col" className="num">
                  Counts as collateral
                </th>
                <th scope="col" className="num">
                  Cost p.a.
                </th>
              </tr>
            </thead>
            <tbody>
              {allocation.lines.map((line) => (
                <tr key={line.asset_id}>
                  <td>
                    <div className="mono text-[11.5px]">{line.asset_id}</div>
                    <div className="text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
                      {line.description}
                    </div>
                  </td>
                  <td>
                    <div className="flex flex-col items-start gap-1">
                      <Chip>{line.asset_class.replace(/_/g, " ").toLowerCase()}</Chip>
                      {line.fx_haircut_applied && (
                        <Chip tone="warn" title="Non-base currency: an FX haircut applies on top of the schedule percentage.">
                          FX
                        </Chip>
                      )}
                    </div>
                  </td>
                  <td className="num">{formatMoney(line.market_value_posted)}</td>
                  <td className="num" style={{ color: "var(--ink-mute)" }}>
                    {(100 - Number(line.effective_percentage) * 100).toFixed(1)}%
                  </td>
                  <td className="num font-semibold">
                    {formatMoney(line.effective_value)}
                  </td>
                  <td className="num" style={{ color: "var(--ink-mute)" }}>
                    {formatMoney(line.annual_cost)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4} className="text-[11.5px]" style={{ color: "var(--ink-mute)" }}>
                  Delivered against {formatMoney(allocation.required_value)} required
                </td>
                <td className="num font-bold" style={{ color: "var(--accent)" }}>
                  {formatMoney(allocation.allocated_value)}
                </td>
                <td className="num font-semibold">{formatMoney(allocation.total_cost)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Panel>

      <Panel title="Composition by asset class">
        <Composition
          slices={classComposition(allocation.lines)}
          total={allocation.allocated_value}
          caption={
            "Share of post-haircut collateral value. Concentration caps in the " +
            "Annex are what stop any one class filling the requirement."
          }
        />
      </Panel>
    </div>
  );
}

function classComposition(lines: Allocation["lines"]) {
  const groups = new Map<string, { amount: number; currency: string }>();
  for (const line of lines) {
    const key = line.asset_class.replace(/_/g, " ").toLowerCase();
    const existing = groups.get(key);
    // Display geometry only: the figures rendered beside each slice are the
    // engine's strings, formatted, not these accumulators.
    const value = Number(line.effective_value.amount);
    groups.set(key, {
      amount: (existing?.amount ?? 0) + value,
      currency: line.effective_value.currency,
    });
  }
  return [...groups.entries()]
    .sort((a, b) => b[1].amount - a[1].amount)
    .map(([label, group]) => ({
      label,
      value: { amount: group.amount.toFixed(2), currency: group.currency },
    }));
}

/**
 * Why this decision.
 *
 * Every line is drawn from the solved problem — the engine's own rationale, the
 * binding constraints from the solver's duals, the eligibility exclusions with
 * their clause references. Nothing here is a generic reassurance.
 */
function WhyThisDecision({ run }: { run: RunResult }) {
  const { decision, allocation, margin_call: call, threshold_status: threshold } = run;
  const binding = allocation?.shadow_prices.filter((s) => s.binding) ?? [];

  const checks: { ok: boolean; text: string; detail: string }[] = [
    {
      ok: threshold.state !== "WITHIN",
      text:
        threshold.state === "WITHIN"
          ? "Exposure is inside the Threshold"
          : "Exposure exceeds the Threshold",
      detail: `Net exposure ${formatMoney(call.exposure)} against a Threshold of ${formatMoney(call.threshold)}.`,
    },
    {
      ok: !call.gated_by_mta && call.direction !== "NONE",
      text: call.gated_by_mta
        ? "Amount is below the Minimum Transfer Amount"
        : "Amount clears the Minimum Transfer Amount",
      detail: `Unrounded ${formatMoney(call.unrounded_amount)} against an MTA of ${formatMoney(call.minimum_transfer_amount)}.`,
    },
  ];

  if (allocation && allocation.status === "OPTIMAL") {
    checks.push(
      {
        ok: true,
        text: "Every selected asset is eligible under the Annex",
        detail: `${allocation.considered.length} assets passed the eligibility schedule; ${allocation.excluded.length} were excluded outright.`,
      },
      {
        ok: true,
        text: "Haircuts and concentration limits are satisfied",
        detail:
          binding.length > 0
            ? `${binding.length} constraint${binding.length === 1 ? "" : "s"} bind: ${binding.map((b) => b.description).join("; ")}.`
            : "No constraint binds at this allocation.",
      },
      {
        ok: true,
        text: "The requirement is covered post-haircut",
        detail: `${formatMoney(allocation.allocated_value)} of collateral value against ${formatMoney(allocation.required_value)} required.`,
      },
      {
        ok: allocation.baseline_covers_requirement,
        text: allocation.baseline_covers_requirement
          ? "Cheaper than a cash-first allocation"
          : "Cash and sovereigns alone could not have covered this",
        detail: allocation.baseline_covers_requirement
          ? `${formatMoney(allocation.total_cost)} a year against ${formatMoney(allocation.baseline_cost)} for cash-first — ${Number(allocation.saving_percentage).toFixed(1)}% lower.`
          : "The cash-first baseline is not comparable, because it cannot meet the requirement.",
      },
    );
  }

  return (
    <Panel
      title="Why this decision"
      aside={<Chip>{checks.length} checks, all from the solved problem</Chip>}
    >
      <div className="grid md:grid-cols-2 gap-px" style={{ background: "var(--rule)" }}>
        {checks.map((check) => (
          <div
            key={check.text}
            className="px-4 py-3 flex gap-2.5"
            style={{ background: "var(--surface)" }}
          >
            <span
              className={`mono shrink-0 ${check.ok ? "status-ok" : "status-warn"}`}
              style={{ fontSize: 12, lineHeight: "1.35" }}
              aria-hidden="true"
            >
              {check.ok ? "✓" : "•"}
            </span>
            <div className="min-w-0">
              <div className="text-[12.5px]" style={{ color: "var(--ink)" }}>
                {check.text}
              </div>
              <div
                className="text-[11px] leading-snug mt-0.5"
                style={{ color: "var(--ink-faint)" }}
              >
                {check.detail}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="px-4 py-3" style={{ borderTop: "1px solid var(--rule)" }}>
        <span className="eyebrow block mb-1.5">Engine rationale</span>
        <ul
          className="m-0 pl-4 flex flex-col gap-1 text-[12px]"
          style={{ color: "var(--ink-mid)" }}
        >
          {decision.rationale.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

/**
 * The decision, and the human gate in front of it.
 *
 * Approval writes a `HUMAN` event into the run's hash chain. It authorises
 * nothing — AETHER has no settlement connectivity — and the panel says so where
 * the button is, not in a footnote.
 */
function DecisionPanel({ run }: { run: RunResult }) {
  const decision: Decision = run.decision;
  const role = useAether((s) => s.role);
  const identity = useAether((s) => s.identity);
  const { approve, revoke } = useApproval();
  const [note, setNote] = useState(
    "Delivery Amount agrees with the counterparty's statement. Allocation reviewed.",
  );

  const mayApprove = can(role, "act:approve");
  const approval = run.approval;

  const tone =
    decision.action === "POST_COLLATERAL" || decision.action === "RECALL_COLLATERAL"
      ? "accent"
      : decision.action === "DEMAND_COLLATERAL"
        ? "warn"
        : decision.action === "ESCALATE"
          ? "crit"
          : "default";

  const surface = approval
    ? "panel panel-ok"
    : tone === "accent"
      ? "panel panel-accent"
      : tone === "warn"
        ? "panel panel-warn"
        : tone === "crit"
          ? "panel panel-crit"
          : "panel";

  return (
    <section className={surface}>
      <div className="px-4 py-3.5 flex flex-wrap items-start gap-x-8 gap-y-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <Chip tone={tone}>{decision.action.replace(/_/g, " ")}</Chip>
            <Chip tone={approval ? "accent" : decision.requires_human_approval ? "warn" : "default"}>
              {approval ? "APPROVED" : decision.status.replace(/_/g, " ")}
            </Chip>
            {approval && (
              <span className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
                {approval.approver} · {approval.role} · {approval.occurred_at}
              </span>
            )}
          </div>

          <h2 className="serif m-0 leading-tight" style={{ fontSize: 24, fontWeight: 700 }}>
            {decision.headline}
          </h2>
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-3.5 shrink-0">
          <Stat
            label="Transfer required"
            value={formatMoney(decision.amount)}
            hint={`from ${decision.transferor.replace("_", " ")}`}
            tone={tone === "default" ? "default" : tone}
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

      {decision.requires_human_approval && (
        <div className="px-4 py-3.5 no-print" style={{ borderTop: "1px solid var(--rule)" }}>
          {approval ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
                Recorded in the audit chain as a{" "}
                <span className="mono" style={{ color: "var(--accent)" }}>
                  HUMAN
                </span>{" "}
                event. Approval is a record, not an instruction: AETHER transmits
                nothing.
              </span>
              <Link href="/audit" className="text-[11.5px]">
                See the event →
              </Link>
              {mayApprove && (
                <button
                  className="ml-auto"
                  onClick={() => revoke.mutate()}
                  disabled={revoke.isPending}
                >
                  {revoke.isPending ? "Withdrawing…" : "Withdraw approval"}
                </button>
              )}
            </div>
          ) : mayApprove ? (
            <div className="flex flex-col gap-2.5">
              <label className="eyebrow" htmlFor="approval-note">
                Approval note — recorded permanently in the audit chain
              </label>
              <textarea
                id="approval-note"
                rows={2}
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <div className="flex flex-wrap items-center gap-3">
                <button
                  className="primary"
                  onClick={() => approve.mutate(note)}
                  disabled={approve.isPending || !note.trim()}
                >
                  {approve.isPending
                    ? "Recording…"
                    : `Approve ${formatMoney(decision.amount)}`}
                </button>
                <span className="text-[11.5px]" style={{ color: "var(--ink-faint)" }}>
                  Signed as {identity} ({role}). Records the decision. Executes
                  nothing — there is no settlement connectivity in this system.
                </span>
              </div>
              {approve.isError && (
                <p className="m-0 text-[12px]" style={{ color: "var(--crit)" }}>
                  {approve.error instanceof Error
                    ? approve.error.message
                    : "The approval was refused."}
                </p>
              )}
            </div>
          ) : (
            <p className="m-0 text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
              This decision awaits sign-off from RISK or ADMIN. Your role cannot
              approve a margin transfer, and the API refuses the request
              independently of this interface.
            </p>
          )}
        </div>
      )}

      <p
        className="px-4 py-2 m-0 text-[11px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        {decision.disclaimer}
      </p>
    </section>
  );
}
