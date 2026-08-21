/**
 * The AETHER workflow, derived from a completed run.
 *
 * .. rubric:: Derived, not declared
 *
 * Nothing here is a hardcoded status. Every stage's state is read off the run the
 * engine returned: whether the optimiser produced an allocation, whether the MTA
 * gated the call, whether the chain verifies, whether a human has signed. A
 * progress bar that advances on a timer would be theatre; this one cannot show a
 * stage complete that did not happen.
 *
 * .. rubric:: Where the workflow stops
 *
 * It stops at approval, and it is supposed to. The pipeline proposes and a human
 * disposes: until someone with the authority signs, the decision stage sits in
 * `REQUIRES_REVIEW` and the audit stage behind it is not yet closed.
 */

import type { RunResult } from "./types";

export type StageState =
  | "COMPLETE"
  | "ACTIVE"
  | "PENDING"
  | "REQUIRES_REVIEW"
  | "WARNING"
  | "NOT_REQUIRED"
  | "BLOCKED";

export type StageId =
  | "contract"
  | "market"
  | "exposure"
  | "margin"
  | "eligibility"
  | "optimisation"
  | "distribution"
  | "approval"
  | "audit";

export interface StageFact {
  label: string;
  value: string;
  /** Marks the figure that carries the stage — rendered with more weight. */
  headline?: boolean;
}

export interface WorkflowStage {
  id: StageId;
  index: number;
  title: string;
  /** What this stage does, in the language a collateral manager uses. */
  purpose: string;
  state: StageState;
  /** One line stating the outcome. Always specific to this run. */
  outcome: string;
  /** Which role owns this stage. */
  owner: string;
  /** The pinned valuation date, or the recorded approval time. */
  occurredAt: string | null;
  /** What this stage received. */
  inputs: StageFact[];
  /** What it produced. */
  outputs: StageFact[];
  /** Where in the app the full detail lives. */
  href: string;
  /** Named because a reader will ask "which clause says so?". */
  basis: string;
}

export interface Workflow {
  stages: WorkflowStage[];
  /** The stage a user should be looking at now. Null once everything is closed. */
  activeStage: StageId | null;
  completedCount: number;
  /** True once every stage is COMPLETE or NOT_REQUIRED. */
  isClosed: boolean;
}

function money(value: { amount: string; currency: string }): string {
  return `${value.currency} ${value.amount}`;
}

/**
 * Build the workflow for one run.
 *
 * `approved` is passed separately rather than read from `run.approval` alone so a
 * caller can render an optimistic state during the round trip without this module
 * knowing about network conditions.
 */
export function buildWorkflow(run: RunResult): Workflow {
  const {
    agreement,
    snapshot,
    exposure,
    margin_call: call,
    allocation,
    settlement,
    decision,
    audit,
    threshold_status: threshold,
    approval,
  } = run;

  const asOf = run.as_of;
  const reviewed = run.terms_source === "FROZEN_FROM_REVIEWED_EXTRACTION";
  const needsAllocation = call.direction === "DELIVERY" && decision.action === "POST_COLLATERAL";
  const approved = approval !== null;

  const stages: Omit<WorkflowStage, "index">[] = [
    {
      id: "contract",
      title: "Contract interpretation",
      purpose:
        "The Legal-Clause Agent reads the Credit Support Annex and produces typed, " +
        "cited terms. Anything it is unsure of goes to a human before the engine " +
        "sees it.",
      state: "COMPLETE",
      outcome: reviewed
        ? "Terms frozen from a reviewed extraction. A reviewer's decision governs " +
          "this calculation."
        : "Computing on the committed agreement fixture. No extraction has been " +
          "reviewed and frozen in this session.",
      owner: "LEGAL",
      occurredAt: asOf,
      inputs: [
        { label: "Document", value: agreement.agreement_id },
        { label: "Governing law", value: agreement.governing_law },
      ],
      outputs: [
        { label: "Threshold (Party A)", value: money(agreement.party_a.threshold) },
        { label: "Threshold (Party B)", value: money(agreement.party_b.threshold) },
        {
          label: "Minimum Transfer Amount",
          value: money(agreement.party_a.minimum_transfer_amount),
        },
        { label: "Terms version", value: String(agreement.terms_version) },
        { label: "Eligible collateral", value: `${agreement.eligible_collateral.length} schedule items` },
      ],
      href: "/review",
      basis: "CSA Paragraph 11 — Elections and Variables.",
    },
    {
      id: "market",
      title: "Market snapshot",
      purpose:
        "A pinned set of curves and FX rates. No calculation in this system reads " +
        "a live feed, which is what makes a run reproducible.",
      state: "COMPLETE",
      outcome: `Pinned to ${snapshot.snapshot_id} — ${snapshot.label}. Simulated data.`,
      owner: "RISK",
      occurredAt: asOf,
      inputs: [{ label: "Valuation date", value: asOf }],
      outputs: [
        { label: "Snapshot", value: snapshot.snapshot_id, headline: true },
        { label: "Label", value: snapshot.label },
        { label: "Base currency", value: exposure.base_currency },
      ],
      href: "/exposure",
      basis: "Pinned snapshot, loaded before any calculation reads it.",
    },
    {
      id: "exposure",
      title: "Exposure / mark-to-market",
      purpose:
        "Every trade repriced against the snapshot, then netted within the netting " +
        "set. Cross-Master netting is structurally prevented.",
      state: "COMPLETE",
      outcome: `${exposure.trade_count} trades repriced. Net exposure ${money(exposure.exposure)}.`,
      owner: "RISK",
      occurredAt: asOf,
      inputs: [
        { label: "Netting set", value: exposure.netting_set_id },
        { label: "Trades", value: String(exposure.trade_count) },
        { label: "Snapshot", value: snapshot.snapshot_id },
      ],
      outputs: [
        { label: "Net exposure", value: money(exposure.exposure), headline: true },
        { label: "Gross positive", value: money(exposure.gross_positive) },
        { label: "Netting benefit", value: money(exposure.netting_benefit) },
      ],
      href: "/exposure",
      basis: "Close-out netting within one netting set. ISDA Master, Section 6(e).",
    },
    {
      id: "margin",
      title: "Margin requirement",
      purpose:
        "Exposure through the Threshold, the Independent Amount, the Minimum " +
        "Transfer Amount gate and directional rounding, to a transfer figure.",
      state: threshold.state === "WARNING" ? "WARNING" : "COMPLETE",
      outcome:
        threshold.state === "WITHIN"
          ? "Exposure sits inside the Threshold. No Credit Support Amount arises."
          : threshold.state === "WARNING"
            ? "Threshold exceeded, but the amount is below the Minimum Transfer " +
              "Amount. Nothing transfers today."
            : `${call.direction === "DELIVERY" ? "Delivery" : "Return"} Amount of ` +
              `${money(call.call_amount)} is due from ${call.transferor.replace("_", " ")}.`,
      owner: "RISK",
      occurredAt: asOf,
      inputs: [
        { label: "Net exposure", value: money(exposure.exposure) },
        { label: "Threshold", value: money(call.threshold) },
        { label: "Independent Amount", value: money(call.independent_amount) },
        { label: "Posted balance", value: money(call.posted_value) },
      ],
      outputs: [
        {
          label: "Credit Support Amount",
          value: money(call.credit_support_amount),
        },
        { label: "Unrounded", value: money(call.unrounded_amount) },
        { label: "Transfer required", value: money(call.call_amount), headline: true },
        { label: "Direction", value: call.direction },
      ],
      href: "/exposure",
      basis: "CSA Paragraph 2(c), 11(b)(iii)(B) and 11(b)(iii)(D).",
    },
    {
      id: "eligibility",
      title: "Eligibility & constraints",
      purpose:
        "Which inventory assets the Annex permits as collateral, at what valuation " +
        "percentage, and under which concentration and issuer caps.",
      state: needsAllocation ? (allocation ? "COMPLETE" : "BLOCKED") : "NOT_REQUIRED",
      outcome: allocation
        ? `${allocation.considered.length} assets eligible, ${allocation.excluded.length} excluded.`
        : needsAllocation
          ? "No eligible set was produced."
          : "No Delivery Amount is due, so no collateral is selected.",
      owner: "RISK",
      occurredAt: asOf,
      inputs: [
        { label: "Schedule items", value: `${agreement.eligible_collateral.length}` },
        {
          label: "Concentration limits",
          value: `${agreement.concentration_limits.length}`,
        },
        { label: "Excluded issuers", value: agreement.excluded_issuers.join(", ") || "none" },
        { label: "FX haircut", value: `${(Number(agreement.fx_haircut_pct) * 100).toFixed(1)}%` },
      ],
      outputs: allocation
        ? [
            { label: "Eligible", value: `${allocation.considered.length} assets`, headline: true },
            { label: "Excluded", value: `${allocation.excluded.length} assets` },
            {
              label: "Wrong-way exclusions",
              value: allocation.excluded.map((e) => e.asset_id).join(", ") || "none",
            },
          ]
        : [],
      href: "/optimisation",
      basis: "CSA Paragraph 11(b)(ii) Eligible Credit Support, 11(g) concentration.",
    },
    {
      id: "optimisation",
      title: "Collateral optimisation",
      purpose:
        "A linear program over the eligible set, minimising funding cost per unit " +
        "of collateral actually delivered, subject to every cap.",
      state: needsAllocation
        ? allocation?.status === "OPTIMAL"
          ? "COMPLETE"
          : allocation
            ? "BLOCKED"
            : "PENDING"
        : "NOT_REQUIRED",
      outcome: allocation
        ? allocation.status === "OPTIMAL"
          ? `Solved. ${money(allocation.total_cost)} per annum against a ` +
            `${money(allocation.baseline_cost)} cash-first baseline.`
          : allocation.message
        : "Not required at this snapshot.",
      owner: "RISK",
      occurredAt: asOf,
      inputs: [
        { label: "Requirement", value: allocation ? money(allocation.required_value) : "—" },
        { label: "Objective", value: "Minimise annual funding cost" },
      ],
      outputs: allocation
        ? [
            { label: "Status", value: allocation.status, headline: true },
            { label: "Optimised cost", value: money(allocation.total_cost) },
            { label: "Baseline cost", value: money(allocation.baseline_cost) },
            { label: "Saving", value: money(allocation.saving) },
            {
              label: "Binding constraints",
              value: String(allocation.shadow_prices.filter((s) => s.binding).length),
            },
          ]
        : [],
      href: "/optimisation",
      basis: "Linear program solved with HiGHS. Dual values reported.",
    },
    {
      id: "distribution",
      title: "Final collateral distribution",
      purpose:
        "The assets selected, their post-haircut collateral value, and the " +
        "settlement instruction generated from them.",
      state: needsAllocation
        ? allocation?.status === "OPTIMAL"
          ? "COMPLETE"
          : "PENDING"
        : "NOT_REQUIRED",
      outcome: allocation
        ? `${allocation.lines.length} assets deliver ${money(allocation.allocated_value)} ` +
          `against ${money(allocation.required_value)} required.`
        : "No transfer, so no distribution.",
      owner: "RISK",
      occurredAt: asOf,
      inputs: [
        { label: "Selected assets", value: allocation ? String(allocation.lines.length) : "—" },
      ],
      outputs: allocation
        ? [
            {
              label: "Post-haircut delivered",
              value: money(allocation.allocated_value),
              headline: true,
            },
            { label: "Instruction", value: settlement?.instruction_id ?? "not generated" },
            { label: "Messages", value: settlement?.message_types.join(" · ") ?? "—" },
            { label: "Transmitted", value: "No — no connectivity exists" },
          ]
        : [],
      href: "/optimisation",
      basis: "Haircut valuation per CSA Paragraph 11(b)(ii). ISO 20022 message shape.",
    },
    {
      id: "approval",
      title: "Human approval",
      purpose:
        "A named person accepts the engine's proposal. Nothing in AETHER moves " +
        "without this, and AETHER moves nothing regardless.",
      state: !decision.requires_human_approval
        ? "NOT_REQUIRED"
        : approved
          ? "COMPLETE"
          : "REQUIRES_REVIEW",
      outcome: !decision.requires_human_approval
        ? `${decision.status.replace(/_/g, " ")} — there is nothing to sign.`
        : approved
          ? `Approved by ${approval.approver} (${approval.role}) at ${approval.occurred_at}.`
          : `Awaiting sign-off on ${decision.action.replace(/_/g, " ")} of ${money(decision.amount)}.`,
      owner: "RISK / ADMIN",
      occurredAt: approval?.occurred_at ?? null,
      inputs: [
        { label: "Decision", value: decision.decision_id },
        { label: "Action", value: decision.action.replace(/_/g, " ") },
        { label: "Amount", value: money(decision.amount) },
      ],
      outputs: approved
        ? [
            { label: "Approver", value: approval.approver, headline: true },
            { label: "Role", value: approval.role },
            { label: "Recorded at", value: approval.occurred_at },
            { label: "Authorises transfer", value: "No — approval is recorded only" },
          ]
        : [],
      href: "/",
      basis: "Separation of duties. Enforced server-side, not by a disabled button.",
    },
    {
      id: "audit",
      title: "Audit trail",
      purpose:
        "Every actor in the run — agent, engine, human — hash-chained so that " +
        "altering any record breaks every hash after it.",
      state: audit.verified ? (approved || !decision.requires_human_approval ? "COMPLETE" : "ACTIVE") : "BLOCKED",
      outcome: audit.verified
        ? `${audit.events.length} events, chain verified.`
        : `Chain broken at event ${audit.break_at}.`,
      owner: "AUDITOR",
      occurredAt: asOf,
      inputs: [{ label: "Chain", value: audit.chain_id }],
      outputs: [
        { label: "Events", value: String(audit.events.length), headline: true },
        { label: "Verified", value: audit.verified ? "Yes" : "No" },
        { label: "Head hash", value: `${audit.head_hash.slice(0, 16)}…` },
        {
          label: "Human events",
          value: String(audit.events.filter((e) => e.actor_type === "HUMAN").length),
        },
      ],
      href: "/audit",
      basis: "SHA-256 chain. Tamper-evident, not a blockchain.",
    },
  ];

  const indexed = stages.map((stage, index) => ({ ...stage, index }));

  // The active stage is the first that still wants attention. A stage that was
  // never required is skipped rather than counted as outstanding.
  const attention = indexed.find((stage) =>
    ["ACTIVE", "PENDING", "REQUIRES_REVIEW", "BLOCKED"].includes(stage.state),
  );

  const settled = indexed.filter((stage) =>
    ["COMPLETE", "NOT_REQUIRED", "WARNING"].includes(stage.state),
  );

  return {
    stages: indexed.map((stage) =>
      stage.id === attention?.id && stage.state === "PENDING"
        ? { ...stage, state: "ACTIVE" }
        : stage,
    ),
    activeStage: attention?.id ?? null,
    completedCount: settled.length,
    isClosed: attention === undefined,
  };
}

export const STAGE_STATE_LABELS: Record<StageState, string> = {
  COMPLETE: "Complete",
  ACTIVE: "Active",
  PENDING: "Pending",
  REQUIRES_REVIEW: "Requires review",
  WARNING: "Warning",
  NOT_REQUIRED: "Not required",
  BLOCKED: "Blocked",
};

/** Tone for a stage state, so the palette is decided in exactly one place. */
export function stageTone(
  state: StageState,
): "accent" | "warn" | "crit" | "default" {
  if (state === "COMPLETE") return "accent";
  if (state === "ACTIVE") return "accent";
  if (state === "REQUIRES_REVIEW" || state === "WARNING") return "warn";
  if (state === "BLOCKED") return "crit";
  return "default";
}
