"use client";

import { Chip, ErrorPanel, Loading, Panel, Stat } from "@/components/primitives";
import { api, ApiError } from "@/lib/api";
import type { ExtractedField, Extraction } from "@/lib/types";
import { RoleGuard } from "@/components/RoleGuard";
import { can } from "@/lib/roles";
import { useAether } from "@/lib/store";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

const DOCUMENT_ID = "CSA-MERIDIAN-2026";
const REVIEWER = "collateral.ops@aether.example";

/**
 * Document review.
 *
 * The split pane is the trust argument made visible: extracted values on the right,
 * the source document on the left, and clicking a field scrolls the document to the
 * exact clause the value came from.
 *
 * The freeze button is the product's central rule expressed as a control. While any
 * field awaits a reviewer it is disabled, and the API refuses the request even if it
 * were not — the gate is enforced server-side, not by the UI.
 */
export default function ReviewPage() {
  return (
    <RoleGuard permission="view:contract">
      <Review />
    </RoleGuard>
  );
}

function Review() {
  const client = useQueryClient();
  const role = useAether((s) => s.role);
  const identity = useAether((s) => s.identity);
  const mayReview = can(role, "act:review-contract");
  const [selected, setSelected] = useState<string | null>(null);
  const [frozen, setFrozen] = useState(false);
  const [rationale, setRationale] = useState(
    "Party B rated AA- (S&P) at the valuation date, above the A- downgrade trigger. The stated USD 5,000,000 Threshold applies.",
  );

  const document = useQuery({
    queryKey: ["document", DOCUMENT_ID],
    queryFn: () => api.document(DOCUMENT_ID),
  });

  const extraction = useQuery({
    queryKey: ["extraction", DOCUMENT_ID],
    queryFn: () => api.extract(DOCUMENT_ID),
  });

  const evaluation = useQuery({
    queryKey: ["evaluation", DOCUMENT_ID],
    queryFn: () => api.evaluation(DOCUMENT_ID),
  });

  const confirm = useMutation({
    mutationFn: (vars: { path: string; value?: unknown }) =>
      api.confirmField(DOCUMENT_ID, {
        path: vars.path,
        reviewer: identity ?? REVIEWER,
        rationale,
        value: vars.value,
      }),
    onSuccess: (data) => {
      client.setQueryData(["extraction", DOCUMENT_ID], data);
      setFrozen(false);
    },
  });

  const freeze = useMutation({
    mutationFn: () => api.freeze(DOCUMENT_ID),
    onSuccess: () => setFrozen(true),
  });

  return (
    <div className="p-4 max-w-[1700px] mx-auto flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="serif m-0 text-[24px] font-bold leading-tight">
            Credit Support Annex — {DOCUMENT_ID}
          </h1>
          <p className="m-0 mt-1 text-[12px]" style={{ color: "var(--ink-mute)" }}>
            Read by the Legal-Clause Agent. Every value carries a citation.
          </p>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {extraction.data && (
            <>
              <Chip title="Extraction served from a cached fixture. No network needed.">
                {extraction.data.mode}
              </Chip>
              <Chip>{extraction.data.model_id}</Chip>
              <Chip>temp {extraction.data.temperature}</Chip>
              <Chip title="Content hash of the source document.">
                sha {extraction.data.document_sha256.slice(0, 10)}…
              </Chip>
            </>
          )}
        </div>
      </div>

      {extraction.isLoading && <Loading label="Extracting clauses" />}
      {extraction.isError && <ErrorPanel error={extraction.error} />}

      {extraction.data && (
        <>
          <ExtractionSummary
            extraction={extraction.data}
            evaluationSummary={evaluation.data?.summary}
          />

          {/* The gate */}
          <FreezeGate
            extraction={extraction.data}
            mayReview={mayReview}
            reviewer={identity ?? REVIEWER}
            frozen={frozen}
            rationale={rationale}
            setRationale={setRationale}
            onConfirm={(path, value) => confirm.mutate({ path, value })}
            onFreeze={() => freeze.mutate()}
            confirming={confirm.isPending}
            freezing={freeze.isPending}
            freezeError={freeze.error}
          />

          <div className="grid xl:grid-cols-2 gap-3 items-start">
            <DocumentPane
              text={document.data?.text ?? ""}
              selectedQuote={
                extraction.data.fields.find((f) => f.path === selected)?.citation?.quote ??
                null
              }
              loading={document.isLoading}
            />
            <FieldTable
              extraction={extraction.data}
              selected={selected}
              onSelect={setSelected}
            />
          </div>
        </>
      )}
    </div>
  );
}

function ExtractionSummary({
  extraction,
  evaluationSummary,
}: {
  extraction: Extraction;
  evaluationSummary?: string;
}) {
  const cited = extraction.fields.filter((f) => f.citation).length;
  return (
    <Panel title="Extraction">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-5 px-4 py-3.5">
        <Stat label="Fields extracted" value={extraction.fields.length} />
        <Stat
          label="With citations"
          value={`${cited} / ${extraction.fields.length}`}
          hint="a value without a citation is an assertion"
          tone={cited === extraction.fields.length ? "accent" : "crit"}
        />
        <Stat
          label="Mean confidence"
          value={Number(extraction.mean_confidence).toFixed(3)}
          hint={`threshold ${extraction.confidence_threshold}`}
        />
        <Stat
          label="Awaiting review"
          value={extraction.pending_review.length}
          hint="blocks freeze until resolved"
          tone={extraction.pending_review.length ? "warn" : "accent"}
        />
        <Stat
          label="Eval vs ground truth"
          value={evaluationSummary?.split("  ")[0] ?? "…"}
          hint={evaluationSummary?.replace(/^\w+\s+/, "")}
          tone="accent"
        />
      </div>
    </Panel>
  );
}

function FreezeGate({
  extraction,
  mayReview,
  reviewer,
  frozen,
  rationale,
  setRationale,
  onConfirm,
  onFreeze,
  confirming,
  freezing,
  freezeError,
}: {
  extraction: Extraction;
  mayReview: boolean;
  reviewer: string;
  frozen: boolean;
  rationale: string;
  setRationale: (value: string) => void;
  onConfirm: (path: string, value?: unknown) => void;
  onFreeze: () => void;
  confirming: boolean;
  freezing: boolean;
  freezeError: unknown;
}) {
  const pending = extraction.pending_review;
  const ready = extraction.is_ready_to_freeze;

  return (
    <Panel
      title="Human confirmation gate"
      aside={
        <Chip tone={ready ? "accent" : "warn"}>
          {ready ? "Ready to freeze" : `${pending.length} pending`}
        </Chip>
      }
      className={pending.length ? "" : ""}
    >
      {pending.length > 0 ? (
        pending.map((item) => {
          const field = extraction.fields.find((f) => f.path === item.path);
          return (
            <div key={item.path} className="px-4 py-3.5 flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone="warn">{item.reason.replace(/_/g, " ")}</Chip>
                <span className="mono text-[12px]">{item.path}</span>
                <span className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
                  confidence {field?.confidence.toFixed(2)}
                </span>
              </div>

              <p className="m-0 text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
                {item.question}
              </p>

              <div className="text-[11.5px] mono" style={{ color: "var(--ink-faint)" }}>
                {item.citation}
              </div>

              <div>
                <label className="eyebrow block mb-1.5">Reviewer rationale</label>
                <textarea
                  rows={2}
                  value={rationale}
                  onChange={(e) => setRationale(e.target.value)}
                  placeholder="Why this value applies. Recorded permanently in the audit trail."
                />
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <button
                  className="primary"
                  disabled={!mayReview || confirming || !rationale.trim()}
                  title={
                    mayReview
                      ? undefined
                      : "Only LEGAL may confirm a contractual term."
                  }
                  onClick={() => onConfirm(item.path)}
                >
                  Confirm {item.current_value}
                </button>
                {item.alternative && (
                  <button
                    disabled={!mayReview || confirming || !rationale.trim()}
                    onClick={() =>
                      onConfirm(item.path, {
                        amount: item.alternative!.replace(/[^0-9.]/g, ""),
                        currency: item.alternative!.slice(0, 3),
                      })
                    }
                    title="Apply the conditional value instead — a Ratings Event is in effect."
                  >
                    Apply {item.alternative} instead
                  </button>
                )}
                <span className="text-[11px]" style={{ color: "var(--ink-faint)" }}>
                  {mayReview
                    ? `Recorded against ${reviewer}`
                    : "Your role may read this review but not decide it. LEGAL owns the contractual interpretation."}
                </span>
              </div>
            </div>
          );
        })
      ) : (
        <div className="px-4 py-3.5 flex flex-wrap items-center gap-4">
          <div className="text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
            Every field is resolved. Terms can be frozen into a computable agreement.
          </div>
          <button
            className="primary ml-auto"
            onClick={onFreeze}
            disabled={!mayReview || freezing || frozen}
            title={mayReview ? undefined : "Only LEGAL may freeze the agreement."}
          >
            {frozen ? "Agreement frozen" : "Freeze agreement"}
          </button>
        </div>
      )}

      {freezeError instanceof ApiError && (
        <div
          className="px-4 py-2.5 text-[12px]"
          style={{ borderTop: "1px solid var(--rule)", color: "var(--crit)" }}
        >
          {freezeError.message}
        </div>
      )}

      <p
        className="px-4 py-2.5 m-0 text-[11.5px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        The margin engine cannot read an unreviewed extraction. Freezing is refused
        server-side while any field awaits a decision — the gate is structural, not a
        disabled button.
      </p>
    </Panel>
  );
}

function DocumentPane({
  text,
  selectedQuote,
  loading,
}: {
  text: string;
  selectedQuote: string | null;
  loading: boolean;
}) {
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedQuote]);

  const content = useMemo(() => {
    if (!selectedQuote) return [{ text, highlighted: false }];

    // Match the quote against the document with whitespace normalised, because the
    // source wraps lines wherever it happens to and a quote spanning a line break is
    // still the same quote.
    const needle = normalise(selectedQuote);
    const plain = normalise(text);
    const index = plain.indexOf(needle);
    if (index === -1) return [{ text, highlighted: false }];

    return [
      { text: plain.slice(0, index), highlighted: false },
      { text: plain.slice(index, index + needle.length), highlighted: true },
      { text: plain.slice(index + needle.length), highlighted: false },
    ];
  }, [text, selectedQuote]);

  return (
    <Panel
      title="Source document"
      aside={
        <Chip tone={selectedQuote ? "accent" : "default"}>
          {selectedQuote ? "Clause highlighted" : "Select a field"}
        </Chip>
      }
    >
      {loading ? (
        <Loading label="Loading document" />
      ) : (
        <div
          className="overflow-y-auto px-4 py-3 text-[12px] leading-relaxed whitespace-pre-wrap"
          style={{ maxHeight: 620, color: "var(--ink-mid)", fontFamily: "var(--mono)" }}
        >
          {content.map((chunk, i) =>
            chunk.highlighted ? (
              <mark
                key={i}
                ref={markRef as React.Ref<HTMLElement>}
                style={{
                  background: "var(--accent-wash)",
                  color: "var(--accent)",
                  padding: "1px 2px",
                  borderRadius: 2,
                  boxShadow: "0 0 0 1px var(--accent-dim)",
                }}
              >
                {chunk.text}
              </mark>
            ) : (
              <span key={i}>{chunk.text}</span>
            ),
          )}
        </div>
      )}
    </Panel>
  );
}

function normalise(value: string): string {
  return value.replace(/\*\*/g, "").replace(/\s+/g, " ").trim();
}

function FieldTable({
  extraction,
  selected,
  onSelect,
}: {
  extraction: Extraction;
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <Panel
      title="Extracted terms"
      aside={<Chip>{extraction.fields.length} fields</Chip>}
    >
      <div className="overflow-y-auto" style={{ maxHeight: 620 }}>
        <table className="grid">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Value</th>
              <th scope="col" className="num">Conf.</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {extraction.fields.map((field) => (
              <tr
                key={field.path}
                onClick={() => onSelect(field.path)}
                style={{
                  cursor: "pointer",
                  background:
                    selected === field.path ? "var(--surface-3)" : undefined,
                }}
                title="Click to highlight the source clause"
              >
                <td>
                  <div className="mono text-[11px]">{field.path}</div>
                  {field.citation && (
                    <div
                      className="text-[10px]"
                      style={{
                        // The selected row sits on a lighter surface, where the
                        // faintest tone drops under 4.5:1. Selection raises the
                        // citation with it.
                        color:
                          selected === field.path
                            ? "var(--ink-mute)"
                            : "var(--ink-faint)",
                      }}
                    >
                      p.{field.citation.page} · {field.citation.section}
                    </div>
                  )}
                </td>
                <td className="text-[11.5px]" style={{ maxWidth: 220 }}>
                  <ValueCell field={field} />
                </td>
                <td
                  className="num"
                  style={{
                    color:
                      field.confidence < extraction.confidence_threshold
                        ? "var(--warn)"
                        : "var(--ink-mute)",
                  }}
                >
                  {field.confidence.toFixed(2)}
                </td>
                <td>
                  {field.source === "HUMAN" ? (
                    <Chip tone="accent" title={field.reviewer_rationale}>
                      human
                    </Chip>
                  ) : field.requires_review ? (
                    <Chip tone="warn">review</Chip>
                  ) : (
                    <Chip>agent</Chip>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function ValueCell({ field }: { field: ExtractedField }) {
  const value = field.value;

  if (value && typeof value === "object" && "amount" in value) {
    const money = value as { amount: string; currency: string };
    return (
      <span className="tnum">
        {money.currency} {Number(money.amount).toLocaleString("en-US", {
          minimumFractionDigits: 2,
        })}
      </span>
    );
  }

  if (Array.isArray(value)) {
    return (
      <span style={{ color: "var(--ink-mute)" }}>
        {value.length} item{value.length === 1 ? "" : "s"}
      </span>
    );
  }

  return <span className="mono">{String(value)}</span>;
}
