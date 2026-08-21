/**
 * Shared data access.
 *
 * Every screen reads the run through these hooks, and every hook keys its query by
 * the scenario held in the session store. Two consequences, both deliberate:
 *
 * 1. React Query deduplicates. Six panels asking for the same run issue one
 *    request and render one object, so the dashboard, the workflow, the analytics
 *    and the assistant are literally reading the same bytes.
 * 2. Changing the scenario in one place changes it everywhere. There is no screen
 *    holding a private copy of "which scenario am I looking at".
 *
 * `staleTime: Infinity` is set on the client: a pinned snapshot's figures cannot
 * change, so there is nothing to refetch.
 */

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "./api";
import { useAether } from "./store";
import type { RunResult } from "./types";
import { buildWorkflow, type Workflow } from "./workflow";

export function useScenarios() {
  return useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health });
}

export function useRun(key: string) {
  return useQuery({
    queryKey: ["run", key],
    queryFn: () => api.runScenario(key),
    enabled: Boolean(key),
  });
}

/** The run every screen renders. */
export function useCurrentRun() {
  const key = useAether((s) => s.currentKey);
  return useRun(key);
}

/** The run the current one is measured against. */
export function useBaselineRun() {
  const key = useAether((s) => s.baselineKey);
  return useRun(key);
}

/**
 * The comparison between two named snapshots.
 *
 * Deltas are computed server-side in `Decimal`; this hook only transports them.
 * Keyed by the pair, so the desk blotter asking for consecutive valuation dates
 * and the workflow screen asking for baseline-to-current share a cache when the
 * pair happens to match.
 */
export function useComparisonBetween(before: string, after: string) {
  return useQuery({
    queryKey: ["comparison", before, after],
    queryFn: () => api.comparison(before, after),
    enabled: Boolean(before) && Boolean(after) && before !== after,
  });
}

/** The before/after comparison for the snapshot pair currently selected. */
export function useComparison() {
  const baselineKey = useAether((s) => s.baselineKey);
  const currentKey = useAether((s) => s.currentKey);
  return useComparisonBetween(baselineKey, currentKey);
}

/** The nine-stage workflow, derived from the current run. */
export function useWorkflow(): Workflow | null {
  const { data } = useCurrentRun();
  return useMemo(() => (data ? buildWorkflow(data) : null), [data]);
}

/**
 * Record or withdraw a human approval.
 *
 * On success the run's cache entry is replaced with the server's response rather
 * than invalidated, so the extended hash chain and the new workflow state appear
 * together in one render — a half-updated approval state on a margin screen would
 * be worse than a slow one.
 */
export function useApproval(scenarioKey?: string) {
  const client = useQueryClient();
  const currentKey = useAether((s) => s.currentKey);
  const key = scenarioKey ?? currentKey;
  const identity = useAether((s) => s.identity);
  const role = useAether((s) => s.role);

  const write = (data: RunResult) => {
    client.setQueryData(["run", key], data);
  };

  const approve = useMutation({
    mutationFn: (note: string) => {
      if (!identity || !role) {
        throw new Error("Sign in before approving a decision.");
      }
      return api.approve(key, {
        approver: identity,
        role,
        note,
        // The approval's timestamp is recorded once, here, and replayed by the
        // server on every subsequent run. That is what keeps the chain
        // reproducible after a human has signed it.
        occurred_at: new Date().toISOString(),
      });
    },
    onSuccess: write,
  });

  const revoke = useMutation({
    mutationFn: () => api.revokeApproval(key),
    onSuccess: write,
  });

  return { approve, revoke };
}
