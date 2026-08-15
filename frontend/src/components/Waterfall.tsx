"use client";

import { formatMoney } from "@/lib/format";
import type { MarginCall } from "@/lib/types";
import { useState } from "react";
import { Chip, Panel } from "./primitives";

/**
 * The margin waterfall.
 *
 * A bridge from net exposure through Threshold, Independent Amount, the MTA gate and
 * rounding to the final transfer. Every row names the clause it comes from, because
 * "where did this number come from" is the question a collateral manager actually
 * asks, and the answer is a paragraph reference rather than a hand-wave.
 */

/** Bar magnitude relative to the largest absolute figure in the trace. */
function useScale(steps: MarginCall["waterfall"]) {
  const magnitudes = steps.map((s) => Math.abs(Number(s.value.amount)));
  const max = Math.max(...magnitudes, 1);
  return (amount: string) => Math.min(100, (Math.abs(Number(amount)) / max) * 100);
}

export function Waterfall({ call }: { call: MarginCall }) {
  const [open, setOpen] = useState<number | null>(null);
  const scale = useScale(call.waterfall);

  return (
    <Panel
      title="Margin waterfall"
      aside={
        <div className="flex items-center gap-2">
          <Chip title="The convention this agreement elects, recorded on every result.">
            {call.mta_before_rounding ? "MTA before rounding" : "Rounding before MTA"}
          </Chip>
          <Chip tone={call.has_call ? "accent" : "default"}>
            {call.direction === "NONE" ? "No transfer" : call.direction}
          </Chip>
        </div>
      }
    >
      <div className="divide-y" style={{ borderColor: "var(--rule-soft)" }}>
        {call.waterfall.map((step, index) => {
          const negative = step.value.amount.startsWith("-");
          const isFinal = index === call.waterfall.length - 1;
          const expanded = open === index;

          return (
            <div key={`${step.label}-${index}`}>
              <button
                onClick={() => setOpen(expanded ? null : index)}
                className="w-full text-left px-4 py-2.5 flex items-center gap-3"
                style={{
                  background: expanded
                    ? "var(--surface-2)"
                    : isFinal
                      ? "var(--accent-wash)"
                      : "transparent",
                  border: 0,
                  borderRadius: 0,
                }}
                aria-expanded={expanded}
              >
                <span
                  className="mono text-[9.5px] w-5 shrink-0"
                  style={{ color: "var(--ink-faint)" }}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>

                <span
                  className="text-[12.5px] shrink-0"
                  style={{
                    width: 210,
                    color: isFinal ? "var(--ink)" : "var(--ink-mid)",
                    fontWeight: isFinal || step.is_gate ? 600 : 400,
                  }}
                >
                  {step.label}
                  {step.is_gate && (
                    <span
                      className="mono ml-2 text-[9px]"
                      style={{ color: "var(--warn)" }}
                    >
                      GATE
                    </span>
                  )}
                </span>

                {/* Magnitude bar — relative, not to scale with anything external. */}
                <span className="flex-1 h-[3px] rounded-sm overflow-hidden hidden md:block"
                  style={{ background: "var(--surface-3)" }}>
                  <span
                    className="block h-full"
                    style={{
                      width: `${scale(step.value.amount)}%`,
                      background: negative
                        ? "var(--neg)"
                        : isFinal
                          ? "var(--accent)"
                          : "var(--accent-dim)",
                    }}
                  />
                </span>

                <span
                  className="tnum text-[13px] shrink-0 text-right"
                  style={{
                    width: 175,
                    color: negative ? "var(--neg)" : "var(--ink)",
                    fontWeight: isFinal ? 700 : 400,
                  }}
                >
                  {formatMoney(step.value)}
                </span>

                <span
                  className="mono text-[10px] shrink-0 text-right hidden lg:block"
                  style={{ width: 130, color: "var(--ink-faint)" }}
                >
                  {step.clause}
                </span>
              </button>

              {expanded && (
                <div
                  className="px-4 pb-3 pl-12 text-[12px] leading-relaxed"
                  style={{ background: "var(--surface-2)", color: "var(--ink-mid)" }}
                >
                  {step.explanation}
                  <div className="mono text-[10px] mt-1.5" style={{ color: "var(--ink-faint)" }}>
                    Source: CSA {step.clause}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div
        className="px-4 py-2.5 text-[11.5px] flex flex-wrap gap-x-5 gap-y-1"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        <span>
          engine <span className="mono">{call.engine_version}</span>
        </span>
        <span>
          snapshot <span className="mono">{call.snapshot_id}</span>
        </span>
        <span>
          as of <span className="mono">{call.as_of}</span>
        </span>
        <span>
          netting set <span className="mono">{call.netting_set_id}</span>
        </span>
      </div>
    </Panel>
  );
}
