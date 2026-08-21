"use client";

import { CrossBorder } from "@/components/CrossBorder";
import { Optimizer } from "@/components/Optimizer";
import { Settlement } from "@/components/Settlement";
import { Chip, ErrorPanel, Panel, Skeleton } from "@/components/primitives";
import { useCurrentRun } from "@/lib/hooks";
import type { RunResult } from "@/lib/types";
import Link from "next/link";

/**
 * Collateral optimisation.
 *
 * The chain from "what may be posted" to "what was posted and why", in the order
 * the engine works it: the eligibility schedule and its caps first, then the
 * linear program, then the cross-border economics, then the instruction the
 * allocation produces.
 *
 * Eligibility leads because it is the constraint set the optimiser solves inside.
 * Showing the answer before showing what the answer was allowed to be is how an
 * optimiser ends up looking like a black box.
 */
export default function OptimisationPage() {
  const run = useCurrentRun();

  if (run.isError) {
    return (
      <div className="p-4 max-w-[1600px] mx-auto">
        <ErrorPanel error={run.error} />
      </div>
    );
  }

  return (
    <div className="p-4 max-w-[1600px] mx-auto flex flex-col gap-3">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <h1 className="serif m-0 text-[25px] font-bold leading-tight">
            Collateral optimisation
          </h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "84ch" }}
          >
            What the Annex permits, what the caps allow, and what the linear
            program chose inside those limits — ranked by cost per unit of
            collateral actually delivered rather than by headline funding spread.
          </p>
        </div>
        {run.data && (
          <div className="ml-auto flex items-center gap-2">
            <Chip>{run.data.snapshot.snapshot_id}</Chip>
            {run.data.allocation && (
              <Chip
                tone={run.data.allocation.status === "OPTIMAL" ? "accent" : "crit"}
              >
                {run.data.allocation.status}
              </Chip>
            )}
          </div>
        )}
      </header>

      {run.isLoading || !run.data ? (
        <Panel title="Collateral optimisation">
          <Skeleton rows={6} />
        </Panel>
      ) : (
        <>
          <Eligibility run={run.data} />
          <Optimizer allocation={run.data.allocation} />
          <CrossBorder allocation={run.data.allocation} />
          <Settlement settlement={run.data.settlement} />

          <p className="m-0 text-[11.5px]" style={{ color: "var(--ink-faint)" }}>
            The message formats and what they are for are set out on the{" "}
            <Link href="/settlement">settlement screen</Link>. Nothing generated
            here is transmitted anywhere.
          </p>
        </>
      )}
    </div>
  );
}

/**
 * Eligibility and constraints.
 *
 * The schedule the Annex sets out, the caps that apply on top of it, and the
 * assets excluded outright with the clause that excludes them. This is the
 * feasible region; everything after it is a choice made inside it.
 */
function Eligibility({ run }: { run: RunResult }) {
  const { agreement, allocation } = run;

  return (
    <div className="grid xl:grid-cols-[minmax(0,1fr)_minmax(0,460px)] gap-3 items-start">
      <Panel
        title="Eligible credit support — the schedule"
        aside={<Chip>{agreement.eligible_collateral.length} items</Chip>}
      >
        <div className="overflow-x-auto">
          <table className="grid">
            <thead>
              <tr>
                <th scope="col" style={{ width: 40 }}>
                  Ref
                </th>
                <th scope="col">Asset class</th>
                <th scope="col">Issuer</th>
                <th scope="col">Currency</th>
                <th scope="col">Maturity</th>
                <th scope="col">Rating</th>
                <th scope="col" className="num">
                  Valuation
                </th>
              </tr>
            </thead>
            <tbody>
              {agreement.eligible_collateral.map((item) => (
                <tr key={item.ref}>
                  <td className="mono text-[11px]" style={{ color: "var(--accent)" }}>
                    {item.ref}
                  </td>
                  <td className="text-[11.5px]">
                    {item.asset_class.replace(/_/g, " ").toLowerCase()}
                  </td>
                  <td className="text-[11.5px]" style={{ color: "var(--ink-mute)" }}>
                    {item.issuer ?? item.issuer_type.replace(/_/g, " ").toLowerCase()}
                  </td>
                  <td className="mono text-[11px]">
                    {item.non_base_currency_only
                      ? "non-base"
                      : (item.currency ?? "any")}
                  </td>
                  <td className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
                    {maturityBand(item.min_maturity_years, item.max_maturity_years)}
                  </td>
                  <td className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
                    {item.min_rating ?? "—"}
                  </td>
                  <td className="num font-semibold">
                    {(Number(item.valuation_percentage) * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p
          className="px-4 py-2.5 m-0 text-[11.5px]"
          style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
        >
          Valuation percentage is the proportion of an asset&apos;s market value that
          counts as credit support. A non-base-currency asset carries an additional{" "}
          {(Number(agreement.fx_haircut_pct) * 100).toFixed(1)}% FX haircut on top.
        </p>
      </Panel>

      <div className="flex flex-col gap-3">
        <Panel
          title="Concentration limits"
          aside={<Chip tone="warn">{agreement.concentration_limits.length}</Chip>}
        >
          <table className="grid">
            <thead>
              <tr>
                <th scope="col">Scope</th>
                <th scope="col" className="num">
                  Cap
                </th>
                <th scope="col" className="num">
                  Binds?
                </th>
              </tr>
            </thead>
            <tbody>
              {agreement.concentration_limits.map((limit) => {
                const shadow = allocation?.shadow_prices.find((price) =>
                  price.name.endsWith(limit.scope),
                );
                return (
                  <tr key={limit.scope}>
                    <td className="text-[11.5px]">
                      {limit.scope.replace(/_/g, " ").toLowerCase()}
                    </td>
                    <td className="num">
                      {(Number(limit.limit_percentage) * 100).toFixed(0)}%
                    </td>
                    <td className="num">
                      {shadow ? (
                        shadow.binding ? (
                          <Chip tone="warn">binds</Chip>
                        ) : (
                          <span style={{ color: "var(--ink-faint)" }}>slack</span>
                        )
                      ) : (
                        <span style={{ color: "var(--ink-faint)" }}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p
            className="px-4 py-2.5 m-0 text-[11.5px]"
            style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
          >
            Caps are proportions of the Credit Support Balance. A cap that binds is
            actively shaping the allocation, and its shadow price says what relaxing
            it by a unit would save.
          </p>
        </Panel>

        <Panel
          title="Excluded from the eligible set"
          aside={
            <Chip tone={allocation?.excluded.length ? "crit" : "default"}>
              {allocation?.excluded.length ?? 0}
            </Chip>
          }
        >
          {allocation && allocation.excluded.length > 0 ? (
            <div className="px-4 py-3 flex flex-col gap-2.5">
              {allocation.excluded.map((item) => (
                <div key={item.asset_id} className="text-[12px]">
                  <span className="mono" style={{ color: "var(--crit)" }}>
                    {item.asset_id}
                  </span>
                  <div className="leading-snug" style={{ color: "var(--ink-mid)" }}>
                    {item.reason}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p
              className="px-4 py-5 m-0 text-[12px]"
              style={{ color: "var(--ink-mute)" }}
            >
              {allocation
                ? "Nothing in the inventory was excluded from the eligible set."
                : "No allocation ran at this snapshot."}
            </p>
          )}
          <p
            className="px-4 py-2.5 m-0 text-[11.5px]"
            style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
          >
            Wrong-way exclusions apply before optimisation, not as a penalty inside
            it. Collateral issued by the counterparty is worth least exactly when it
            is needed most, so it is removed from the problem rather than priced
            within it.
          </p>
        </Panel>
      </div>
    </div>
  );
}

function maturityBand(min: string | null, max: string | null): string {
  if (!min && !max) return "any";
  if (min && max) return `${Number(min)}–${Number(max)}y`;
  if (max) return `≤ ${Number(max)}y`;
  return `≥ ${Number(min)}y`;
}
