"use client";

import { Chip } from "@/components/primitives";
import {
  STAGE_STATE_LABELS,
  stageTone,
  type StageId,
  type Workflow,
  type WorkflowStage,
} from "@/lib/workflow";

/**
 * The process tracker.
 *
 * Nine stages, each showing where this run actually got to. The answer to "where
 * am I in the process?" should not require reading a paragraph, so the state
 * reaches the eye through a stripe down the leading edge, and the words underneath
 * say the same thing for anyone the colour does not reach.
 *
 * Every state is derived in `lib/workflow.ts` from the run the engine returned. A
 * stage cannot show complete unless the thing it describes happened.
 */
export function ProcessTracker({
  workflow,
  selected,
  onSelect,
  compact = false,
}: {
  workflow: Workflow;
  selected?: StageId | null;
  onSelect?: (id: StageId) => void;
  compact?: boolean;
}) {
  return (
    <div className="tracker" role="list" aria-label="AETHER workflow progress">
      {workflow.stages.map((stage) => {
        const isSelected = selected === stage.id;
        const isActive = workflow.activeStage === stage.id;

        return (
          <button
            key={stage.id}
            role="listitem"
            className="tracker-step"
            data-state={stage.state}
            aria-current={isActive ? "step" : isSelected ? "true" : undefined}
            onClick={() => onSelect?.(stage.id)}
            disabled={!onSelect}
            title={`${STAGE_STATE_LABELS[stage.state]} — ${stage.outcome}`}
            style={
              isSelected && !isActive ? { background: "var(--surface-3)" } : undefined
            }
          >
            <span className="tracker-index">
              {String(stage.index + 1).padStart(2, "0")}
            </span>
            <span className="tracker-title">{stage.title}</span>
            {!compact && (
              <span
                className="mono text-[9px] mt-1 block"
                style={{
                  color:
                    stage.state === "COMPLETE"
                      ? "var(--ok)"
                      : stage.state === "ACTIVE"
                        ? "var(--accent)"
                        : stage.state === "REQUIRES_REVIEW" || stage.state === "WARNING"
                          ? "var(--warn)"
                          : stage.state === "BLOCKED"
                            ? "var(--crit)"
                            : "var(--ink-faint)",
                  letterSpacing: "0.1em",
                }}
              >
                {STAGE_STATE_LABELS[stage.state].toUpperCase()}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** The tracker's own key. Six states, each meaning one thing. */
export function TrackerLegend() {
  const entries: [string, string, string][] = [
    ["var(--ok)", "Complete", "The stage ran and produced its output."],
    ["var(--accent)", "Active", "Where the run is now."],
    ["var(--warn)", "Requires review / warning", "A human decision is outstanding, or the stage completed with a caveat."],
    ["var(--crit)", "Blocked", "The stage could not complete."],
    ["var(--rule)", "Not required", "This run did not need the stage — no Delivery Amount was due."],
  ];

  return (
    <div
      className="flex flex-wrap items-center gap-x-5 gap-y-1.5 px-4 py-2 text-[11px]"
      style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
    >
      <span className="eyebrow">States</span>
      {entries.map(([colour, label, hint]) => (
        <span key={label} className="flex items-center gap-1.5" title={hint}>
          <span
            style={{
              width: 3,
              height: 11,
              background: colour,
              display: "inline-block",
              borderRadius: 1,
            }}
          />
          {label}
        </span>
      ))}
    </div>
  );
}

/**
 * One stage, opened.
 *
 * Inputs on the left, outputs on the right, with the clause or method that links
 * them underneath. "Where did this number come from" is the question this panel
 * exists to answer, and it answers it with the stage's own recorded values rather
 * than a description of what the stage generally does.
 */
export function StageDetail({ stage }: { stage: WorkflowStage }) {
  const tone = stageTone(stage.state);

  return (
    <div className="px-4 py-4 flex flex-col gap-4" style={{ background: "var(--surface-2)" }}>
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <p
            className="m-0 text-[12.5px] leading-relaxed max-w-[80ch]"
            style={{ color: "var(--ink-mid)" }}
          >
            {stage.purpose}
          </p>
          <p
            className="mt-2 mb-0 text-[12.5px] leading-relaxed max-w-[80ch]"
            style={{ color: "var(--ink)" }}
          >
            {stage.outcome}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <Chip tone={tone}>{STAGE_STATE_LABELS[stage.state]}</Chip>
          <span className="eyebrow">{stage.owner}</span>
          {stage.occurredAt && (
            <span className="mono text-[10px]" style={{ color: "var(--ink-faint)" }}>
              {stage.occurredAt}
            </span>
          )}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-px" style={{ background: "var(--rule)" }}>
        <FactColumn title="Received" facts={stage.inputs} />
        <FactColumn title="Produced" facts={stage.outputs} />
      </div>

      <p
        className="m-0 text-[11px] pt-1"
        style={{ color: "var(--ink-faint)", borderTop: "1px solid var(--rule)" }}
      >
        <span className="eyebrow">Basis</span>{" "}
        <span className="ml-2">{stage.basis}</span>
      </p>
    </div>
  );
}

function FactColumn({
  title,
  facts,
}: {
  title: string;
  facts: WorkflowStage["inputs"];
}) {
  return (
    <div className="px-3.5 py-3" style={{ background: "var(--surface)" }}>
      <div className="eyebrow mb-2.5">{title}</div>
      {facts.length === 0 ? (
        <p className="m-0 text-[11.5px]" style={{ color: "var(--ink-faint)" }}>
          Nothing was produced at this stage in this run.
        </p>
      ) : (
        <dl className="m-0 flex flex-col gap-2">
          {facts.map((fact) => (
            <div key={fact.label} className="flex items-baseline justify-between gap-4">
              <dt className="text-[11.5px] shrink-0" style={{ color: "var(--ink-mute)" }}>
                {fact.label}
              </dt>
              <dd
                className="m-0 tnum text-right"
                style={{
                  fontSize: fact.headline ? 13 : 11.5,
                  fontWeight: fact.headline ? 700 : 400,
                  color: fact.headline ? "var(--accent)" : "var(--ink)",
                  overflowWrap: "anywhere",
                }}
              >
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
