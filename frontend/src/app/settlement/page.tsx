"use client";

import { Settlement } from "@/components/Settlement";
import { Chip, ErrorPanel, Loading, Panel } from "@/components/primitives";
import { useCurrentRun } from "@/lib/hooks";

/**
 * The settlement screen.
 *
 * The boundary statement comes first, above the message text, because the order
 * matters: a reader should know that nothing is transmitted before they see
 * something that looks like a transmissible message.
 */
export default function SettlementPage() {
  const run = useCurrentRun();

  return (
    <div className="p-4 flex flex-col gap-3 max-w-[1600px] mx-auto">
      <section className="panel panel-warn">
        <div className="px-4 py-3.5">
          <div className="flex items-center gap-2 mb-1.5">
            <Chip tone="warn">Simulated settlement</Chip>
            <Chip>No network</Chip>
          </div>
          <h1 className="serif m-0 text-[23px] font-bold leading-tight">
            Instructions are generated. Nothing is sent.
          </h1>
          <p
            className="mt-2 mb-0 text-[12.5px] leading-relaxed max-w-[85ch]"
            style={{ color: "var(--ink-mid)" }}
          >
            Every line, quantity and valuation below is the optimiser&apos;s output, and
            the totals reconcile to the Delivery Amount. What does not exist is
            connectivity: there is no SWIFT membership, no network session, no service
            bureau and no gpi tracker anywhere in this system. The XML follows the
            element shape of the ISO 20022 collateral messages and has not been
            validated against their schemas; BICs and account numbers are synthetic
            placeholders in the correct format. Generating a message and sending one
            are different capabilities, and AETHER has only the first.
          </p>
        </div>
      </section>

      {run.isLoading && <Loading label="Generating the instruction" />}
      {run.isError && <ErrorPanel error={run.error} />}

      {run.data &&
        (run.data.settlement ? (
          <>
            <Settlement settlement={run.data.settlement} />
            <MessageReference />
          </>
        ) : (
          <Panel title="No instruction">
            <p className="px-4 py-6 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
              No transfer is due under this snapshot, so no instruction was generated.
              A settlement message for a zero transfer would misrepresent what the
              system decided.
            </p>
          </Panel>
        ))}
    </div>
  );
}

function MessageReference() {
  const messages: [string, string, string][] = [
    [
      "colr.003",
      "MarginCallRequest",
      "The call itself: what is owed, by whom, under which agreement, for which value date.",
    ],
    [
      "colr.005",
      "CollateralProposal",
      "The assets proposed to satisfy it, each with its haircut valuation and safekeeping account.",
    ],
    [
      "MT527",
      "Triparty Collateral Instruction",
      "The legacy form many custodians still accept. Field tags follow the MT527 layout.",
    ],
  ];

  return (
    <Panel title="What these messages are">
      <table className="grid">
        <thead>
          <tr>
            <th scope="col" style={{ width: 110 }}>Message</th>
            <th scope="col" style={{ width: 220 }}>Name</th>
            <th scope="col">Purpose</th>
          </tr>
        </thead>
        <tbody>
          {messages.map(([id, name, purpose]) => (
            <tr key={id}>
              <td className="mono text-[11.5px]" style={{ color: "var(--accent)" }}>
                {id}
              </td>
              <td className="text-[12px]">{name}</td>
              <td className="text-[11.5px]" style={{ color: "var(--ink-mid)" }}>
                {purpose}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p
        className="px-4 py-2.5 m-0 text-[11.5px]"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        When the counterparty owes the collateral, only the request is generated —
        they choose what to deliver, and their proposal comes back in reply. Switch to
        the flash crash scenario to see that case.
      </p>
    </Panel>
  );
}
