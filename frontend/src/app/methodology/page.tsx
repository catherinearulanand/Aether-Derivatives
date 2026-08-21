"use client";

import { Chip, ErrorPanel, Loading, Panel, Stat } from "@/components/primitives";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

/**
 * Methodology and evaluation.
 *
 * This page exists to be read by a sceptic. It states what is modelled, what is not,
 * and what may never be claimed — and it serves that content from the API so the UI
 * cannot drift away from what the engine actually does.
 *
 * Precision about limits is more persuasive to an informed audience than breadth of
 * claims, and one checkable overclaim loses a technical judge for good.
 */
export default function MethodologyPage() {
  const methodology = useQuery({
    queryKey: ["methodology"],
    queryFn: api.methodology,
  });
  const evaluation = useQuery({
    queryKey: ["evaluation", "CSA-MERIDIAN-2026"],
    queryFn: () => api.evaluation("CSA-MERIDIAN-2026"),
  });

  return (
    <div className="p-4 max-w-[1200px] mx-auto flex flex-col gap-3">
      <div>
        <h1 className="serif m-0 text-[24px] font-bold leading-tight">Methodology</h1>
        <p className="m-0 mt-1 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
          What this system models, what it deliberately does not, and what it will never claim.
        </p>
      </div>

      {methodology.isLoading && <Loading label="Loading" />}
      {methodology.isError && <ErrorPanel error={methodology.error} />}

      {methodology.data && (
        <>
          <section className="panel panel-accent px-5 py-4">
            <p
              className="serif m-0 text-[21px] leading-snug font-bold"
              style={{ color: "var(--ink)" }}
            >
              {methodology.data.principle}
            </p>
            <p className="mt-2.5 mb-0 text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
              Every contractual value crosses from the model side to the engine side
              exactly once — through a typed schema, carrying a citation, past a human
              confirmation when confidence is low. No model-generated number becomes an
              authoritative financial result.
            </p>
          </section>

          {evaluation.data && (
            <Panel
              title="Extraction harness score — not a measure of model accuracy"
              aside={
                <div className="flex items-center gap-2">
                  <Chip
                    tone="warn"
                    title="In replay mode the cached extraction is itself hand-authored, so this compares hand-authored output against hand-authored ground truth."
                  >
                    Hand-authored cache
                  </Chip>
                  <Chip tone={evaluation.data.passes ? "accent" : "crit"}>
                    {evaluation.data.passes ? "Passes targets" : "Below target"}
                  </Chip>
                </div>
              }
            >
              <div className="grid grid-cols-2 md:grid-cols-4 gap-5 px-4 py-3.5">
                <Stat
                  label="Value accuracy"
                  value={pct(evaluation.data.value_accuracy)}
                  hint="target ≥ 90%"
                  tone="accent"
                />
                <Stat
                  label="Citation accuracy"
                  value={pct(evaluation.data.citation_accuracy)}
                  hint="target ≥ 80%"
                  tone="accent"
                />
                <Stat
                  label="Review-flag recall"
                  value={pct(evaluation.data.review_flag_recall)}
                  hint="target 100% — missing one is the worst failure"
                  tone="accent"
                />
                <Stat
                  label="Fields scored"
                  value={evaluation.data.scored_fields}
                  hint={`${evaluation.data.mode} — cached extraction is hand-authored`}
                />
              </div>
              <p
                className="px-4 py-2.5 m-0 text-[11.5px]"
                style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
              >
                Scored against hand-authored ground truth. A missed review flag is
                weighted three times, because computing confidently on an unconfirmed
                value is worse than an obvious error — nothing downstream questions it.
                Note: in replay mode the cached extraction is itself hand-authored, so
                this score demonstrates the harness rather than model accuracy.
              </p>
            </Panel>
          )}

          <div className="grid lg:grid-cols-2 gap-3 items-start">
            <Panel
              title="Modelled"
              aside={<Chip tone="accent">{methodology.data.modelled.length}</Chip>}
            >
              <ul className="m-0 px-5 py-3.5 flex flex-col gap-2 text-[12.5px]">
                {methodology.data.modelled.map((item) => (
                  <li key={item} style={{ color: "var(--ink-mid)" }}>
                    {item}
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel
              title="Deliberately not modelled"
              aside={<Chip tone="warn">{methodology.data.not_modelled.length}</Chip>}
            >
              <ul className="m-0 px-5 py-3.5 flex flex-col gap-2 text-[12.5px]">
                {methodology.data.not_modelled.map((item) => (
                  <li key={item} style={{ color: "var(--ink-mid)" }}>
                    {item}
                  </li>
                ))}
              </ul>
            </Panel>
          </div>

          <Panel
            title="Claims this system does not make"
            aside={<Chip tone="crit">Read before asking</Chip>}
          >
            <table className="grid">
              <thead>
                <tr>
                  <th scope="col" style={{ width: 220 }}>Not claimed</th>
                  <th scope="col">What is true instead</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(methodology.data.never_claimed).map(([claim, truth]) => (
                  <tr key={claim}>
                    <td>
                      <span style={{ color: "var(--crit)", textDecoration: "line-through" }}>
                        {claim}
                      </span>
                    </td>
                    <td style={{ color: "var(--ink-mid)" }}>{truth}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Data provenance">
            <div className="px-4 py-3.5 text-[12.5px]" style={{ color: "var(--ink-mid)" }}>
              <p className="mt-0">
                Every fixture in this system carries a provenance block declaring itself
                simulated, and the loader refuses to read one that does not. Market
                curves, FX rates, counterparties, the derivatives book, the collateral
                inventory and the Credit Support Annex are all synthetic and were
                authored for this prototype.
              </p>
              <p className="mb-0">
                Market data is <strong>pinned snapshots</strong> rather than a live feed.
                That is a design choice in service of reproducibility: the same inputs
                produce the same audit hash on any machine, which is what makes the
                determinism test meaningful.
              </p>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

function pct(value: string): string {
  return `${(Number(value) * 100).toFixed(1)}%`;
}
