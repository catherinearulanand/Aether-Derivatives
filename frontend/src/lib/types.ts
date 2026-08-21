/**
 * Types mirroring the AETHER API.
 *
 * Money is always `{ amount: string, currency: string }` — a decimal string, never a
 * JavaScript number. A nine-figure notional would silently lose cents through an
 * IEEE-754 double, so amounts are formatted from the string and never arithmetic'd
 * in the browser. Every number displayed here was computed in Python with `Decimal`.
 */

export interface Money {
  amount: string;
  currency: string;
}

export interface WaterfallStep {
  label: string;
  value: Money;
  clause: string;
  explanation: string;
  is_gate: boolean;
}

export interface TradeValuation {
  trade_id: string;
  trade_type: string;
  native_value: Money;
  base_value: Money;
  detail: string;
}

export interface Exposure {
  netting_set_id: string;
  snapshot_id: string;
  as_of: string;
  base_currency: string;
  exposure: Money;
  gross_positive: Money;
  netting_benefit: Money;
  trade_count: number;
  trades: TradeValuation[];
}

export interface InitialMargin {
  method: string;
  disclaimer: string;
  gross_im: Money;
  net_to_gross_ratio: string;
  initial_margin: Money;
  charged_to_vm_call: boolean;
}

export interface MarginCall {
  agreement_id: string;
  netting_set_id: string;
  snapshot_id: string;
  as_of: string;
  engine_version: string;
  base_currency: string;
  exposure: Money;
  transferor: string;
  threshold: Money;
  independent_amount: Money;
  minimum_transfer_amount: Money;
  credit_support_amount: Money;
  posted_value: Money;
  unrounded_amount: Money;
  rounded_amount: Money;
  call_amount: Money;
  direction: "DELIVERY" | "RETURN" | "NONE";
  gated_by_mta: boolean;
  mta_before_rounding: boolean;
  has_call: boolean;
  summary: string;
  waterfall: WaterfallStep[];
}

export interface AllocationLine {
  asset_id: string;
  description: string;
  asset_class: string;
  issuer: string;
  currency: string;
  market_value_posted: Money;
  effective_percentage: string;
  effective_value: Money;
  funding_spread_bps: string;
  cost_per_effective_unit_bps: string;
  annual_cost: Money;
  fx_haircut_applied: boolean;
  fx_drag_bps: string;
  headline_rank: number;
  effective_rank: number;
  available_market_value: Money | null;
  selected: boolean;
  not_selected_reason: string;
}

export interface ShadowPrice {
  name: string;
  description: string;
  shadow_price_bps: string;
  binding: boolean;
}

export interface Allocation {
  agreement_id: string;
  snapshot_id: string;
  status: "OPTIMAL" | "INFEASIBLE" | "NOT_REQUIRED";
  message: string;
  base_currency: string;
  required_value: Money;
  allocated_value: Money;
  total_cost: Money;
  baseline_cost: Money;
  saving: Money;
  saving_percentage: string;
  lines: AllocationLine[];
  baseline_lines: AllocationLine[];
  shadow_prices: ShadowPrice[];
  excluded: { asset_id: string; reason: string }[];
  considered: AllocationLine[];
  cross_border: AllocationLine[];
  baseline_covers_requirement: boolean;
}

export interface Decision {
  decision_id: string;
  agreement_id: string;
  snapshot_id: string;
  as_of: string;
  engine_version: string;
  action:
    | "POST_COLLATERAL"
    | "RECALL_COLLATERAL"
    | "DEMAND_COLLATERAL"
    | "NO_ACTION"
    | "ESCALATE";
  status: "PENDING_APPROVAL" | "NO_ACTION_REQUIRED" | "BLOCKED";
  transferor: string;
  amount: Money;
  exposure: Money;
  credit_support_amount: Money;
  initial_margin: Money;
  allocation_cost: Money;
  baseline_cost: Money;
  saving: Money;
  saving_percentage: string;
  asset_count: number;
  headline: string;
  rationale: string[];
  requires_human_approval: boolean;
  disclaimer: string;
  simulated: boolean;
}

export interface AuditEvent {
  seq: number;
  actor: string;
  actor_type: "ENGINE" | "AGENT" | "HUMAN" | "SYSTEM";
  action: string;
  entity_type: string;
  entity_id: string;
  occurred_at: string;
  hash: string;
  prev_hash: string;
  payload: Record<string, unknown>;
}

export interface Audit {
  chain_id: string;
  head_hash: string;
  verified: boolean;
  break_at: number | null;
  verification_message: string;
  events: AuditEvent[];
}

export interface EligibleCollateralItem {
  ref: string;
  asset_class: string;
  issuer_type: string;
  issuer: string | null;
  currency: string | null;
  non_base_currency_only: boolean;
  min_maturity_years: string | null;
  max_maturity_years: string | null;
  min_rating: string | null;
  valuation_percentage: string;
}

export interface Agreement {
  agreement_id: string;
  netting_set_id: string;
  csa_type: string;
  governing_law: string;
  terms_version: number;
  base_currency: string;
  eligible_currencies: string[];
  fx_haircut_pct: string;
  mta_before_rounding: boolean;
  excluded_issuers: string[];
  party_a: PartyTerms;
  party_b: PartyTerms;
  rounding: {
    increment: Money;
    delivery_direction: string;
    return_direction: string;
  };
  eligible_collateral: EligibleCollateralItem[];
  concentration_limits: { scope: string; limit_percentage: string }[];
  simulated: boolean;
}

export interface PartyTerms {
  party: string;
  threshold: Money;
  minimum_transfer_amount: Money;
  independent_amount: Money;
}

export interface Scenario {
  key: string;
  name: string;
  snapshot_id?: string;
  as_of?: string;
  summary: string;
  argument: string;
}

export interface Sensitivity {
  risk_class: "INTEREST_RATE" | "FX";
  measure: "DELTA" | "VEGA";
  bucket: string;
  label: string;
  tenor_years: number | null;
  value: Money;
  risk_weight: string;
  weighted_value: Money;
}

export interface RiskBucket {
  risk_class: "INTEREST_RATE" | "FX";
  bucket: string;
  sensitivity_count: number;
  weighted_sum: Money;
  margin: Money;
}

export interface SensitivityMargin {
  netting_set_id: string;
  snapshot_id: string;
  as_of: string;
  method: string;
  interest_rate_margin: Money;
  fx_margin: Money;
  vega_margin: Money;
  total_margin: Money;
  disclaimer: string;
  vega_note: string;
  buckets: RiskBucket[];
  sensitivities: Sensitivity[];
}

export interface SettlementLeg {
  sequence: number;
  asset_id: string;
  description: string;
  asset_class: string;
  currency: string;
  market_value: Money;
  valuation_percentage: string;
  collateral_value: Money;
  safekeeping_account: string;
  delivery_method: string;
}

export interface Settlement {
  instruction_id: string;
  agreement_id: string;
  netting_set_id: string;
  snapshot_id: string;
  as_of: string;
  value_date: string;
  direction: "DELIVERY" | "RETURN" | "NONE";
  deliverer: string;
  deliverer_bic: string;
  receiver: string;
  receiver_bic: string;
  call_amount: Money;
  collateral_value: Money;
  is_balanced: boolean;
  status: string;
  message_types: string[];
  engine_version: string;
  transmitted: boolean;
  disclaimer: string;
  legs: SettlementLeg[];
  iso20022_xml: string;
  mt527: string;
}

export interface AgentAction {
  agent: string;
  tool: string;
  intent: string;
  arguments: Record<string, string | number | boolean | null>;
  outcome: string;
}

export interface ToolSpec {
  name: string;
  owner: string;
  description: string;
  required_arguments: string[];
  produces: string;
}

export interface Agents {
  plan_source: string;
  roster: { role: string; title: string; responsibility: string }[];
  actions: AgentAction[];
  tools: ToolSpec[];
  boundary: string;
}

export interface Timing {
  elapsed_ms: number;
  stages: number;
  measured: string;
  manual_baseline_hours: string;
  manual_baseline_note: string;
}

export interface DocumentFormat {
  format: string;
  label: string;
  available: boolean;
  note: string;
  bytes?: number;
  characters?: number;
}

// ------------------------------------------------------- threshold & approval

export type ThresholdState = "WITHIN" | "WARNING" | "BREACHED";

export interface ThresholdStatus {
  state: ThresholdState;
  message: string;
  exposure: Money;
  threshold: Money;
  credit_support_amount: Money;
  minimum_transfer_amount: Money;
  call_amount: Money;
  transferor: string;
  gated_by_mta: boolean;
}

/** A recorded human sign-off. Recording an approval executes nothing. */
export interface Approval {
  approver: string;
  role: string;
  note: string;
  occurred_at: string;
  decision_id: string;
  action_approved: string;
  amount_approved: string;
  currency: string;
}

// ------------------------------------------------------------- comparison

export type Direction = "UP" | "DOWN" | "FLAT" | "NOT_COMPARABLE";

export interface ComparisonMetric {
  id: string;
  label: string;
  basis: string;
  before: Money;
  after: Money;
  before_available: boolean;
  after_available: boolean;
  comparable: boolean;
  /** Null when the two sides are not comparable — never a stand-in zero. */
  delta: Money | null;
  direction: Direction;
  unavailable_reason: string;
}

export interface ComparisonSide {
  key: string;
  name: string;
  summary: string;
  argument: string;
  run_id: string;
  snapshot_id: string;
  snapshot_label: string;
  as_of: string;
  decision: string;
  transferor: string;
  threshold_status: ThresholdStatus;
  asset_count: number;
}

export interface AllocationDeltaRow {
  asset_id: string;
  description: string;
  asset_class: string;
  currency: string;
  before: Money;
  after: Money;
  delta: Money;
  status: "ADDED" | "REMOVED" | "INCREASED" | "DECREASED" | "UNCHANGED";
}

export interface Comparison {
  before: ComparisonSide;
  after: ComparisonSide;
  base_currency: string;
  engine_version: string;
  metrics: ComparisonMetric[];
  allocation_delta: AllocationDeltaRow[];
  transferor_changed: boolean;
  method: string;
  simulated: boolean;
}

// ---------------------------------------------------------------- run

export interface RunResult {
  run_id: string;
  trace_id: string;
  as_of: string;
  engine_version: string;
  snapshot: {
    snapshot_id: string;
    label: string;
    as_of: string;
    simulated: boolean;
  };
  agreement: Agreement;
  exposure: Exposure;
  sensitivity_margin: SensitivityMargin;
  initial_margin: InitialMargin;
  margin_call: MarginCall;
  allocation: Allocation | null;
  settlement: Settlement | null;
  agents: Agents;
  decision: Decision;
  audit: Audit;
  scenario?: Scenario;
  terms_source?: string;
  timing?: Timing;
  threshold_status: ThresholdStatus;
  /** Null until a permitted role signs the decision. */
  approval: Approval | null;
}

// ---------------------------------------------------------------- extraction

export interface Citation {
  page: number;
  section: string;
  quote: string;
}

export interface ExtractedField {
  path: string;
  value: unknown;
  confidence: number;
  source: "AGENT" | "HUMAN";
  requires_review: boolean;
  is_resolved: boolean;
  review_reason: string | null;
  review_note: string;
  reviewer: string | null;
  reviewer_rationale: string;
  citation: Citation | null;
  conditional: {
    trigger: string;
    condition: string;
    value_if_triggered: Record<string, string> | null;
    trigger_citation: Citation | null;
  } | null;
}

export interface PendingItem {
  path: string;
  current_value: string;
  reason: string;
  question: string;
  alternative: string | null;
  citation: string;
}

export interface Extraction {
  document_id: string;
  document_sha256: string;
  model_id: string;
  prompt_version: string;
  mode: string;
  temperature: number;
  cache_hit: boolean;
  latency_ms: number;
  mean_confidence: string;
  confidence_threshold: number;
  is_ready_to_freeze: boolean;
  simulated: boolean;
  fields: ExtractedField[];
  pending_review: PendingItem[];
}

export interface EvaluationReport {
  document_id: string;
  model_id: string;
  prompt_version: string;
  mode: string;
  scored_fields: number;
  value_accuracy: string;
  citation_accuracy: string;
  review_flag_recall: string;
  overall_score: string;
  passes: boolean;
  summary: string;
  missing_fields: string[];
  field_scores: {
    path: string;
    value_match: boolean;
    citation_match: boolean;
    review_flag_match: boolean;
    score: string;
    note: string;
  }[];
}

export interface Methodology {
  principle: string;
  modelled: string[];
  not_modelled: string[];
  never_claimed: Record<string, string>;
  confidence_threshold: number;
  mode: string;
  all_data_simulated: boolean;
}

export interface Health {
  status: string;
  mode: string;
  engine_version: string;
  model_id: string;
  live_available: boolean;
  simulated_data: boolean;
}
