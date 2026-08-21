/**
 * The AETHER retrieval assistant.
 *
 * .. rubric:: What this is
 *
 * A **deterministic lookup** over the run currently on screen. It matches a
 * question to a retriever, reads named fields out of the typed `RunResult` — the
 * same object every panel renders — and answers with those values and a pointer to
 * where they are displayed.
 *
 * It is not a language model and this file does not call one. That is a design
 * decision, not a limitation to apologise for: an assistant that answers "what is
 * the collateral requirement" by *retrieving* `margin_call.call_amount` cannot
 * disagree with the dashboard, cannot hallucinate a figure, and cannot drift when
 * the scenario changes. The UI labels it as retrieval so no one mistakes it for
 * something it is not.
 *
 * .. rubric:: The rule it enforces
 *
 * Every answer is assembled from values the engine computed. This module performs
 * **no arithmetic on money**. Where a question asks what changed, the answer comes
 * from the comparison payload, whose deltas were subtracted in Python with
 * `Decimal`. Where the data is not on screen, the assistant says so rather than
 * reaching for something adjacent.
 *
 * .. rubric:: Roles
 *
 * A retriever declares the permission it needs. Asked for contract detail by a
 * role that may not see it, the assistant refuses and names the role that can.
 */

import { can, type Permission, type Role } from "./roles";
import type { Comparison, RunResult } from "./types";

export type AnswerStatus = "ANSWERED" | "UNAVAILABLE" | "NOT_PERMITTED" | "UNKNOWN";

export interface AnswerField {
  label: string;
  value: string;
  /** Set when this figure is the direct answer to the question. */
  headline?: boolean;
}

export interface Answer {
  status: AnswerStatus;
  /** Prose. Never contains a figure that is not also in `fields`. */
  text: string;
  fields: AnswerField[];
  /** Which panel of the app displays these same values. */
  source: string;
  href?: string;
  /** The exact paths read from the run, so a sceptic can check. */
  paths: string[];
}

export interface AssistantContext {
  run: RunResult | null;
  comparison: Comparison | null;
  role: Role | null;
  /** The scenario key currently displayed, for wording. */
  scenarioName: string;
  baselineName: string;
}

interface Retriever {
  id: string;
  /** Terms that pull a question towards this retriever. */
  keywords: string[][];
  /** A question that demonstrates it, offered as a suggestion chip. */
  example: string;
  permission: Permission;
  answer: (context: AssistantContext) => Answer;
}

function money(value: { amount: string; currency: string }): string {
  return `${value.currency} ${value.amount}`;
}

function unavailable(text: string, source = "—"): Answer {
  return { status: "UNAVAILABLE", text, fields: [], source, paths: [] };
}

// ------------------------------------------------------------- retrievers

const RETRIEVERS: Retriever[] = [
  {
    id: "collateral-requirement",
    keywords: [
      ["collateral", "requirement"],
      ["how", "much", "post"],
      ["transfer", "amount"],
      ["delivery", "amount"],
      ["call", "amount"],
      ["margin", "call"],
    ],
    example: "What is the current collateral requirement?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const call = run.margin_call;
      if (call.direction === "NONE") {
        return {
          status: "ANSWERED",
          text:
            "No collateral is required at this snapshot. " +
            run.threshold_status.message,
          fields: [
            { label: "Transfer required", value: money(call.call_amount), headline: true },
            { label: "Credit Support Amount", value: money(call.credit_support_amount) },
            { label: "Threshold", value: money(call.threshold) },
          ],
          source: "Margin waterfall",
          href: "/exposure",
          paths: ["margin_call.call_amount", "margin_call.credit_support_amount"],
        };
      }
      return {
        status: "ANSWERED",
        text:
          `${money(call.call_amount)} is due as a ${call.direction.toLowerCase()} ` +
          `amount from ${call.transferor.replace("_", " ")}. That is the Credit ` +
          `Support Amount of ${money(call.credit_support_amount)} after the ` +
          "Minimum Transfer Amount gate and rounding.",
        fields: [
          { label: "Transfer required", value: money(call.call_amount), headline: true },
          { label: "Credit Support Amount", value: money(call.credit_support_amount) },
          { label: "Unrounded", value: money(call.unrounded_amount) },
          { label: "Minimum Transfer Amount", value: money(call.minimum_transfer_amount) },
          { label: "Transferor", value: call.transferor.replace("_", " ") },
        ],
        source: "Margin waterfall",
        href: "/exposure",
        paths: [
          "margin_call.call_amount",
          "margin_call.credit_support_amount",
          "margin_call.unrounded_amount",
        ],
      };
    },
  },
  {
    id: "exposure",
    keywords: [
      ["exposure"],
      ["mark", "to", "market"],
      ["mtm"],
      ["portfolio", "value"],
      ["netting"],
    ],
    example: "What is the current exposure?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const e = run.exposure;
      return {
        status: "ANSWERED",
        text:
          `Net exposure across ${e.trade_count} trades in netting set ` +
          `${e.netting_set_id} is ${money(e.exposure)}. Netting removes ` +
          `${money(e.netting_benefit)} from a gross positive of ` +
          `${money(e.gross_positive)}.`,
        fields: [
          { label: "Net exposure", value: money(e.exposure), headline: true },
          { label: "Gross positive", value: money(e.gross_positive) },
          { label: "Netting benefit", value: money(e.netting_benefit) },
          { label: "Trades", value: String(e.trade_count) },
        ],
        source: "Netting-set exposure",
        href: "/exposure",
        paths: ["exposure.exposure", "exposure.gross_positive", "exposure.netting_benefit"],
      };
    },
  },
  {
    id: "what-changed",
    keywords: [
      ["what", "changed"],
      ["before", "after"],
      ["market", "movement"],
      ["impact"],
      ["delta"],
      ["difference", "between"],
    ],
    example: "What changed after the market movement?",
    permission: "view:desk",
    answer: ({ comparison }) => {
      if (!comparison) {
        return unavailable(
          "The before/after comparison has not loaded. Open Workflow & Impact to " +
            "run it.",
          "Before / after",
        );
      }
      const pick = (id: string) => comparison.metrics.find((m) => m.id === id);
      const mtm = pick("portfolio_mtm");
      const csa = pick("credit_support_amount");
      const call = pick("call_amount");

      const fields: AnswerField[] = comparison.metrics
        .filter((m) => m.comparable && m.delta)
        .map((m) => ({
          label: m.label,
          value: `${money(m.before)} → ${money(m.after)}  (${m.delta ? money(m.delta) : ""})`,
          headline: m.id === "call_amount",
        }));

      return {
        status: "ANSWERED",
        text:
          `Between ${comparison.before.snapshot_label} (${comparison.before.as_of}) and ` +
          `${comparison.after.snapshot_label} (${comparison.after.as_of}): ` +
          (mtm?.delta ? `mark-to-market moved by ${money(mtm.delta)}, ` : "") +
          (csa?.delta ? `the Credit Support Amount by ${money(csa.delta)}, ` : "") +
          (call?.delta ? `and the transfer required by ${money(call.delta)}. ` : "") +
          `Threshold status went from ${comparison.before.threshold_status.state} to ` +
          `${comparison.after.threshold_status.state}.` +
          (comparison.transferor_changed
            ? " The Transferor also changed, so the other party's Threshold now governs."
            : ""),
        fields,
        source: "Before / after comparison",
        href: "/workflow",
        paths: ["comparison.metrics[*].delta"],
      };
    },
  },
  {
    id: "why-selected",
    keywords: [
      ["why", "selected"],
      ["why", "chosen"],
      ["why", "treasury"],
      ["why", "this", "collateral"],
      ["why", "posted"],
      ["cheapest"],
      ["rationale"],
      ["why", "decision"],
    ],
    example: "Why was this collateral selected?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const allocation = run.allocation;
      if (!allocation || allocation.status !== "OPTIMAL") {
        return unavailable(
          "No allocation was produced at this snapshot, so there is no selection " +
            "to explain.",
          "Collateral optimisation",
        );
      }
      const binding = allocation.shadow_prices.filter((s) => s.binding);
      return {
        status: "ANSWERED",
        text:
          `The optimiser selected ${allocation.lines.length} assets by cost per ` +
          "effective unit — funding spread divided by the effective valuation " +
          "percentage — not by headline spread. Every selected asset is eligible " +
          `under the Annex. ${binding.length} constraint` +
          `${binding.length === 1 ? "" : "s"} bound the solution: ` +
          `${binding.map((b) => b.description).join("; ")}. The result costs ` +
          `${money(allocation.total_cost)} a year against ` +
          `${money(allocation.baseline_cost)} for a cash-first allocation.`,
        fields: [
          ...allocation.lines.map((line) => ({
            label: line.asset_id,
            value:
              `${money(line.market_value_posted)} posted, ` +
              `${line.cost_per_effective_unit_bps}bp per effective unit`,
          })),
          { label: "Optimised cost", value: money(allocation.total_cost), headline: true },
          { label: "Cash-first baseline", value: money(allocation.baseline_cost) },
          { label: "Saving", value: money(allocation.saving) },
        ],
        source: "Collateral optimisation",
        href: "/optimisation",
        paths: [
          "allocation.lines[*].cost_per_effective_unit_bps",
          "allocation.shadow_prices[?binding]",
          "allocation.total_cost",
        ],
      };
    },
  },
  {
    id: "not-selected",
    keywords: [
      ["why", "not", "used"],
      ["why", "not", "selected"],
      ["rejected"],
      ["excluded"],
      ["not", "posted"],
    ],
    example: "Why was an asset excluded?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run?.allocation) {
        return unavailable(
          "No allocation ran at this snapshot, so nothing was excluded.",
          "Collateral optimisation",
        );
      }
      const { excluded, considered } = run.allocation;
      const rejected = considered.filter((line) => !line.selected);
      return {
        status: "ANSWERED",
        text:
          `${excluded.length} asset${excluded.length === 1 ? " was" : "s were"} ` +
          `excluded from the eligible set outright, and ${rejected.length} eligible ` +
          "asset" +
          `${rejected.length === 1 ? " was" : "s were"} considered and not used. ` +
          "Reasons are read from the solved problem rather than guessed at.",
        fields: [
          ...excluded.map((item) => ({
            label: `${item.asset_id} (ineligible)`,
            value: item.reason,
          })),
          ...rejected.slice(0, 6).map((line) => ({
            label: `${line.asset_id} (not used)`,
            value: line.not_selected_reason,
          })),
        ],
        source: "Considered and not used",
        href: "/optimisation",
        paths: ["allocation.excluded[*].reason", "allocation.considered[?!selected]"],
      };
    },
  },
  {
    id: "threshold",
    keywords: [
      ["threshold"],
      ["breach"],
      ["limit"],
      ["mta"],
      ["minimum", "transfer"],
      ["within"],
    ],
    example: "Is the threshold breached?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const t = run.threshold_status;
      return {
        status: "ANSWERED",
        text: `Threshold status is ${t.state}. ${t.message}`,
        fields: [
          { label: "Status", value: t.state, headline: true },
          { label: "Net exposure", value: money(t.exposure) },
          { label: "Threshold", value: money(t.threshold) },
          { label: "Credit Support Amount", value: money(t.credit_support_amount) },
          { label: "Minimum Transfer Amount", value: money(t.minimum_transfer_amount) },
          { label: "Gated by MTA", value: t.gated_by_mta ? "Yes" : "No" },
        ],
        source: "Threshold status",
        href: "/",
        paths: ["threshold_status.state", "margin_call.threshold"],
      };
    },
  },
  {
    id: "decision",
    keywords: [
      ["decision"],
      ["what", "happens", "next"],
      ["next", "step"],
      ["action"],
      ["recommend"],
    ],
    example: "What happens next?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const d = run.decision;
      const approval = run.approval;
      return {
        status: "ANSWERED",
        text:
          `${d.headline} Status is ${d.status.replace(/_/g, " ")}. ` +
          (approval
            ? `Approved by ${approval.approver} at ${approval.occurred_at}. ` +
              "Recording an approval does not execute a transfer — AETHER has no " +
              "settlement connectivity."
            : d.requires_human_approval
              ? "It awaits a named approver from RISK or ADMIN. Nothing moves until " +
                "someone signs, and AETHER moves nothing regardless."
              : "No approval is required."),
        fields: [
          { label: "Action", value: d.action.replace(/_/g, " "), headline: true },
          { label: "Amount", value: money(d.amount) },
          { label: "Status", value: d.status.replace(/_/g, " ") },
          ...(approval
            ? [
                { label: "Approver", value: approval.approver },
                { label: "Approved at", value: approval.occurred_at },
              ]
            : []),
        ],
        source: "Decision",
        href: "/",
        paths: ["decision.action", "decision.status", "approval"],
      };
    },
  },
  {
    id: "initial-margin",
    keywords: [
      ["initial", "margin"],
      ["im"],
      ["simm"],
      ["sensitivit"],
      ["schedule", "margin"],
    ],
    example: "What is the initial margin?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const s = run.sensitivity_margin;
      const g = run.initial_margin;
      return {
        status: "ANSWERED",
        text:
          `Two figures, neither charged to this variation margin call. The ` +
          `risk-weighted sensitivity model returns ${money(s.total_margin)}; the ` +
          `BCBS-IOSCO standardised schedule returns ${money(g.initial_margin)}. ` +
          "The sensitivity weights are AETHER's own and are not certified — this " +
          "is not ISDA SIMM.",
        fields: [
          { label: "Sensitivity margin", value: money(s.total_margin), headline: true },
          { label: "Schedule margin", value: money(g.initial_margin) },
          { label: "Rates", value: money(s.interest_rate_margin) },
          { label: "FX", value: money(s.fx_margin) },
          { label: "Charged to VM call", value: "No" },
        ],
        source: "Initial margin — two methods",
        href: "/exposure",
        paths: ["sensitivity_margin.total_margin", "initial_margin.initial_margin"],
      };
    },
  },
  {
    id: "audit",
    keywords: [
      ["audit"],
      ["hash"],
      ["chain"],
      ["tamper"],
      ["evidence"],
      ["verified"],
    ],
    example: "Is the audit chain verified?",
    permission: "view:audit",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const a = run.audit;
      const byType = (type: string) =>
        a.events.filter((e) => e.actor_type === type).length;
      return {
        status: "ANSWERED",
        text:
          `${a.verification_message} The chain covers ${byType("AGENT")} agent ` +
          `decisions, ${byType("ENGINE")} engine computations and ${byType("HUMAN")} ` +
          "human actions. It is tamper-evident, not a blockchain.",
        fields: [
          { label: "Verified", value: a.verified ? "Yes" : `No — broken at ${a.break_at}`, headline: true },
          { label: "Events", value: String(a.events.length) },
          { label: "Head hash", value: a.head_hash },
          { label: "Chain", value: a.chain_id },
        ],
        source: "Audit trail",
        href: "/audit",
        paths: ["audit.verified", "audit.head_hash", "audit.events"],
      };
    },
  },
  {
    id: "contract-terms",
    keywords: [
      ["csa"],
      ["contract"],
      ["annex"],
      ["clause"],
      ["terms"],
      ["agreement"],
      ["paragraph"],
    ],
    example: "What terms did the agent extract?",
    permission: "view:contract",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      const a = run.agreement;
      return {
        status: "ANSWERED",
        text:
          `Agreement ${a.agreement_id} under ${a.governing_law}, terms version ` +
          `${a.terms_version}. ` +
          (run.terms_source === "FROZEN_FROM_REVIEWED_EXTRACTION"
            ? "These terms were frozen from a reviewed extraction, so a reviewer's " +
              "decision governs this calculation."
            : "These are the committed fixture terms; no extraction has been " +
              "reviewed and frozen in this session."),
        fields: [
          { label: "Party A Threshold", value: money(a.party_a.threshold), headline: true },
          { label: "Party B Threshold", value: money(a.party_b.threshold) },
          { label: "Minimum Transfer Amount", value: money(a.party_a.minimum_transfer_amount) },
          { label: "Rounding increment", value: money(a.rounding.increment) },
          { label: "FX haircut", value: `${(Number(a.fx_haircut_pct) * 100).toFixed(1)}%` },
          { label: "Excluded issuers", value: a.excluded_issuers.join(", ") || "none" },
          { label: "Eligible collateral", value: `${a.eligible_collateral.length} schedule items` },
        ],
        source: "Contract terms",
        href: "/review",
        paths: ["agreement.party_a.threshold", "agreement.rounding", "terms_source"],
      };
    },
  },
  {
    id: "provenance",
    keywords: [
      ["snapshot"],
      ["reproducib"],
      ["deterministic"],
      ["engine", "version"],
      ["trace"],
      ["simulated"],
      ["real", "data"],
    ],
    example: "Is this real market data?",
    permission: "view:desk",
    answer: ({ run }) => {
      if (!run) return unavailable("No run is loaded.");
      return {
        status: "ANSWERED",
        text:
          "No. Every market figure here comes from a pinned, simulated snapshot. " +
          "Snapshots are pinned rather than live so that the same inputs reproduce " +
          "the same audit hash on any machine. No calculation in this system reads " +
          "a live feed.",
        fields: [
          { label: "Snapshot", value: run.snapshot.snapshot_id, headline: true },
          { label: "Label", value: run.snapshot.label },
          { label: "As of", value: run.as_of },
          { label: "Engine version", value: run.engine_version },
          { label: "Trace", value: run.trace_id },
          { label: "Simulated", value: "Yes — all data" },
        ],
        source: "Run provenance",
        href: "/methodology",
        paths: ["snapshot.snapshot_id", "engine_version", "trace_id"],
      };
    },
  },
];

/** Suggestion chips, in the order a demo would walk them. */
export const SUGGESTIONS: string[] = [
  "What is the current collateral requirement?",
  "What changed after the market movement?",
  "Why was this collateral selected?",
  "Is the threshold breached?",
  "What happens next?",
  "Is the audit chain verified?",
];

// ------------------------------------------------------------------ routing

function normalise(question: string): string {
  return question.toLowerCase().replace(/[^a-z0-9\s]/g, " ");
}

/**
 * Score a question against a retriever's keyword groups.
 *
 * A group scores only when *every* term in it appears, so "why not used" does not
 * also fire the "why selected" retriever on the word "why" alone. Longer groups
 * score higher, which lets a specific phrasing beat a general one.
 */
function score(question: string, retriever: Retriever): number {
  const text = ` ${normalise(question)} `;
  let best = 0;
  for (const group of retriever.keywords) {
    if (group.every((term) => text.includes(term))) {
      best = Math.max(best, group.length * 10 + group.join("").length);
    }
  }
  return best;
}

/**
 * Answer a question from the run currently on screen.
 *
 * Returns `UNKNOWN` rather than a plausible-sounding paragraph when nothing
 * matches. Saying "I do not hold that" is the correct behaviour for a retrieval
 * assistant over financial data, and inventing an answer would be the single most
 * damaging thing this component could do.
 */
export function ask(question: string, context: AssistantContext): Answer {
  const trimmed = question.trim();
  if (!trimmed) {
    return {
      status: "UNKNOWN",
      text: "Ask about the collateral requirement, exposure, what changed, or why an asset was selected.",
      fields: [],
      source: "—",
      paths: [],
    };
  }

  const ranked = RETRIEVERS.map((retriever) => ({
    retriever,
    weight: score(trimmed, retriever),
  }))
    .filter((entry) => entry.weight > 0)
    .sort((a, b) => b.weight - a.weight);

  const match = ranked[0]?.retriever;
  if (!match) {
    return {
      status: "UNKNOWN",
      text:
        "I do not hold an answer to that. I retrieve values from the run on " +
        "screen — exposure, margin, threshold status, the allocation and its " +
        "reasons, the decision and the audit chain. I do not calculate, and I do " +
        "not answer from outside this run.",
      fields: [],
      source: "—",
      paths: [],
    };
  }

  if (!can(context.role, match.permission)) {
    return {
      status: "NOT_PERMITTED",
      text:
        `Your role does not have access to that. Answering would require the ` +
        `"${match.permission}" permission. Sign in as a role that holds it.`,
      fields: [],
      source: "Access control",
      paths: [],
    };
  }

  return match.answer(context);
}
