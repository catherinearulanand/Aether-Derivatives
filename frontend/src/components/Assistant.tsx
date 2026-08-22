"use client";

import { Chip } from "@/components/primitives";
import { api } from "@/lib/api";
import { useCurrentRun } from "@/lib/hooks";
import { useAether } from "@/lib/store";
import type {
  AssistantAnswer,
  AssistantTurn,
  Evidence as EvidenceBlock,
} from "@/lib/types";
import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * The AETHER assistant.
 *
 * .. rubric:: What it is
 *
 * An agent that guides a user through this application — where to go, what a panel
 * means, what the run in front of them says, and what to do next. The agent runs on
 * the server. This component sends a question and renders what comes back.
 *
 * .. rubric:: What it may and may not do
 *
 * The model chooses which tools to call and writes the sentences between them. It
 * never authors a figure. Every number it can reach comes from a deterministic tool
 * over the same run object these panels render, and the server re-reads the model's
 * prose before answering: a reply naming a figure no tool returned is discarded and
 * the deterministic composition is served in its place. When that happens the answer
 * is labelled, rather than silently downgraded.
 *
 * That is why the figures are rendered here as a separate block below the prose, not
 * woven into it. The evidence is the checkable part. The prose is the explanation of
 * it, and it is marked with which of the two produced it.
 */

interface Turn {
  question: string;
  answer: AssistantAnswer | null;
  failed?: string;
}

export function Assistant() {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  // The transcript is scoped to the pair of snapshots it was answered against.
  // Rather than clearing it in an effect when the scenario changes, the scope is
  // compared during render: answers about a different run are simply not this
  // conversation. Same outcome, no cascading render, and the invariant is
  // expressed as data rather than as a side effect.
  const [log, setLog] = useState<{ scope: string; turns: Turn[] }>({
    scope: "",
    turns: [],
  });
  const scrollRef = useRef<HTMLDivElement>(null);

  const role = useAether((s) => s.role);
  const currentKey = useAether((s) => s.currentKey);
  const baselineKey = useAether((s) => s.baselineKey);

  const run = useCurrentRun();

  const suggestions = useQuery({
    queryKey: ["assistant-suggestions", role],
    queryFn: () => api.assistantSuggestions(role),
    enabled: Boolean(role),
  });

  const scope = `${currentKey}|${baselineKey}`;
  // Memoised so the scroll effect below depends on a stable reference: without
  // it, an out-of-scope render produces a fresh empty array every time and the
  // effect re-runs on every keystroke.
  const turns = useMemo(
    () => (log.scope === scope ? log.turns : []),
    [log, scope],
  );

  const ask = useMutation({
    mutationFn: (question: string) => {
      // Only settled turns are context. A question still in flight has no answer
      // to send, and a failed one would teach the agent from an error.
      const history: AssistantTurn[] = turns
        .filter((turn): turn is Turn & { answer: AssistantAnswer } =>
          Boolean(turn.answer),
        )
        .flatMap((turn) => [
          { role: "user" as const, content: turn.question },
          { role: "assistant" as const, content: turn.answer.reply },
        ]);

      return api.assistantChat({
        question,
        scenario_key: currentKey,
        baseline_key: baselineKey,
        role,
        history,
      });
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns, open, ask.isPending]);

  if (!role) return null;

  function submit(question: string) {
    const trimmed = question.trim();
    if (!trimmed || ask.isPending) return;

    setDraft("");
    setLog((previous) => ({
      scope,
      turns: [
        ...(previous.scope === scope ? previous.turns : []),
        { question: trimmed, answer: null },
      ],
    }));

    ask.mutate(trimmed, {
      onSuccess: (answer) =>
        setLog((previous) => ({
          scope: previous.scope,
          turns: settle(previous.turns, trimmed, { answer }),
        })),
      onError: (error: Error) =>
        setLog((previous) => ({
          scope: previous.scope,
          turns: settle(previous.turns, trimmed, { failed: error.message }),
        })),
    });
  }

  if (!open) {
    return (
      <button
        className="assistant-launcher no-print"
        onClick={() => setOpen(true)}
        aria-label="Open the AETHER assistant"
      >
        <span className="mono" style={{ color: "var(--accent)", fontSize: 13 }}>
          ⌕
        </span>
        <span className="text-[12px]">Ask AETHER</span>
      </button>
    );
  }

  const live = suggestions.data?.mode === "live";

  return (
    <aside
      className="assistant-panel no-print"
      role="complementary"
      aria-label="AETHER assistant"
    >
      <header
        className="panel-head shrink-0"
        style={{ borderRadius: "3px 3px 0 0" }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="panel-title">Assistant</h2>
          <Chip
            tone={live ? "accent" : "default"}
            title={
              live
                ? `Agent mode. ${suggestions.data?.model_id} decides which deterministic tools to call and writes the prose. It cannot author a figure.`
                : "Replay mode. A deterministic router answers from the same tools the agent uses. No model is called."
            }
          >
            {live ? "agent" : "replay"}
          </Chip>
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Close the assistant"
          style={{ padding: "2px 8px", fontSize: 13, lineHeight: 1 }}
        >
          ✕
        </button>
      </header>

      <div className="assistant-scroll" ref={scrollRef}>
        {turns.length === 0 ? (
          <Intro
            onPick={submit}
            loading={run.isLoading}
            suggestions={suggestions.data?.suggestions ?? []}
          />
        ) : (
          <div className="flex flex-col">
            {turns.map((turn, index) => (
              <TurnView key={index} turn={turn} onPick={submit} />
            ))}
          </div>
        )}
      </div>

      <div
        className="shrink-0 p-2.5 flex gap-2"
        style={{ borderTop: "1px solid var(--rule)" }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") submit(draft);
          }}
          placeholder={
            ask.isPending ? "Working…" : "Ask about this run, or where to go…"
          }
          aria-label="Ask the AETHER assistant"
          disabled={ask.isPending}
        />
        <button
          className="primary shrink-0"
          onClick={() => submit(draft)}
          disabled={!draft.trim() || ask.isPending}
        >
          Ask
        </button>
      </div>

      <p
        className="m-0 px-3 py-2 text-[10.5px] leading-snug shrink-0"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Figures are retrieved from the run on screen by deterministic tools and are
        not recalculated here. The assistant does not compute, and any answer
        naming a figure no tool returned is discarded before it reaches you.
      </p>
    </aside>
  );
}

/** Replace the pending turn matching this question with its outcome. */
function settle(
  turns: Turn[],
  question: string,
  outcome: { answer?: AssistantAnswer; failed?: string },
): Turn[] {
  let replaced = false;
  return turns.map((turn) => {
    if (replaced || turn.answer || turn.failed || turn.question !== question) {
      return turn;
    }
    replaced = true;
    return { ...turn, answer: outcome.answer ?? null, failed: outcome.failed };
  });
}

function Intro({
  onPick,
  loading,
  suggestions,
}: {
  onPick: (question: string) => void;
  loading: boolean;
  suggestions: string[];
}) {
  return (
    <div className="px-3.5 py-3.5 flex flex-col gap-3">
      <p
        className="m-0 text-[12px] leading-relaxed"
        style={{ color: "var(--ink-mid)" }}
      >
        I can explain the run on screen, tell you what any screen of this
        application is for, and say what to do next. Every figure I give you is
        read from the run rather than recalculated, so it cannot disagree with
        what the panels show. If I do not hold something, I will say so.
      </p>

      {loading && (
        <p className="m-0 text-[11.5px]" style={{ color: "var(--ink-faint)" }}>
          The run is still loading.
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <span className="eyebrow">Try</span>
        {suggestions.map((suggestion) => (
          <button
            key={suggestion}
            onClick={() => onPick(suggestion)}
            className="text-left"
            style={{ fontSize: 11.5, padding: "6px 10px", fontWeight: 400 }}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}

function TurnView({
  turn,
  onPick,
}: {
  turn: Turn;
  onPick: (question: string) => void;
}) {
  return (
    <div style={{ borderBottom: "1px solid var(--rule)" }}>
      <div
        className="px-3.5 py-2.5 text-[12px]"
        style={{ background: "var(--surface-2)", color: "var(--ink)" }}
      >
        <span className="eyebrow block mb-1">You asked</span>
        {turn.question}
      </div>

      {turn.answer ? (
        <AnswerView answer={turn.answer} onPick={onPick} />
      ) : turn.failed ? (
        <div className="px-3.5 py-3 flex flex-col gap-2">
          <Chip tone="crit">unreachable</Chip>
          <p
            className="m-0 text-[12px] leading-relaxed"
            style={{ color: "var(--ink-mid)" }}
          >
            {turn.failed}
          </p>
        </div>
      ) : (
        <p
          className="m-0 px-3.5 py-3 text-[11.5px]"
          style={{ color: "var(--ink-faint)" }}
        >
          Reading the run…
        </p>
      )}
    </div>
  );
}

function AnswerView({
  answer,
  onPick,
}: {
  answer: AssistantAnswer;
  onPick: (question: string) => void;
}) {
  const tone =
    answer.status === "ANSWERED"
      ? "accent"
      : answer.status === "NOT_PERMITTED"
        ? "crit"
        : "warn";

  return (
    <div className="px-3.5 py-3 flex flex-col gap-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <Chip tone={tone}>
          {answer.status.replace(/_/g, " ").toLowerCase()}
        </Chip>
        {answer.route === "model" && answer.model_id && (
          <Chip title={`Composed by ${answer.model_id} from ${answer.tool_calls} tool calls, then verified against them.`}>
            agent · {answer.tool_calls} tools
          </Chip>
        )}
        {answer.guard === "FIGURE_NOT_IN_EVIDENCE" && (
          <Chip
            tone="warn"
            title="The model's reply named a figure that no tool returned. It was discarded in full and this answer was composed from the evidence instead."
          >
            model answer rejected
          </Chip>
        )}
      </div>

      <p
        className="m-0 text-[12px] leading-relaxed"
        style={{ color: "var(--ink-mid)" }}
      >
        {answer.reply}
      </p>

      {answer.evidence.map((block, index) => (
        <EvidenceView key={`${block.tool}-${index}`} block={block} />
      ))}

      {answer.actions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {answer.actions.map((action) => (
            <Link
              key={action.href}
              href={action.href}
              className="text-[11.5px]"
            >
              {action.label} →
            </Link>
          ))}
        </div>
      )}

      {answer.follow_ups.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="eyebrow">Then ask</span>
          <div className="flex flex-wrap gap-1.5">
            {answer.follow_ups.map((question) => (
              <button
                key={question}
                onClick={() => onPick(question)}
                style={{ fontSize: 11, padding: "4px 8px", fontWeight: 400 }}
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * One tool's result.
 *
 * Rendered as its own block rather than folded into the prose, because this is the
 * part a sceptic checks: the figures, the screen that displays them, and the exact
 * paths they were read from.
 */
function EvidenceView({ block }: { block: EvidenceBlock }) {
  if (block.fields.length === 0) return null;

  return (
    <div
      className="flex flex-col gap-1.5 px-2.5 py-2 rounded-sm"
      style={{ background: "var(--ground)", border: "1px solid var(--rule)" }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="eyebrow">{block.title}</span>
        <span className="mono text-[10px]" style={{ color: "var(--ink-faint)" }}>
          {block.tool}
        </span>
      </div>

      <dl className="m-0 flex flex-col gap-1.5">
        {block.fields.map((field) => (
          <div
            key={field.label}
            className="flex items-baseline justify-between gap-3"
          >
            <dt
              className="text-[11px] shrink-0"
              style={{ color: "var(--ink-mute)" }}
            >
              {field.label}
            </dt>
            <dd
              className="m-0 tnum text-right"
              style={{
                fontSize: field.headline ? 12.5 : 11,
                fontWeight: field.headline ? 700 : 400,
                color: field.headline ? "var(--accent)" : "var(--ink)",
                overflowWrap: "anywhere",
              }}
            >
              {field.value}
            </dd>
          </div>
        ))}
      </dl>

      {block.paths.length > 0 && (
        <details>
          <summary
            className="mono text-[10px] cursor-pointer"
            style={{ color: "var(--ink-faint)" }}
          >
            fields read
          </summary>
          <ul
            className="m-0 mt-1.5 pl-4 flex flex-col gap-0.5 mono text-[10px]"
            style={{ color: "var(--ink-faint)" }}
          >
            {block.paths.map((path) => (
              <li key={path}>{path}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
