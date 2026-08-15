/**
 * API client.
 *
 * Frontend and backend are separate processes; this module is the only place the
 * frontend knows the backend exists.
 */

import type {
  Agreement,
  DocumentFormat,
  EvaluationReport,
  Extraction,
  Health,
  Methodology,
  RunResult,
  Scenario,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the AETHER API at ${API_BASE}. Start it with: uvicorn aether.api.main:app --port 8000`,
      0,
    );
  }

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = await response.text();
    }
    throw new ApiError(describeError(response.status, detail), response.status, detail);
  }

  return (await response.json()) as T;
}

function describeError(status: number, detail: unknown): string {
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (typeof detail === "string" && detail) return detail;
  return `Request failed with status ${status}.`;
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  methodology: () => request<Methodology>("/api/v1/methodology"),

  scenarios: () =>
    request<{ scenarios: Scenario[] }>("/api/v1/scenarios").then((r) => r.scenarios),

  runScenario: (key: string) =>
    request<RunResult>(`/api/v1/scenarios/${key}/run`, { method: "POST" }),

  document: (id: string) =>
    request<{ document_id: string; text: string }>(`/api/v1/documents/${id}`),

  extract: (id: string, sourceFormat: "md" | "pdf" = "md") =>
    request<Extraction>(
      `/api/v1/documents/${id}/extract?source_format=${sourceFormat}`,
      { method: "POST" },
    ),

  documentFormats: (id: string) =>
    request<{ document_id: string; formats: DocumentFormat[] }>(
      `/api/v1/documents/${id}/formats`,
    ).then((r) => r.formats),

  terms: (id: string) => request<Extraction>(`/api/v1/documents/${id}/terms`),

  confirmField: (
    id: string,
    body: { path: string; reviewer: string; rationale: string; value?: unknown },
  ) =>
    request<Extraction>(`/api/v1/documents/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  freeze: (id: string) =>
    request<{ status: string; agreement: Agreement }>(
      `/api/v1/documents/${id}/freeze`,
      { method: "POST" },
    ),

  evaluation: (id: string) =>
    request<EvaluationReport>(`/api/v1/documents/${id}/evaluation`),
};
