/** Thin client for the ARTHA decision service.
 *
 * Everything this console shows comes from the same decision log the regulator
 * rendering is built from. There is no separate "dashboard" data path, because a
 * second path is a second version of the truth.
 */

const BASE = import.meta.env.VITE_ARTHA_API ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText} — ${body.slice(0, 200)}`);
  }
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
};

// --- payload shapes -------------------------------------------------------

export interface QueueRow {
  customer_token: string;
  verdict: string;
  pd_uplift_90d: number;
  lead_time_days: number | null;
  pay_intent: string;
  anomaly_score: number;
  evidence: string[];
  income_type: string;
  district: string;
  balance: string;
}

export interface QueueResponse {
  capacity: number;
  assessed: number;
  in_queue: number;
  excluded_as_unactionable: number;
  note: string;
  queue: QueueRow[];
  excluded: { customer_token: string; verdict: string; reason: string }[];
  data_provenance: string;
}

export interface CorrelatedAlert {
  dimension: string;
  key: string;
  affected_customers: number;
  median_delay_days: number;
  description: string;
  customer_tokens: string[];
}

export interface GateCheckRow {
  check: string;
  passed: boolean;
  detail: string;
  reason_code: string | null;
  outcome_if_failed: string;
}

export interface ReasonCodeRow {
  code: string;
  title: string;
  description: string;
  polarity: string;
  adverse_action: boolean;
  weight: number;
  params: Record<string, string>;
}

export interface TwinPayload {
  verdict: string;
  sentence: string;
  safe_buffer: string;
  safe_buffer_paise: number;
  lowest_projected: string;
  breach_probability: number;
  baseline_breach_probability: number;
  resilience_score: number;
  shocks_absorbed: number;
  first_breach_date: string | null;
  scenarios: {
    key: string;
    label: string;
    passed: boolean;
    breach_probability: number;
    min_balance_p05_paise: number;
  }[];
  path_with: number[];
  path_without: number[];
  path_p05: number[];
}

export interface SupervisoryGap {
  recovery_state: string;
  asset_classification: {
    days_past_due: number;
    state: string;
    band: string;
    is_stressed: boolean;
    next_state: string | null;
    days_to_next_downgrade: number | null;
    verify_against_circular: string;
  };
  behavioural_concern: number;
  lead: number;
  acting_early: boolean;
  missed: boolean;
  note: string;
}

export interface DecisionResponse {
  decision_id: string;
  outcome: string;
  recovery_state: string;
  supervisory: SupervisoryGap;
  customer: {
    language: string;
    headline: string;
    detail: string;
    counterfactual: string | null;
    spoken: string;
    privacy_note: string;
  };
  regulator: {
    decision_id: string;
    outcome: string;
    created_at: string;
    policy_version: string;
    model_versions: Record<string, string>;
    input_hash: string;
    recovery_state: string;
    moment: { trigger: string; description: string; evidence_dates: string[] } | null;
    offer: Record<string, unknown> | null;
    twin: Record<string, unknown> | null;
    counterfactual: Record<string, unknown> | null;
    gate_trace: GateCheckRow[];
    reason_codes: ReasonCodeRow[];
    consent: { purposes_used: string[]; purposes_excluded: string[] };
  };
  privacy_ledger: Record<string, unknown>;
  moments: { trigger: string; description: string; priority: number; products: string[] }[];
  suppressed_candidates: { product_id: string; reason: string; blocking_check: string | null }[];
  is_adverse_action: boolean;
  sentinel?: {
    verdict: string;
    pd_uplift_90d: number;
    anomaly_score: number;
    pay_intent: string;
    lead_time_days: number | null;
    evidence: string[];
    contact_recommended: boolean;
    fraud_signals: {
      pattern: string;
      description: string;
      response: string;
      severity: number;
      cooling_off_minutes: number;
    }[];
  };
  intervention?: {
    withheld_reason: string;
    recommended: {
      rung: number;
      name: string;
      description: string;
      customer_sentence: string;
      regulatory_cost: string;
      reg_cost: string;
      auto_proposable: boolean;
      requires_human_credit_officer: boolean;
      economic_cost: string;
      reversible: boolean;
      new_emi: string | null;
      new_day_of_month: number | null;
      additional_total_cost: string;
    } | null;
    alternatives: {
      rung: number;
      name: string;
      regulatory_cost: string;
      reg_cost: string;
      requires_human_credit_officer: boolean;
      economic_cost: string;
    }[];
  };
  offer?: {
    product_id: string;
    product_name: string;
    family: string;
    amount: string;
    amount_paise: number;
    eligible_amount: string;
    reduced_from_eligibility: boolean;
    tenure_months: number;
    emi: string;
    day_of_month: number;
    annual_rate: number;
    total_interest: string;
    rationale: string;
  };
  kfs?: {
    spoken_script: string;
    lines: { key: string; label: string; value: string }[];
    tenure_options: {
      tenure_months: number;
      emi: string;
      total_interest: string;
      additional_cost: string;
      recommended: boolean;
    }[];
  };
  twin?: TwinPayload;
  data_provenance: string;
}

export interface CustomerRow {
  customer_token: string;
  income_type: string;
  income_type_confidence: number;
  posture: string;
  recovery_state: string;
  balance: string;
  monthly_income: string;
  district: string;
  is_rural: boolean;
  thin_file: boolean;
  transactions: number;
}
