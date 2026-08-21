"use client";

import { Chip } from "@/components/primitives";
import { SUGGESTIONS, ask, type Answer } from "@/lib/assistant";
import { useComparison, useCurrentRun, useScenarios } from "@/lib/hooks";
import { useAether } from "@/lib/store";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

/**
 * The AETHER assistant.
 *
 * .. rubric:: What it does
 *
 * Answers questions about the run currently on screen by **retrieving** values
 * from it. Every answer names the panel that displays the same figures and lists
 * the field paths it read, so the claim "this agrees with the dashboard" is
 * checkable rather than asserted.
 *
 * .. rubric:: What it is not
 *
 * Not a language model, and not a chatbot. This component makes no model call, and
 * the retrieval layer performs no arithmetic on money. Those are the two things
 * that would make it dangerous here: a model could produce a figure that disagrees
 * with the margin engine, and arithmetic in the browser could produce one that is
 * merely wrong. Where a question asks what changed, the deltas come from the
 * comparison endpoint, computed in Python with `Decimal`.
 *
 * When nothing matches, it says so. That is the correct answer, and inventing a
 * confident paragraph instead would be the single most damaging thing this
 * component could do.
 */

interface Turn {
  question: string;
  answer: Answer;
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
  const comparison = useComparison();
  const scenarios = useScenarios();

  const nameOf = (key: string) =>
    scenarios.data?.find((s) => s.key === key)?.name ?? key;

  const scope = `${currentKey}|${baselineKey}`;
  // Memoised so the scroll effect below depends on a stable reference: without
  // it, an out-of-scope render produces a fresh empty array every time and the
  // effect re-runs on every keystroke.
  const turns = useMemo(
    () => (log.scope === scope ? log.turns : []),
    [log, scope],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns, open]);

  if (!role) return null;

  function submit(question: string) {
    const trimmed = question.trim();
    if (!trimmed) return;

    const answer = ask(trimmed, {
      run: run.data ?? null,
      comparison: comparison.data ?? null,
      role,
      scenarioName: nameOf(currentKey),
      baselineName: nameOf(baselineKey),
    });

    setLog((previous) => ({
      scope,
      turns: [
        ...(previous.scope === scope ? previous.turns : []),
        { question: trimmed, answer },
      ],
    }));
    setDraft("");
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
          <Chip title="This assistant retrieves values from the run on screen. It makes no model call and computes nothing.">
            retrieval
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
            scenarioName={nameOf(currentKey)}
            onPick={submit}
            loading={run.isLoading}
          />
        ) : (
          <div className="flex flex-col">
            {turns.map((turn, index) => (
              <TurnView key={index} turn={turn} />
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
          placeholder="Ask about this run…"
          aria-label="Ask the AETHER assistant"
        />
        <button
          className="primary shrink-0"
          onClick={() => submit(draft)}
          disabled={!draft.trim()}
        >
          Ask
        </button>
      </div>

      <p
        className="m-0 px-3 py-2 text-[10.5px] leading-snug shrink-0"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Retrieval only. Values are read from the run on screen and are not
        recalculated here. No model is called.
      </p>
    </aside>
  );
}

function Intro({
  scenarioName,
  onPick,
  loading,
}: {
  scenarioName: string;
  onPick: (question: string) => void;
  loading: boolean;
}) {
  return (
    <div className="px-3.5 py-3.5 flex flex-col gap-3">
      <p className="m-0 text-[12px] leading-relaxed" style={{ color: "var(--ink-mid)" }}>
        I answer from the run on screen —{" "}
        <strong style={{ color: "var(--ink)" }}>{scenarioName}</strong>. Every figure
        I give you is read from that run, not recalculated, so it cannot disagree
        with what the panels show. If I do not hold something, I will say so.
      </p>

      {loading && (
        <p className="m-0 text-[11.5px]" style={{ color: "var(--ink-faint)" }}>
          The run is still loading.
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <span className="eyebrow">Try</span>
        {SUGGESTIONS.map((suggestion) => (
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

function TurnView({ turn }: { turn: Turn }) {
  const { answer } = turn;
  const tone =
    answer.status === "ANSWERED"
      ? "accent"
      : answer.status === "NOT_PERMITTED"
        ? "crit"
        : "warn";

  return (
    <div style={{ borderBottom: "1px solid var(--rule)" }}>
      <div
        className="px-3.5 py-2.5 text-[12px]"
        style={{ background: "var(--surface-2)", color: "var(--ink)" }}
      >
        <span className="eyebrow block mb-1">You asked</span>
        {turn.question}
      </div>

      <div className="px-3.5 py-3 flex flex-col gap-2.5">
        <div className="flex items-center gap-2">
          <Chip tone={tone}>{answer.status.replace(/_/g, " ").toLowerCase()}</Chip>
          {answer.status === "ANSWERED" && (
            <span className="text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
              from {answer.source}
            </span>
          )}
        </div>

        <p
          className="m-0 text-[12px] leading-relaxed"
          style={{ color: "var(--ink-mid)" }}
        >
          {answer.text}
        </p>

        {answer.fields.length > 0 && (
          <dl
            className="m-0 flex flex-col gap-1.5 px-2.5 py-2 rounded-sm"
            style={{ background: "var(--ground)", border: "1px solid var(--rule)" }}
          >
            {answer.fields.map((field) => (
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
        )}

        {answer.href && (
          <Link href={answer.href} className="text-[11.5px]">
            Open {answer.source} →
          </Link>
        )}

        {answer.paths.length > 0 && (
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
              {answer.paths.map((path) => (
                <li key={path}>{path}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
