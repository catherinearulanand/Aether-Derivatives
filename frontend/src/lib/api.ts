/**
 * API client.
 *
 * Frontend and backend are separate processes; this module is the only place the
 * frontend knows the backend exists.
 */

import type {
  Agreement,
  AssistantAnswer,
  AssistantTurn,
  Comparison,
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

  // A Response body is a stream and can be consumed exactly once. Reading it as
  // text first and parsing afterwards keeps the non-JSON case recoverable:
  // calling .json() and falling back to .text() drains the stream on the failed
  // parse, and the .text() then throws "body stream already read" — which
  // replaces the real failure with a meaningless one. That is precisely the case
  // that matters, because a request that never reaches the API comes back as the
  // platform's HTML error page rather than as JSON.
  const body = await response.text().catch(() => "");

  if (!response.ok) {
    let detail: unknown = body;
    try {
      detail = (JSON.parse(body) as { detail?: unknown }).detail ?? body;
    } catch {
      // Not JSON. The raw body is the best detail available.
    }
    throw new ApiError(describeError(response.status, detail), response.status, detail);
  }

  try {
    return JSON.parse(body) as T;
  } catch {
    throw new ApiError(
      `The API returned ${response.status} with a body that is not JSON. The request was ` +
        `most likely answered by the platform in front of the API rather than by the API.`,
      response.status,
      body.slice(0, 500),
    );
  }
}

function describeError(status: number, detail: unknown): string {
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  if (typeof detail === "string") {
    const text = detail.trim();
    // An API error is JSON. Anything else came from the platform in front of the
    // API — an HTML 404 or 5xx page — and quoting its markup into the UI helps
    // nobody. Say what the shape of the response implies instead.
    if (text && !text.startsWith("<") && text.length <= 300) return text;
    if (text) {
      return `Request failed with status ${status}. The response was not JSON, which means ` +
        `the request did not reach the API.`;
    }
  }
  return `Request failed with status ${status}.`;
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  methodology: () => request<Methodology>("/api/v1/methodology"),

  scenarios: () =>
    request<{ scenarios: Scenario[] }>("/api/v1/scenarios").then((r) => r.scenarios),

  runScenario: (key: string) =>
    request<RunResult>(`/api/v1/scenarios/${key}/run`, { method: "POST" }),

  /**
   * Two runs and the exact difference between them.
   *
   * The subtraction happens in Python with `Decimal`. The browser renders the
   * result and never computes a money delta itself.
   */
  comparison: (before: string, after: string) =>
    request<Comparison>(`/api/v1/comparison/${before}/${after}`),

  /** Record a human sign-off into the run's hash chain. Executes nothing. */
  approve: (
    key: string,
    body: { approver: string; role: string; note: string; occurred_at: string },
  ) =>
    request<RunResult>(`/api/v1/scenarios/${key}/approve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  revokeApproval: (key: string) =>
    request<RunResult>(`/api/v1/scenarios/${key}/approve`, { method: "DELETE" }),

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

  /**
   * Ask the assistant.
   *
   * The agent runs server-side, which is not an implementation detail: the model
   * key never reaches the browser, and every figure in the answer is retrieved by a
   * tool over the same deterministic run the panels render. A reply that names a
   * figure no tool returned is rejected before this promise resolves.
   */
  assistantChat: (body: {
    question: string;
    scenario_key: string;
    baseline_key: string;
    role: string | null;
    history: AssistantTurn[];
  }) =>
    request<AssistantAnswer>("/api/v1/assistant/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Opening questions this role can actually be told the answer to. */
  assistantSuggestions: (role: string | null) =>
    request<{ suggestions: string[]; mode: string; model_id: string | null }>(
      `/api/v1/assistant/suggestions${role ? `?role=${role}` : ""}`,
    ),
};
