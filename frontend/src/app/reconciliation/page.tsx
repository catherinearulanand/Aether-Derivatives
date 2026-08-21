"use client";

import { RoleGuard } from "@/components/RoleGuard";
import { Chip, Panel, Stat } from "@/components/primitives";
import { CsvError, buildCsv, downloadFile, parseCsv, requireColumns, type ParsedCsv } from "@/lib/csv";
import {
  EXTERNAL_COLUMNS,
  INTERNAL_COLUMNS,
  isException,
  reconcile,
  statusLabel,
  type MatchStatus,
  type ReconciliationResult,
} from "@/lib/reconcile";
import { useMemo, useRef, useState } from "react";

/**
 * Collateral reconciliation.
 *
 * .. rubric:: The morning job
 *
 * A collateral team's day starts by proving that what the bank thinks it holds and
 * what the custodian says it holds are the same thing. This screen does that
 * comparison and classifies every difference.
 *
 * .. rubric:: No custodian is connected
 *
 * There is no custodian integration here and the screen says so where a user would
 * otherwise assume one. Both sides are uploaded as CSV. Sample files ship with the
 * repository, generated with a documented set of deliberately injected breaks so
 * that the classifier can be scored rather than admired.
 *
 * .. rubric:: The arithmetic
 *
 * Differences are computed with exact scaled-integer arithmetic on the decimal
 * strings, never with `parseFloat`. A phantom one-cent break on a
 * four-hundred-million-rupee position would discredit the whole screen, and that
 * is precisely what floating point produces at that magnitude.
 */
export default function ReconciliationPage() {
  return (
    <RoleGuard permission="act:reconcile">
      <Reconciliation />
    </RoleGuard>
  );
}

interface Upload {
  name: string;
  parsed: ParsedCsv;
}

function Reconciliation() {
  const [internal, setInternal] = useState<Upload | null>(null);
  const [external, setExternal] = useState<Upload | null>(null);
  const [errors, setErrors] = useState<{ internal?: string; external?: string }>({});
  const [tolerance, setTolerance] = useState(5);
  const [filter, setFilter] = useState<"exceptions" | "all">("exceptions");
  const [loadingSamples, setLoadingSamples] = useState(false);

  const result: ReconciliationResult | null = useMemo(() => {
    if (!internal || !external) return null;
    return reconcile(internal.parsed.rows, external.parsed.rows, tolerance);
  }, [internal, external, tolerance]);

  function accept(
    side: "internal" | "external",
    file: File,
  ): void {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = parseCsv(String(reader.result));
        requireColumns(
          parsed,
          side === "internal" ? INTERNAL_COLUMNS : EXTERNAL_COLUMNS,
          side === "internal" ? "internal ledger" : "custodian statement",
        );
        if (side === "internal") setInternal({ name: file.name, parsed });
        else setExternal({ name: file.name, parsed });
        setErrors((previous) => ({ ...previous, [side]: undefined }));
      } catch (error) {
        const message =
          error instanceof CsvError || error instanceof Error
            ? error.message
            : "The file could not be read.";
        setErrors((previous) => ({ ...previous, [side]: message }));
        if (side === "internal") setInternal(null);
        else setExternal(null);
      }
    };
    reader.onerror = () =>
      setErrors((previous) => ({
        ...previous,
        [side]: "The file could not be read from disk.",
      }));
    reader.readAsText(file);
  }

  /**
   * Load the committed sample pair.
   *
   * The files live in `fixtures/reconciliation/`. They are fetched rather than
   * bundled so the page ships without a copy of the data, and so a user can see
   * that they are ordinary CSVs rather than something the app synthesises.
   */
  async function loadSamples() {
    setLoadingSamples(true);
    try {
      const [internalText, externalText] = await Promise.all([
        fetch("/samples/internal_ledger.csv").then((r) => r.text()),
        fetch("/samples/custodian_statement.csv").then((r) => r.text()),
      ]);
      const internalParsed = parseCsv(internalText);
      const externalParsed = parseCsv(externalText);
      requireColumns(internalParsed, INTERNAL_COLUMNS, "internal ledger");
      requireColumns(externalParsed, EXTERNAL_COLUMNS, "custodian statement");
      setInternal({ name: "internal_ledger.csv", parsed: internalParsed });
      setExternal({ name: "custodian_statement.csv", parsed: externalParsed });
      setErrors({});
    } catch (error) {
      setErrors({
        internal:
          error instanceof Error
            ? `The sample files could not be loaded: ${error.message}`
            : "The sample files could not be loaded.",
      });
    } finally {
      setLoadingSamples(false);
    }
  }

  const visibleRows =
    result?.rows.filter((row) => filter === "all" || isException(row.status)) ?? [];

  return (
    <div className="p-4 max-w-[1500px] mx-auto flex flex-col gap-3">
      <header className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div>
          <h1 className="serif m-0 text-[25px] font-bold leading-tight">
            Collateral reconciliation
          </h1>
          <p
            className="m-0 mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--ink-mute)", maxWidth: "84ch" }}
          >
            The bank&apos;s internal collateral ledger against the custodian&apos;s daily
            statement, matched on safekeeping account and asset. Every difference
            is classified and every classification names its reason.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Chip tone="warn" title="No custodian integration exists. Both sides are uploaded.">
            No custodian connected
          </Chip>
          <Chip>files stay in the browser</Chip>
        </div>
      </header>

      <Panel
        title="Load the two sides"
        aside={
          <button
            onClick={loadSamples}
            disabled={loadingSamples}
            style={{ fontSize: 11, padding: "3px 10px" }}
          >
            {loadingSamples ? "Loading…" : "Load the sample pair"}
          </button>
        }
      >
        <div className="grid md:grid-cols-2 gap-3 px-4 py-3.5">
          <Dropzone
            label="Internal ledger"
            hint="The bank's own record. Needs: position_id, safekeeping_account, asset_id, currency, nominal, market_value."
            upload={internal}
            error={errors.internal}
            onFile={(file) => accept("internal", file)}
            onClear={() => {
              setInternal(null);
              setErrors((p) => ({ ...p, internal: undefined }));
            }}
          />
          <Dropzone
            label="Custodian statement"
            hint="The external daily statement. Needs: safekeeping_account, asset_id, currency, nominal, market_value."
            upload={external}
            error={errors.external}
            onFile={(file) => accept("external", file)}
            onClear={() => {
              setExternal(null);
              setErrors((p) => ({ ...p, external: undefined }));
            }}
          />
        </div>

        <div
          className="px-4 py-2.5 flex flex-wrap items-center gap-x-5 gap-y-2"
          style={{ borderTop: "1px solid var(--rule)" }}
        >
          <label className="flex items-center gap-2.5 text-[11.5px]">
            <span className="eyebrow shrink-0">Tolerance</span>
            <input
              type="range"
              min={0}
              max={50}
              step={1}
              value={tolerance}
              onChange={(event) => setTolerance(Number(event.target.value))}
              style={{ width: 160, padding: 0 }}
              aria-label="Matching tolerance in basis points"
            />
            <span className="tnum" style={{ width: 46 }}>
              {tolerance} bp
            </span>
          </label>
          <span
            className="text-[11px] leading-snug"
            style={{ color: "var(--ink-faint)", maxWidth: "72ch" }}
          >
            A value difference at or inside the tolerance is recorded as matched
            rather than raised. Two vendors pricing the same bond do not agree to
            the last cent, and a screen with no tolerance reports the whole book as
            broken.
          </span>
        </div>

        {internal && (
          <Provenance banner={internal.parsed.banner} name={internal.name} />
        )}
      </Panel>

      {!result ? (
        <Panel title="Reconciliation summary">
          <p className="px-4 py-8 m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
            Load both files to run the reconciliation. The sample pair is generated
            by <span className="mono">scripts/generate_reconciliation_data.py</span>{" "}
            with a documented set of deliberately injected breaks, so the classifier
            can be checked against an answer key rather than taken on trust.
          </p>
        </Panel>
      ) : (
        <>
          <Summary result={result} />

          <Panel
            title={filter === "exceptions" ? "Exceptions" : "All positions"}
            aside={
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setFilter("exceptions")}
                  className={filter === "exceptions" ? "primary" : ""}
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  Exceptions ({result.summary.exceptions})
                </button>
                <button
                  onClick={() => setFilter("all")}
                  className={filter === "all" ? "primary" : ""}
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  All ({result.summary.total})
                </button>
                <button
                  onClick={() => exportReconciliation(result)}
                  style={{ fontSize: 11, padding: "3px 9px" }}
                >
                  Export CSV
                </button>
              </div>
            }
          >
            {visibleRows.length === 0 ? (
              <p
                className="px-4 py-8 m-0 text-[12.5px]"
                style={{ color: "var(--ok)" }}
              >
                No exceptions. Every position on both sides agrees within the{" "}
                {result.toleranceBps} bp tolerance.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="grid">
                  <thead>
                    <tr>
                      <th scope="col">Account · asset</th>
                      <th scope="col">Custodian</th>
                      <th scope="col" className="num">
                        Internal
                      </th>
                      <th scope="col" className="num">
                        Custodian
                      </th>
                      <th scope="col" className="num">
                        Difference
                      </th>
                      <th scope="col" className="num">
                        bp
                      </th>
                      <th scope="col" style={{ width: 170 }}>
                        Status
                      </th>
                      <th scope="col" style={{ minWidth: 260 }}>
                        Reason
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.slice(0, 250).map((row) => (
                      <tr key={row.key}>
                        <td>
                          <div className="mono text-[11px]">
                            {row.safekeeping_account}
                          </div>
                          <div
                            className="mono text-[10.5px]"
                            style={{ color: "var(--ink-faint)" }}
                          >
                            {row.asset_id}
                            {row.position_id ? ` · ${row.position_id}` : ""}
                          </div>
                        </td>
                        <td className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
                          {row.custodian || "—"}
                        </td>
                        <td className="num">
                          {row.internal_market_value ? (
                            <>
                              <span style={{ color: "var(--ink-faint)" }}>
                                {row.internal_currency}{" "}
                              </span>
                              {row.internal_market_value}
                            </>
                          ) : (
                            <span style={{ color: "var(--ink-faint)" }}>absent</span>
                          )}
                        </td>
                        <td className="num">
                          {row.external_market_value ? (
                            <>
                              <span
                                style={{
                                  color:
                                    row.status === "CURRENCY_MISMATCH"
                                      ? "var(--crit)"
                                      : "var(--ink-faint)",
                                }}
                              >
                                {row.external_currency}{" "}
                              </span>
                              {row.external_market_value}
                            </>
                          ) : (
                            <span style={{ color: "var(--ink-faint)" }}>absent</span>
                          )}
                        </td>
                        <td
                          className="num"
                          style={{
                            color: row.difference?.startsWith("-")
                              ? "var(--crit)"
                              : "var(--ink)",
                          }}
                        >
                          {row.difference ?? "—"}
                        </td>
                        <td className="num" style={{ color: "var(--ink-mute)" }}>
                          {row.difference_bps === null
                            ? "—"
                            : row.difference_bps.toFixed(2)}
                        </td>
                        <td>
                          <StatusChip status={row.status} />
                        </td>
                        <td
                          className="text-[11px] leading-snug"
                          style={{ color: "var(--ink-mid)" }}
                        >
                          {row.explanation}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {visibleRows.length > 250 && (
                  <p
                    className="px-4 py-2.5 m-0 text-[11.5px]"
                    style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
                  >
                    Showing the first 250 of {visibleRows.length} rows. Export the
                    CSV for the complete set.
                  </p>
                )}
              </div>
            )}
          </Panel>

          <Panel title="How a difference is classified">
            <div className="overflow-x-auto">
              <table className="grid">
                <thead>
                  <tr>
                    <th scope="col" style={{ width: 190 }}>
                      Status
                    </th>
                    <th scope="col">What it means, and what a desk does about it</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["MATCHED", "Both sides agree exactly. No action."],
                      [
                        "MATCHED_WITHIN_TOLERANCE",
                        "Values differ inside the tolerance — vendor pricing noise. Recorded and absorbed, not raised. Widening the tolerance to hide real breaks is the failure mode this row exists to make visible.",
                      ],
                      [
                        "VALUE_DIFFERENCE",
                        "Values differ beyond tolerance. A stale vendor feed or a disputed mark; goes to the pricing team.",
                      ],
                      [
                        "QUANTITY_DIFFERENCE",
                        "Nominals differ. Usually a partial settlement — part of the delivery has not reached the account.",
                      ],
                      [
                        "CURRENCY_MISMATCH",
                        "The two sides disagree on currency. The amounts may look close and are not comparable at all; this is why currency is checked before value.",
                      ],
                      [
                        "MISSING_EXTERNAL",
                        "Internal holds it, the custodian does not. Settlement in flight — but it is unconfirmed collateral until the custodian shows it.",
                      ],
                      [
                        "MISSING_INTERNAL",
                        "The custodian holds it, internal does not. An unexpected receipt, or collateral booked to the wrong account. Never net this against a missing-external row: doing so hides a misdirection.",
                      ],
                    ] as [MatchStatus, string][]
                  ).map(([status, meaning]) => (
                    <tr key={status}>
                      <td>
                        <StatusChip status={status} />
                      </td>
                      <td
                        className="text-[11.5px] leading-snug"
                        style={{ color: "var(--ink-mid)" }}
                      >
                        {meaning}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}

function StatusChip({ status }: { status: MatchStatus }) {
  const tone =
    status === "MATCHED"
      ? "ok"
      : status === "MATCHED_WITHIN_TOLERANCE"
        ? "default"
        : status === "MISSING_EXTERNAL" || status === "MISSING_INTERNAL"
          ? "crit"
          : "warn";

  const className =
    tone === "ok"
      ? "chip chip-ok"
      : tone === "crit"
        ? "chip chip-crit"
        : tone === "warn"
          ? "chip chip-warn"
          : "chip";

  return <span className={className}>{statusLabel(status)}</span>;
}

function Summary({ result }: { result: ReconciliationResult }) {
  const s = result.summary;

  return (
    <Panel
      title="Reconciliation summary"
      aside={
        <div className="flex items-center gap-2">
          {result.statementDate && <Chip>as of {result.statementDate}</Chip>}
          <Chip tone={s.exceptions === 0 ? "accent" : "warn"}>
            {(s.exceptionRate * 100).toFixed(1)}% exception rate
          </Chip>
        </div>
      }
    >
      <div className="px-4 py-3.5 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-x-5 gap-y-4">
        <Stat label="Positions compared" value={String(s.total)} />
        <Stat label="Matched" value={String(s.matched)} tone="accent" />
        <Stat
          label="Within tolerance"
          value={String(s.withinTolerance)}
          hint={`≤ ${result.toleranceBps} bp`}
        />
        <Stat
          label="Value difference"
          value={String(s.valueDifference)}
          tone={s.valueDifference ? "warn" : "default"}
        />
        <Stat
          label="Quantity difference"
          value={String(s.quantityDifference + s.currencyMismatch)}
          hint={`${s.currencyMismatch} currency mismatch`}
          tone={s.quantityDifference + s.currencyMismatch ? "warn" : "default"}
        />
        <Stat
          label="Missing at custodian"
          value={String(s.missingExternal)}
          tone={s.missingExternal ? "crit" : "default"}
        />
        <Stat
          label="Missing internally"
          value={String(s.missingInternal)}
          tone={s.missingInternal ? "crit" : "default"}
        />
      </div>

      <div style={{ borderTop: "1px solid var(--rule)" }}>
        <div className="px-4 pt-3 pb-1">
          <span className="eyebrow">Total variance, by currency</span>
        </div>
        {s.variance.length === 0 ? (
          <p
            className="px-4 pb-3.5 m-0 text-[12px]"
            style={{ color: "var(--ok)" }}
          >
            No variance. Every difference fell inside the tolerance.
          </p>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th scope="col">Currency</th>
                <th scope="col" className="num">
                  Exceptions
                </th>
                <th scope="col" className="num">
                  Net (internal − custodian)
                </th>
                <th scope="col" className="num">
                  Gross (absolute)
                </th>
              </tr>
            </thead>
            <tbody>
              {s.variance.map((entry) => (
                <tr key={entry.currency}>
                  <td className="mono text-[11.5px]">{entry.currency}</td>
                  <td className="num">{entry.rows}</td>
                  <td
                    className="num"
                    style={{
                      color: entry.net.startsWith("-") ? "var(--crit)" : "var(--ink)",
                    }}
                  >
                    {entry.net}
                  </td>
                  <td className="num font-semibold">{entry.gross}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p
        className="px-4 py-2.5 m-0 text-[11.5px] leading-relaxed"
        style={{ borderTop: "1px solid var(--rule)", color: "var(--ink-faint)" }}
      >
        Variance is reported per currency and never summed across them. Converting
        an INR position into USD to produce one headline number would need an FX
        rate this screen has not been given, and inventing one would be the exact
        kind of quiet error a reconciliation exists to catch. Differences are
        computed with exact decimal arithmetic, not floating point.
      </p>
    </Panel>
  );
}

function Provenance({ banner, name }: { banner: string[]; name: string }) {
  if (banner.length === 0) return null;
  return (
    <div
      className="px-4 py-2.5 flex flex-col gap-1"
      style={{ borderTop: "1px solid var(--rule)" }}
    >
      <span className="eyebrow">Provenance declared by {name}</span>
      {banner.map((line) => (
        <span key={line} className="mono text-[10.5px]" style={{ color: "var(--warn)" }}>
          {line}
        </span>
      ))}
    </div>
  );
}

function Dropzone({
  label,
  hint,
  upload,
  error,
  onFile,
  onClear,
}: {
  label: string;
  hint: string;
  upload: Upload | null;
  error?: string;
  onFile: (file: File) => void;
  onClear: () => void;
}) {
  const [active, setActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="eyebrow">{label}</span>
        {upload && (
          <button onClick={onClear} style={{ fontSize: 10.5, padding: "2px 8px" }}>
            Clear
          </button>
        )}
      </div>

      <div
        className="dropzone"
        data-active={active}
        data-loaded={Boolean(upload)}
        onDragOver={(event) => {
          event.preventDefault();
          setActive(true);
        }}
        onDragLeave={() => setActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setActive(false);
          const file = event.dataTransfer.files[0];
          if (file) onFile(file);
        }}
      >
        {upload ? (
          <div className="flex flex-col gap-1">
            <span className="mono text-[12px] status-ok">{upload.name}</span>
            <span className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
              {upload.parsed.rows.length} rows · {upload.parsed.headers.length} columns
            </span>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <span className="text-[12px]" style={{ color: "var(--ink-mute)" }}>
              Drop a CSV here
            </span>
            <button onClick={() => inputRef.current?.click()} style={{ fontSize: 11 }}>
              Choose a file
            </button>
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          style={{ display: "none" }}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onFile(file);
            event.target.value = "";
          }}
        />
      </div>

      {error ? (
        <p className="m-0 text-[11.5px] leading-snug" style={{ color: "var(--crit)" }}>
          {error}
        </p>
      ) : (
        <p className="m-0 text-[10.5px] leading-snug" style={{ color: "var(--ink-faint)" }}>
          {hint}
        </p>
      )}
    </div>
  );
}

/** The exception report, in the same classification the screen displays. */
function exportReconciliation(result: ReconciliationResult): void {
  const columns = [
    { key: "safekeeping_account", header: "Safekeeping account" },
    { key: "asset_id", header: "Asset" },
    { key: "description", header: "Description" },
    { key: "position_id", header: "Internal position" },
    { key: "counterparty", header: "Counterparty" },
    { key: "custodian", header: "Custodian" },
    { key: "internal_currency", header: "Internal currency" },
    { key: "internal_nominal", header: "Internal nominal" },
    { key: "internal_market_value", header: "Internal market value" },
    { key: "external_currency", header: "Custodian currency" },
    { key: "external_nominal", header: "Custodian nominal" },
    { key: "external_market_value", header: "Custodian market value" },
    { key: "difference", header: "Difference" },
    { key: "difference_bps", header: "Difference (bp)" },
    { key: "stale_price_as_of", header: "Custodian priced as of" },
    { key: "status", header: "Status" },
    { key: "explanation", header: "Reason" },
  ];

  const csv = buildCsv(
    columns,
    result.rows.map((row) => ({
      ...row,
      difference_bps: row.difference_bps?.toFixed(4) ?? "",
    })),
    [
      "AETHER collateral reconciliation report. SIMULATED DATA.",
      `Statement date: ${result.statementDate ?? "unstated"}. Tolerance: ${result.toleranceBps} bp.`,
      `${result.summary.total} positions compared, ${result.summary.exceptions} exceptions ` +
        `(${(result.summary.exceptionRate * 100).toFixed(2)}%).`,
      "Matched on safekeeping account plus asset. Variance is not summed across currencies.",
      "No custodian system is connected. Both sides were supplied as files.",
    ],
  );

  downloadFile(
    `aether-reconciliation-${result.statementDate ?? "report"}.csv`,
    csv,
  );
}
