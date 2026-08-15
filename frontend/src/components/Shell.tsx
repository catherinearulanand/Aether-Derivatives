"use client";

import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Margin Desk", hint: "Run the pipeline end to end" },
  { href: "/review", label: "Document Review", hint: "Extraction, citations, approval gate" },
  { href: "/agents", label: "Agents", hint: "The swarm and its tool boundary" },
  { href: "/settlement", label: "Settlement", hint: "ISO 20022 instruction, never sent" },
  { href: "/audit", label: "Audit Trail", hint: "Hash chain, agent to engine to decision" },
  { href: "/methodology", label: "Methodology", hint: "What is and isn't modelled" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health });

  return (
    <div className="min-h-screen flex flex-col">
      <header
        className="flex items-center gap-6 px-5 h-12 shrink-0"
        style={{ borderBottom: "1px solid var(--rule)", background: "var(--surface)" }}
      >
        <Link href="/" className="flex items-baseline gap-2.5 no-underline">
          <span
            className="mono font-bold"
            style={{ color: "var(--accent)", letterSpacing: "0.24em", fontSize: 14 }}
          >
            AETHER
          </span>
          <span className="eyebrow hidden md:inline">
            Margin &amp; Collateral Intelligence
          </span>
        </Link>

        <nav className="flex items-stretch gap-0.5 h-full">
          {NAV.map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.hint}
                className="flex items-center px-3 text-[12.5px] no-underline hover:no-underline"
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

        <div className="ml-auto flex items-center gap-2.5">
          <span className="chip chip-warn" title="Every figure in this system is simulated.">
            Simulated data
          </span>
          {health && (
            <>
              <span
                className="chip"
                title={
                  health.mode === "replay"
                    ? "Extraction served from a cached fixture. No network required."
                    : "Extraction calls the model live."
                }
              >
                {health.mode}
              </span>
              <span className="chip" title="Engine version, recorded on every result.">
                v{health.engine_version}
              </span>
            </>
          )}
        </div>
      </header>

      <main className="flex-1 min-w-0">{children}</main>

      <footer
        className="px-5 py-2 text-[11px] shrink-0"
        style={{
          borderTop: "1px solid var(--rule)",
          color: "var(--ink-faint)",
          background: "var(--surface)",
        }}
      >
        Prototype. AI-extracted terms, deterministically calculated margin, settlement
        instructions generated in message shape and never transmitted, pinned simulated
        market snapshots. No transaction is executed, no market infrastructure is
        connected and no regulatory approval is claimed.
      </footer>
    </div>
  );
}
