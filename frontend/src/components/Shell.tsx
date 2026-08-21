"use client";

import { Chip } from "@/components/primitives";
import { useHealth, useScenarios } from "@/lib/hooks";
import { ROLE_PROFILES, can, type Permission } from "@/lib/roles";
import { useAether } from "@/lib/store";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Navigation, ordered by the workflow rather than by feature.
 *
 * A collateral call moves left to right along this bar: the desk view, the impact
 * of the market event, the contract behind it, the numbers, the allocation, the
 * analysis, the reconciliation and finally the record. A user who walks the nav in
 * order has walked the pipeline.
 *
 * Each entry declares the permission it needs, so the bar shows a role what it can
 * reach rather than showing everyone everything and refusing on arrival.
 */
const NAV: {
  href: string;
  label: string;
  hint: string;
  permission: Permission;
}[] = [
  {
    href: "/",
    label: "Dashboard",
    hint: "What happened, what changed, what to post and why",
    permission: "view:desk",
  },
  {
    href: "/workflow",
    label: "Workflow & Impact",
    hint: "Every stage, opened: input, output and the change it caused",
    permission: "view:desk",
  },
  {
    href: "/review",
    label: "Contracts",
    hint: "CSA extraction, citations and the approval gate",
    permission: "view:contract",
  },
  {
    href: "/exposure",
    label: "Exposure & Margin",
    hint: "Mark-to-market, the margin waterfall, initial margin",
    permission: "view:desk",
  },
  {
    href: "/optimisation",
    label: "Optimisation",
    hint: "Eligibility, the linear program, the settlement instruction",
    permission: "view:desk",
  },
  {
    href: "/analytics",
    label: "Analytics",
    hint: "Concentration, cost and the market event's effect",
    permission: "view:desk",
  },
  {
    href: "/reconciliation",
    label: "Reconciliation",
    hint: "Internal ledger against the custodian statement",
    permission: "act:reconcile",
  },
  {
    href: "/audit",
    label: "Audit Trail",
    hint: "Hash chain, agent to engine to human, exportable",
    permission: "view:audit",
  },
  {
    href: "/admin",
    label: "Admin",
    hint: "Workflow status board and system state",
    permission: "view:admin",
  },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const role = useAether((s) => s.role);
  const identity = useAether((s) => s.identity);
  const signOut = useAether((s) => s.signOut);
  const { data: health } = useHealth();

  const visible = NAV.filter((item) => can(role, item.permission));

  return (
    <div className="min-h-screen flex flex-col">
      <header
        className="shrink-0 no-print"
        style={{ borderBottom: "1px solid var(--rule)", background: "var(--surface)" }}
      >
        <div className="flex items-center gap-5 px-5 h-11">
          <Link href="/" className="flex items-baseline gap-2.5 no-underline shrink-0">
            <span
              className="mono font-bold"
              style={{ color: "var(--accent)", letterSpacing: "0.24em", fontSize: 14 }}
            >
              AETHER
            </span>
            <span className="eyebrow hidden xl:inline">
              Margin &amp; Collateral Intelligence
            </span>
          </Link>

          <div className="ml-auto flex items-center gap-2.5">
            <Chip tone="warn" title="Every figure in this system is simulated.">
              Simulated data
            </Chip>
            {health && (
              <>
                <Chip
                  title={
                    health.mode === "replay"
                      ? "Extraction served from a cached fixture. No network required."
                      : "Extraction calls the model live."
                  }
                >
                  {health.mode}
                </Chip>
                <Chip title="Engine version, recorded on every result.">
                  v{health.engine_version}
                </Chip>
              </>
            )}

            {role && (
              <div
                className="flex items-center gap-2 pl-2.5"
                style={{ borderLeft: "1px solid var(--rule)" }}
              >
                <div className="text-right hidden sm:block leading-tight">
                  <div
                    className="mono text-[10px] font-bold"
                    style={{ color: "var(--accent)", letterSpacing: "0.12em" }}
                  >
                    {role}
                  </div>
                  <div className="text-[10px]" style={{ color: "var(--ink-faint)" }}>
                    {identity}
                  </div>
                </div>
                <button
                  onClick={signOut}
                  title={ROLE_PROFILES[role].cannot}
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  Switch role
                </button>
              </div>
            )}
          </div>
        </div>

        <nav
          className="flex items-stretch gap-0.5 px-5 overflow-x-auto"
          style={{ borderTop: "1px solid var(--rule-soft)" }}
          aria-label="Primary"
        >
          {visible.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.hint}
                aria-current={active ? "page" : undefined}
                className="flex items-center px-3 py-2 text-[12.5px] no-underline hover:no-underline whitespace-nowrap"
                style={{
                  color: active ? "var(--ink)" : "var(--ink-mute)",
                  borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}`,
                  fontWeight: active ? 600 : 400,
                }}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <ScenarioBar />

      <main className="flex-1 min-w-0">{children}</main>

      <footer
        className="px-5 py-2.5 text-[11px] shrink-0 flex flex-wrap gap-x-5 gap-y-1.5 items-baseline no-print"
        style={{
          borderTop: "1px solid var(--rule)",
          color: "var(--ink-faint)",
          background: "var(--surface)",
        }}
      >
        <span className="max-w-[92ch]">
          Prototype. AI-extracted terms, deterministically calculated margin,
          settlement instructions generated in message shape and never transmitted,
          pinned simulated market snapshots. No transaction is executed, no market
          infrastructure is connected and no regulatory approval is claimed.
        </span>
        <span className="ml-auto flex gap-4 shrink-0">
          <Link href="/agents">Agents</Link>
          <Link href="/settlement">Settlement</Link>
          <Link href="/methodology">Methodology</Link>
        </span>
      </footer>
    </div>
  );
}

/**
 * The scenario bar.
 *
 * One selector, at the top of every screen, driving every panel below it. The
 * baseline is chosen here too, because the before/after comparison is not a
 * separate feature — it is the same run measured against a different snapshot, and
 * putting the two controls side by side says so.
 */
function ScenarioBar() {
  const scenarios = useScenarios();
  const currentKey = useAether((s) => s.currentKey);
  const baselineKey = useAether((s) => s.baselineKey);
  const setCurrent = useAether((s) => s.setCurrent);
  const setBaseline = useAether((s) => s.setBaseline);

  const summary = scenarios.data?.find((s) => s.key === currentKey)?.summary;

  return (
    <div
      className="shrink-0 flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-2 no-print"
      style={{ borderBottom: "1px solid var(--rule)", background: "var(--surface-2)" }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="eyebrow">Snapshot</span>
        {scenarios.data?.map((scenario) => (
          <button
            key={scenario.key}
            onClick={() => setCurrent(scenario.key)}
            className={scenario.key === currentKey ? "primary" : ""}
            title={scenario.summary}
            aria-pressed={scenario.key === currentKey}
            style={{ fontSize: 11.5, padding: "4px 11px" }}
          >
            {scenario.name}
          </button>
        ))}
      </div>

      <div
        className="flex items-center gap-2 flex-wrap pl-5"
        style={{ borderLeft: "1px solid var(--rule)" }}
      >
        <span className="eyebrow" title="What the current snapshot is measured against.">
          Baseline
        </span>
        {scenarios.data?.map((scenario) => (
          <button
            key={scenario.key}
            onClick={() => setBaseline(scenario.key)}
            aria-pressed={scenario.key === baselineKey}
            title={`Compare against ${scenario.name}`}
            style={{
              fontSize: 11.5,
              padding: "4px 11px",
              borderColor:
                scenario.key === baselineKey ? "var(--accent-dim)" : "var(--rule)",
              color:
                scenario.key === baselineKey ? "var(--accent)" : "var(--ink-mute)",
              fontWeight: scenario.key === baselineKey ? 700 : 400,
            }}
          >
            {scenario.name}
          </button>
        ))}
      </div>

      {summary && (
        <span
          className="text-[11.5px] hidden lg:block"
          style={{ color: "var(--ink-mute)" }}
        >
          {summary}
        </span>
      )}
    </div>
  );
}
