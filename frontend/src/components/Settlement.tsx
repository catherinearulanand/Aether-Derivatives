"use client";

import { Chip, Panel, Stat } from "@/components/primitives";
import { formatDate, formatMoney } from "@/lib/format";
import type { Settlement as SettlementInstruction } from "@/lib/types";
import { useState } from "react";

type MessageView = "legs" | "iso" | "mt";

/**
 * The generated settlement instruction.
 *
 * Everything here is real output from the deterministic allocation. What is not real
 * is connectivity: nothing is transmitted, there is no network, and the banner says
 * so before a reader sees the message text. Generating a message and sending one are
 * one careless sentence apart, so the distinction is made structurally.
 */
export function Settlement({ settlement }: { settlement: SettlementInstruction | null }) {
  const [view, setView] = useState<MessageView>("legs");

  if (!settlement) return null;

  return (
    <Panel
      title="Settlement instruction"
      aside={
        <div className="flex items-center gap-2">
          <Chip tone="warn" title="Generated, never sent. No network connectivity exists.">
            Not transmitted
          </Chip>
          <Chip>{settlement.status.replace(/_/g, " ").toLowerCase()}</Chip>
        </div>
      }
    >
      <div
        className="px-4 py-3 grid sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-3.5"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <Stat
          label="Instruction"
          value={settlement.instruction_id}
          hint="derived by SHA-256 from the call. No clock, no counter."
        />
        <Stat
          label="Amount called"
          value={formatMoney(settlement.call_amount)}
          hint={`value date ${formatDate(settlement.value_date)}`}
          tone="accent"
        />
        <Stat
          label="Collateral value"
          value={formatMoney(settlement.collateral_value)}
          hint={settlement.is_balanced ? "covers the requirement" : "does not cover"}
          tone={settlement.is_balanced ? "default" : "crit"}
        />
        <Stat
          label="Messages"
          value={String(settlement.message_types.length)}
          hint={settlement.message_types.join(" · ")}
        />
      </div>

      <div
        className="px-4 py-3 flex flex-wrap items-center gap-x-8 gap-y-2 text-[12px]"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        <div>
          <span className="eyebrow block mb-0.5">Deliverer</span>
          <span>{settlement.deliverer}</span>{" "}
          <span className="mono text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
            {settlement.deliverer_bic}
          </span>
        </div>
        <span className="mono" style={{ color: "var(--accent)" }}>
          →
        </span>
        <div>
          <span className="eyebrow block mb-0.5">Receiver</span>
          <span>{settlement.receiver}</span>{" "}
          <span className="mono text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
            {settlement.receiver_bic}
          </span>
        </div>
      </div>

      <div
        className="flex items-center gap-1 px-4 py-2"
        style={{ borderBottom: "1px solid var(--rule)" }}
      >
        {(
          [
            ["legs", `Movements (${settlement.legs.length})`],
            ["iso", "ISO 20022"],
            ["mt", "MT527"],
          ] as [MessageView, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setView(key)}
            className={view === key ? "primary" : ""}
            style={{ fontSize: 11.5, padding: "3px 10px" }}
          >
            {label}
          </button>
        ))}
      </div>

      {view === "legs" &&
        (settlement.legs.length === 0 ? (
          <p className="px-4 py-4 m-0 text-[12px]" style={{ color: "var(--ink-mute)" }}>
            No movements: the counterparty owes this collateral, so they select what to
            deliver. Only the margin call request is generated, and their collateral
            proposal comes back in reply.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="grid">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Asset</th>
                  <th>Ccy</th>
                  <th className="num">Market value</th>
                  <th className="num">Valuation</th>
                  <th className="num">Collateral value</th>
                  <th>Account</th>
                </tr>
              </thead>
              <tbody>
                {settlement.legs.map((leg) => (
                  <tr key={leg.sequence}>
                    <td className="num tnum">{leg.sequence}</td>
                    <td>
                      <div className="mono text-[11px]">{leg.asset_id}</div>
                      <div className="text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
                        {leg.description}
                      </div>
                    </td>
                    <td className="mono text-[11px]">{leg.currency}</td>
                    <td className="num tnum">{formatMoney(leg.market_value)}</td>
                    <td className="num tnum">
                      {(Number(leg.valuation_percentage) * 100).toFixed(2)}%
                    </td>
                    <td className="num tnum font-semibold">
                      {formatMoney(leg.collateral_value)}
                    </td>
                    <td className="mono text-[10.5px]" style={{ color: "var(--ink-faint)" }}>
                      {leg.safekeeping_account}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}

      {view !== "legs" && (
        <pre
          className="m-0 px-4 py-3 text-[11px] leading-relaxed overflow-x-auto"
          style={{ background: "var(--surface-2)", color: "var(--ink-mid)", maxHeight: 420 }}
        >
          {view === "iso" ? settlement.iso20022_xml : settlement.mt527}
        </pre>
      )}

      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        {settlement.disclaimer}
      </p>
    </Panel>
  );
}
