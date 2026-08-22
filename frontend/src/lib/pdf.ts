/**
 * The audit trail as a PDF document.
 *
 * .. rubric:: Why the hashes are printed in full
 *
 * An audit export exists so somebody outside this application can check the
 * chain. Truncating a SHA-256 to sixteen characters makes a tidier table and an
 * unverifiable document: a reader cannot recompute `h(prev || content)` from a
 * prefix. So every hash is printed complete, and the page is laid out landscape
 * in a monospaced face to make room for it.
 *
 * That is the whole reason this is not simply the screen sent to a printer. The
 * table on screen truncates hashes because a human reading a console does not
 * want 64 hex characters per row; the document does not have that luxury.
 *
 * .. rubric:: Why it is generated in the browser
 *
 * Two reasons, and the second is the one that matters.
 *
 * The practical one: the frontend static-exports to object storage and the API
 * runs in a function whose package is already close to its size limit. A
 * server-side renderer would add to that for no functional gain.
 *
 * The substantive one: the document is built from the same `RunResult` object
 * the table on screen renders. There is no second query, no second
 * serialisation and no second source of truth, so the export cannot disagree
 * with what the reviewer was looking at when they exported it. A server-side
 * renderer would re-fetch, and re-fetching is where "the report says something
 * different from the screen" comes from.
 *
 * .. rubric:: What the document does not claim
 *
 * It carries the chain's own verification result rather than asserting the
 * chain is valid, states that the data is simulated, and says that hashing makes
 * tampering detectable rather than impossible. An audit artefact that overstated
 * any of those would be the most damaging document this system could produce.
 */

import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { RunResult } from "./types";

/** Verdigris, matching the application's accent. */
const ACCENT: [number, number, number] = [47, 139, 124];
const INK: [number, number, number] = [17, 17, 17];
const MUTED: [number, number, number] = [110, 110, 110];
const RULE: [number, number, number] = [200, 200, 200];
const CRIT: [number, number, number] = [176, 48, 74];

const MARGIN = 12;

interface Meta {
  exportedBy: string;
  exportedAt: string;
}

/**
 * Build and download the report.
 *
 * `filename` mirrors the CSV export's convention so the two artefacts for one
 * run sort next to each other.
 */
export function exportAuditPdf(run: RunResult, meta: Meta): void {
  const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
  const width = doc.internal.pageSize.getWidth();

  const headerBottom = drawHeader(doc, run, meta, width);
  drawEvents(doc, run, headerBottom);
  drawFooters(doc, run);

  doc.save(`aether-audit-${run.trace_id}-${run.as_of}.pdf`);
}

/**
 * The identifying block.
 *
 * Everything a reader needs to know what they are holding before they read a
 * single event: which agreement, which snapshot, which engine, and whether the
 * chain verified.
 */
function drawHeader(doc: jsPDF, run: RunResult, meta: Meta, width: number): number {
  const audit = run.audit;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.setTextColor(...INK);
  doc.text("AETHER", MARGIN, 16);

  doc.setFont("helvetica", "normal");
  doc.setFontSize(11);
  doc.setTextColor(...MUTED);
  doc.text("Audit Trail Report", MARGIN + 24, 16);

  // The provenance stamp sits opposite the title, where a reader looks for it.
  doc.setFontSize(8);
  doc.text(`Exported ${meta.exportedAt}`, width - MARGIN, 12, { align: "right" });
  doc.text(`by ${meta.exportedBy}`, width - MARGIN, 16, { align: "right" });

  doc.setDrawColor(...ACCENT);
  doc.setLineWidth(0.6);
  doc.line(MARGIN, 19, width - MARGIN, 19);

  // Two columns of identifiers. Laid out as pairs rather than prose because a
  // reader scans this block for one value rather than reading it through.
  const left: [string, string][] = [
    ["Agreement", run.agreement.agreement_id],
    ["Netting set", run.exposure.netting_set_id],
    ["Market snapshot", run.snapshot.snapshot_id],
    ["Valuation date", run.as_of],
  ];
  const right: [string, string][] = [
    ["Chain", audit.chain_id],
    ["Engine version", run.engine_version],
    ["Trace", run.trace_id],
    ["Events", String(audit.events.length)],
  ];

  let y = 25;
  doc.setFontSize(7.5);
  for (let i = 0; i < left.length; i += 1) {
    doc.setTextColor(...MUTED);
    doc.text(left[i][0].toUpperCase(), MARGIN, y);
    doc.text(right[i][0].toUpperCase(), width / 2, y);

    doc.setTextColor(...INK);
    doc.setFont("courier", "normal");
    doc.text(left[i][1], MARGIN + 28, y);
    doc.text(right[i][1], width / 2 + 28, y);
    doc.setFont("helvetica", "normal");
    y += 4.4;
  }

  // The head hash gets its own line: it is 64 characters and it is the value a
  // reader checks the chain against.
  y += 1;
  doc.setTextColor(...MUTED);
  doc.setFontSize(7.5);
  doc.text("HEAD HASH", MARGIN, y);
  doc.setFont("courier", "normal");
  doc.setTextColor(...INK);
  doc.text(audit.head_hash, MARGIN + 28, y);
  doc.setFont("helvetica", "normal");
  y += 6;

  // Verification, reported rather than asserted.
  const verified = audit.verified;
  doc.setFillColor(...(verified ? ACCENT : CRIT));
  doc.rect(MARGIN, y - 3.4, 2, 4.6, "F");
  doc.setTextColor(...(verified ? ACCENT : CRIT));
  doc.setFont("helvetica", "bold");
  doc.setFontSize(8.5);
  doc.text(
    verified ? "CHAIN VERIFIED" : `CHAIN BROKEN AT EVENT ${audit.break_at}`,
    MARGIN + 4,
    y,
  );

  doc.setFont("helvetica", "normal");
  doc.setFontSize(7.5);
  doc.setTextColor(...MUTED);
  doc.text(audit.verification_message, MARGIN + 40, y);
  y += 6;

  doc.setTextColor(...CRIT);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(8);
  doc.text(
    "SIMULATED DATA — no transaction was executed and no regulatory approval is claimed.",
    MARGIN,
    y,
  );

  doc.setDrawColor(...RULE);
  doc.setLineWidth(0.2);
  doc.line(MARGIN, y + 3, doc.internal.pageSize.getWidth() - MARGIN, y + 3);

  return y + 7;
}

/**
 * The events.
 *
 * Hashes go in full, on their own wrapped lines, because a truncated hash
 * cannot be used to verify anything.
 */
function drawEvents(doc: jsPDF, run: RunResult, startY: number): void {
  const body = run.audit.events.map((event) => [
    String(event.seq),
    event.actor_type,
    event.actor,
    event.action,
    `${event.entity_type} · ${event.entity_id}`,
    event.occurred_at,
    splitHash(event.hash),
    splitHash(event.prev_hash),
  ]);

  autoTable(doc, {
    startY,
    head: [["#", "Actor type", "Actor", "Action", "Entity", "Occurred", "Hash", "Previous hash"]],
    body,
    theme: "grid",
    styles: {
      font: "courier",
      fontSize: 5.6,
      cellPadding: 1.1,
      lineColor: RULE,
      lineWidth: 0.1,
      textColor: INK,
      overflow: "linebreak",
      valign: "top",
    },
    headStyles: {
      font: "helvetica",
      fontStyle: "bold",
      fontSize: 6,
      fillColor: [238, 238, 238],
      textColor: INK,
      lineColor: RULE,
    },
    // Budget: 297mm page less two 12mm margins = 273mm usable. These total 233mm,
    // leaving room for cell padding. The two hash columns are deliberately
    // narrower than 64 monospaced characters so each hash wraps onto two lines
    // rather than being clipped — wrapped is readable, clipped is unverifiable.
    columnStyles: {
      0: { cellWidth: 6, halign: "right" },
      1: { cellWidth: 15 },
      2: { cellWidth: 34 },
      3: { cellWidth: 40 },
      4: { cellWidth: 40 },
      5: { cellWidth: 20 },
      6: { cellWidth: 39 },
      7: { cellWidth: 39 },
    },
    margin: { left: MARGIN, right: MARGIN, bottom: 16 },
    // A HUMAN event is the one a supervisor looks for first — it is where a
    // person, rather than the engine, changed the outcome.
    didParseCell: (data) => {
      if (data.section !== "body") return;
      if (data.row.raw && (data.row.raw as string[])[1] === "HUMAN") {
        data.cell.styles.fillColor = [252, 246, 232];
      }
    },
  });
}

/**
 * A hash across two aligned lines of 32 characters.
 *
 * The full 64 characters are present either way; this only decides where the
 * break falls, so the column reads as a block rather than ragged.
 */
function splitHash(hash: string): string {
  return `${hash.slice(0, 32)}
${hash.slice(32)}`;
}

/** Page numbers and the standing disclaimer. */
function drawFooters(doc: jsPDF, run: RunResult): void {
  const pages = doc.getNumberOfPages();
  const width = doc.internal.pageSize.getWidth();
  const height = doc.internal.pageSize.getHeight();

  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page);
    doc.setDrawColor(...RULE);
    doc.setLineWidth(0.2);
    doc.line(MARGIN, height - 11, width - MARGIN, height - 11);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(6.5);
    doc.setTextColor(...MUTED);
    doc.text(
      "Each event hashes its own canonical content plus its predecessor, so altering any record " +
        "invalidates every hash after it. Tamper-evident, not immutable.",
      MARGIN,
      height - 7,
    );
    doc.text(`${run.agreement.agreement_id} · ${run.audit.chain_id}`, MARGIN, height - 4);
    doc.text(`Page ${page} of ${pages}`, width - MARGIN, height - 4, { align: "right" });
  }
}
