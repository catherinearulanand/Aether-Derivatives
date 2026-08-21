"use client";

import { ProcessTracker, StageDetail, TrackerLegend } from "@/components/ProcessTracker";
import { BeforeAfter } from "@/components/BeforeAfter";
import {
  Chip,
  Delta,
  ErrorPanel,
  Panel,
  Skeleton,
  StatusPill,
} from "@/components/primitives";
import { formatMoney } from "@/lib/format";
import { useComparison, useCurrentRun, useWorkflow } from "@/lib/hooks";
import { STAGE_STATE_LABELS, stageTone, type StageId } from "@/lib/workflow";
import Link from "next/link";
import { useState } from "react";

/**
 * Workflow & Impact.
 *
 * .. rubric:: The deduction chain
 *
 * The dashboard shows what AETHER concluded. This screen shows how it got there:
 * every stage, opened, with what it received, what it produced, and the clause or
 * method that connects the two. A reader who disagrees with the final number can
 * walk backwards until they find the stage they disagree with.
 *
 * Stages are expandable rather than all-open because nine stages of detail at once
 * is a wall, and a wall is not explainability. The stage awaiting attention opens
 * by default — that is the one the user came for.
 */
export default function WorkflowPage() {
  const run = useCurrentRun();
  const comparison = useComparison();
  const workflow = useWorkflow();

  const [open, setOpen] = useState<Set<StageId>>(new Set());
  const [touched, setTouched] = useState(false);

  // Until the user expresses a preference, the active stage stands open. After
  // that their selection is the truth, including when it is "nothing open".
  const effectiveOpen =
    touched || !workflow?.activeStage ? open : new Set<StageId>([workflow.activeStage]);

  function toggle(id: StageId) {
    setTouched(true);
    setOpen((previous) => {
      const next = new Set(touched ? previous : effectiveOpen);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

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
            Workflow &amp; Impact
          </h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "82ch" }}
          >
            Every stage between the contract and the audit record, with the values
            that entered it and the values it produced. Open a stage to see the
            working; the figures are the engine&apos;s own, not a description of them.
          </p>
        </div>
        {run.data && (
          <div className="ml-auto flex items-center gap-2">
            <StatusPill
              state={run.data.threshold_status.state}
              title={run.data.threshold_status.message}
            />
            <Chip>{run.data.snapshot.snapshot_id}</Chip>
            <Chip>{run.data.trace_id}</Chip>
          </div>
        )}
      </header>

      {run.isLoading || !workflow ? (
        <Panel title="Process">
          <Skeleton rows={5} height={20} />
        </Panel>
      ) : (
        <>
          <Panel
            title="Process"
            aside={
              <Chip tone={workflow.isClosed ? "accent" : "warn"}>
                {workflow.activeStage
                  ? `Active: ${workflow.stages.find((s) => s.id === workflow.activeStage)?.title}`
                  : "All stages settled"}
              </Chip>
            }
          >
            <ProcessTracker
              workflow={workflow}
              selected={[...effectiveOpen][0] ?? null}
              onSelect={toggle}
            />
            <TrackerLegend />
          </Panel>

          <Panel
            title="Stages"
            aside={
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    setTouched(true);
                    setOpen(new Set(workflow.stages.map((s) => s.id)));
                  }}
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  Expand all
                </button>
                <button
                  onClick={() => {
                    setTouched(true);
                    setOpen(new Set());
                  }}
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  Collapse
                </button>
              </div>
            }
          >
            <div className="divide-y" style={{ borderColor: "var(--rule)" }}>
              {workflow.stages.map((stage) => {
                const expanded = effectiveOpen.has(stage.id);
                const headline =
                  stage.outputs.find((o) => o.headline) ?? stage.outputs[0];

                return (
                  <div key={stage.id}>
                    <button
                      className="disclosure"
                      aria-expanded={expanded}
                      onClick={() => toggle(stage.id)}
                    >
                      <span className="disclosure-marker" aria-hidden="true">
                        ▶
                      </span>

                      <span
                        className="mono text-[9.5px] shrink-0"
                        style={{ color: "var(--ink-faint)", width: 20 }}
                      >
                        {String(stage.index + 1).padStart(2, "0")}
                      </span>

                      <span
                        className="shrink-0"
                        style={{ width: 200, fontWeight: 600 }}
                      >
                        {stage.title}
                      </span>

                      <span
                        className="hidden lg:block flex-1 min-w-0 truncate text-[11.5px]"
                        style={{ color: "var(--ink-mute)" }}
                      >
                        {stage.outcome}
                      </span>

                      {headline && (
                        <span
                          className="tnum text-[11.5px] shrink-0 text-right hidden md:block"
                          style={{ width: 190, color: "var(--ink)" }}
                        >
                          {headline.value}
                        </span>
                      )}

                      <span className="shrink-0">
                        <Chip tone={stageTone(stage.state)}>
                          {STAGE_STATE_LABELS[stage.state]}
                        </Chip>
                      </span>
                    </button>

                    {expanded && (
                      <>
                        <StageDetail stage={stage} />
                        <div
                          className="px-4 py-2 flex items-center gap-4"
                          style={{
                            background: "var(--surface-2)",
                            borderTop: "1px solid var(--rule)",
                          }}
                        >
                          <Link href={stage.href} className="text-[11.5px]">
                            Open the full {stage.title.toLowerCase()} screen →
                          </Link>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </Panel>

          {/* The change each stage saw, on one surface. This is the answer to
              "how did the market movement propagate?" — not narrated, tabulated. */}
          {comparison.data ? (
            <>
              <StagePropagation comparison={comparison.data} />
              <BeforeAfter comparison={comparison.data} />
            </>
          ) : comparison.isLoading ? (
            <Panel title="Propagation">
              <Skeleton rows={4} />
            </Panel>
          ) : (
            <Panel title="Propagation">
              <p
                className="px-4 py-6 m-0 text-[12.5px]"
                style={{ color: "var(--ink-mute)" }}
              >
                Choose a different baseline in the bar above to see how a market
                movement propagates through the stages.
              </p>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

/**
 * Propagation.
 *
 * The same four figures the workflow computes in sequence, shown as a chain with
 * the change at each link. Read top to bottom it is the causal claim the product
 * makes: the market moved, so exposure moved, so the requirement moved, so the
 * allocation moved.
 */
function StagePropagation({
  comparison,
}: {
  comparison: NonNullable<ReturnType<typeof useComparison>["data"]>;
}) {
  const chain = [
    { id: "portfolio_mtm", stage: "Exposure", caption: "The book is repriced against the new snapshot." },
    { id: "credit_support_amount", stage: "Margin", caption: "Exposure less Threshold gives the requirement." },
    { id: "call_amount", stage: "Transfer", caption: "MTA gate and rounding give the amount that moves." },
    { id: "collateral_post_haircut", stage: "Distribution", caption: "The optimiser posts collateral to cover it." },
  ];

  return (
    <Panel
      title="How the movement propagated"
      aside={
        <Chip title="Every delta was subtracted in Python with Decimal, not in the browser.">
          exact deltas
        </Chip>
      }
    >
      <div className="px-4 py-4 flex flex-col gap-0">
        {chain.map((link, index) => {
          const metric = comparison.metrics.find((m) => m.id === link.id);
          if (!metric) return null;

          return (
            <div key={link.id}>
              <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5 py-2.5">
                <span
                  className="eyebrow shrink-0"
                  style={{ width: 100, color: "var(--accent)" }}
                >
                  {link.stage}
                </span>

                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px]">{metric.label}</div>
                  <div
                    className="text-[11px] leading-snug"
                    style={{ color: "var(--ink-faint)" }}
                  >
                    {link.caption}
                  </div>
                </div>

                <span
                  className="tnum text-[11.5px] shrink-0 text-right"
                  style={{ width: 160, color: "var(--ink-faint)" }}
                >
                  {metric.before_available ? formatMoney(metric.before) : "not computed"}
                </span>

                <span
                  className="tnum text-[13px] font-semibold shrink-0 text-right"
                  style={{ width: 170 }}
                >
                  {metric.after_available ? formatMoney(metric.after) : "not computed"}
                </span>

                <span className="shrink-0 text-right" style={{ width: 170 }}>
                  <Delta
                    value={metric.delta}
                    direction={metric.direction}
                    unavailable={metric.unavailable_reason}
                  />
                </span>
              </div>

              {index < chain.length - 1 && (
                <div
                  className="mono text-[11px] pl-[104px]"
                  style={{ color: "var(--ink-faint)", lineHeight: 1 }}
                  aria-hidden="true"
                >
                  ↓
                </div>
              )}
            </div>
          );
        })}
      </div>

      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Each row is a separate deterministic computation, not a scaling of the one
        above it. The optimiser was re-solved against the new requirement rather
        than having the previous allocation adjusted, which is why the composition
        can change shape and not merely size.
      </p>
    </Panel>
  );
}
