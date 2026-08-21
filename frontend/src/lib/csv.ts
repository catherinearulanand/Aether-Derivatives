/**
 * CSV reading and writing.
 *
 * Two jobs: parse a custodian statement or internal ledger a user drops onto the
 * reconciliation screen, and write an audit export a reader can open in Excel.
 *
 * The parser is deliberately small but not naive. It handles quoted fields
 * containing commas and embedded quotes, CRLF from Windows-authored files, a BOM
 * from Excel, and leading `#` comment lines — vendor extracts routinely carry a
 * provenance banner above the header row, and the fixtures in this repository do
 * too. It does not attempt to be a general CSV engine; it reports what it cannot
 * read rather than guessing.
 */

export interface ParsedCsv {
  headers: string[];
  rows: Record<string, string>[];
  /** Comment lines stripped from the top of the file, in order. */
  banner: string[];
}

export class CsvError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CsvError";
  }
}

/** Split one CSV line, honouring quotes. */
function splitLine(line: string): string[] {
  const fields: string[] = [];
  let field = "";
  let quoted = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];

    if (quoted) {
      if (char === '"') {
        if (line[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') quoted = true;
    else if (char === ",") {
      fields.push(field);
      field = "";
    } else field += char;
  }

  fields.push(field);
  return fields.map((value) => value.trim());
}

export function parseCsv(text: string): ParsedCsv {
  const clean = text.replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  const lines = clean.split("\n");

  const banner: string[] = [];
  let cursor = 0;
  while (cursor < lines.length) {
    const line = lines[cursor];
    if (line.trim() === "") {
      cursor += 1;
      continue;
    }
    if (line.startsWith("#")) {
      banner.push(line.replace(/^#\s?/, ""));
      cursor += 1;
      continue;
    }
    break;
  }

  if (cursor >= lines.length) {
    throw new CsvError("The file has no header row — every line is blank or a comment.");
  }

  const headers = splitLine(lines[cursor]).map((h) => h.replace(/^"|"$/g, ""));
  if (headers.length < 2) {
    throw new CsvError(
      "Only one column was found. The file may be tab- or semicolon-separated; " +
        "this reader expects commas.",
    );
  }

  const rows: Record<string, string>[] = [];
  for (let i = cursor + 1; i < lines.length; i += 1) {
    const line = lines[i];
    if (line.trim() === "" || line.startsWith("#")) continue;

    const values = splitLine(line);
    if (values.length !== headers.length) {
      throw new CsvError(
        `Line ${i + 1} has ${values.length} fields but the header declares ` +
          `${headers.length}. The file is malformed or a quoted field is unclosed.`,
      );
    }
    const row: Record<string, string> = {};
    headers.forEach((header, index) => {
      row[header] = values[index];
    });
    rows.push(row);
  }

  if (rows.length === 0) {
    throw new CsvError("The file has a header row but no data.");
  }

  return { headers, rows, banner };
}

/** Fail early and by name when a file is missing a column the caller needs. */
export function requireColumns(
  parsed: ParsedCsv,
  required: readonly string[],
  what: string,
): void {
  const missing = required.filter((column) => !parsed.headers.includes(column));
  if (missing.length > 0) {
    throw new CsvError(
      `The ${what} is missing ${missing.length === 1 ? "a column" : "columns"}: ` +
        `${missing.join(", ")}. Found: ${parsed.headers.join(", ")}.`,
    );
  }
}

function escapeField(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * Build a CSV from rows keyed by column.
 *
 * `banner` lines are written above the header prefixed with `#`, so an export
 * carries its own provenance and this module's own parser can read it back.
 */
export function buildCsv(
  columns: readonly { key: string; header: string }[],
  rows: readonly Record<string, unknown>[],
  banner: readonly string[] = [],
): string {
  const head = banner.map((line) => `# ${line}`).join("\n");
  const header = columns.map((c) => escapeField(c.header)).join(",");
  const body = rows
    .map((row) => columns.map((c) => escapeField(row[c.key])).join(","))
    .join("\n");
  return [head, header, body].filter(Boolean).join("\n") + "\n";
}

/**
 * Hand a generated file to the browser.
 *
 * A blob URL rather than a data URI, because an audit export of a few hundred
 * events comfortably exceeds what some browsers accept in a data URI.
 */
export function downloadFile(
  filename: string,
  content: string,
  mime = "text/csv;charset=utf-8",
): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
