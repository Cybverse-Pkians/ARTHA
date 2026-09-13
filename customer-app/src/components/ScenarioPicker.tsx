import { useMemo, useState } from "react";
import type { CustomerRow } from "../api";
import { t, type Lang } from "../i18n";

/** Switch between the seeded demo customers, grouped by how they are flagged.
 *
 * The old chip row listed every customer in one undifferentiated line, labelled
 * each with a hard-coded tag taken from a table of tokens that mostly did not
 * exist, and gave no way to find the one you wanted. The point of seeding
 * fifteen customers is that they differ — a farmer with no instalment, a
 * borrower two instalments behind, an account mid-restructuring — so the picker
 * is organised by the thing that differs.
 *
 * Every badge here is read from the decision service. Nothing on this component
 * asserts a state it has not been told.
 */

export interface ScenarioGroup {
  id: string;
  label: string;
  hint: string;
  match: (c: CustomerRow) => boolean;
}

export const SMA_COLOUR: Record<string, string> = {
  SMA_0: "#bd7712",
  SMA_1: "#c1653a",
  SMA_2: "#c74055",
  NPA: "#8e2433",
};

const RECOVERY_COLOUR: Record<string, string> = {
  WATCH: "#5848b0",
  AT_RISK: "#bd7712",
  RECOVERY: "#c74055",
};

const GROUPS: ScenarioGroup[] = [
  {
    id: "all",
    label: "All customers",
    hint: "Every seeded profile.",
    match: () => true,
  },
  {
    id: "flagged",
    label: "Flagged — SMA",
    hint: "Behind on an instalment: SMA-0, SMA-1 or SMA-2 by days past due.",
    match: (c) => c.sma_stage !== "STANDARD",
  },
  {
    id: "recovery",
    label: "In Recovery Mode",
    hint: "Selling suppressed while the customer is assisted or a plan is tracked.",
    match: (c) => c.recovery_state !== "STABLE",
  },
  {
    id: "adversarial",
    label: "Adversarial",
    hint: "Deliberately constructed to attack the system rather than to be served by it.",
    match: (c) => c.tags.includes("adversarial"),
  },
  {
    id: "healthy",
    label: "Up to date",
    hint: "Nothing overdue and no Recovery-Mode state.",
    match: (c) => c.sma_stage === "STANDARD" && c.recovery_state === "STABLE",
  },
];

export function ScenarioPicker({
  lang,
  customers,
  selected,
  onSelect,
  onReset,
  busy,
}: {
  lang: Lang;
  customers: CustomerRow[];
  selected: string;
  onSelect: (token: string) => void;
  onReset: () => void;
  busy: boolean;
}) {
  const [group, setGroup] = useState("all");

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const g of GROUPS) out[g.id] = customers.filter(g.match).length;
    return out;
  }, [customers]);

  const active = GROUPS.find((g) => g.id === group) ?? GROUPS[0];
  const shown = useMemo(() => customers.filter(active.match), [customers, active]);

  if (customers.length === 0) return null;

  return (
    <div className="scenario-picker">
      <div className="scenario-head">
        <span className="demo-picker-label">{t(lang, "demo_scenario")}</span>
        <div className="scenario-filters" role="tablist" aria-label="Filter demo customers">
          {GROUPS.map((g) => (
            <button
              key={g.id}
              role="tab"
              aria-selected={group === g.id}
              className={`scenario-filter${group === g.id ? " scenario-filter-on" : ""}`}
              onClick={() => setGroup(g.id)}
              disabled={counts[g.id] === 0 && g.id !== "all"}
              title={g.hint}
            >
              {g.label}
              <span className="scenario-count">{counts[g.id]}</span>
            </button>
          ))}
        </div>
      </div>

      <p className="scenario-hint">
        {active.hint}{" "}
        <button type="button" className="link-button" onClick={onReset} disabled={busy}>
          {t(lang, "demo_reset")}
        </button>{" "}
        <span className="muted">— {t(lang, "demo_reset_hint")}</span>
      </p>

      <div className="scenario-chips">
        {shown.map((c) => {
          const isSelected = c.customer_token === selected;
          const flagged = c.sma_stage !== "STANDARD";
          const inRecovery = c.recovery_state !== "STABLE";
          return (
            <button
              key={c.customer_token}
              className={`scenario-chip${isSelected ? " scenario-chip-on" : ""}`}
              aria-pressed={isSelected}
              disabled={busy && !isSelected}
              onClick={() => onSelect(c.customer_token)}
            >
              <span className="scenario-chip-top">
                <span className="scenario-chip-name">{c.name}</span>
                {flagged ? (
                  <span
                    className="scenario-tag"
                    style={{ background: SMA_COLOUR[c.sma_stage] ?? "#4d6187" }}
                  >
                    {c.sma_stage_label} · {c.days_past_due}d
                  </span>
                ) : null}
                {inRecovery ? (
                  <span
                    className="scenario-tag"
                    style={{ background: RECOVERY_COLOUR[c.recovery_state] ?? "#4d6187" }}
                  >
                    {c.recovery_state.replace(/_/g, " ")}
                  </span>
                ) : null}
              </span>
              <span className="scenario-chip-role">{c.label}</span>
              <span className="scenario-chip-meta">
                {c.income_type.replace(/_/g, " ").toLowerCase()} · {c.district} ·{" "}
                {c.balance}
              </span>
              {flagged && c.arrears ? (
                <span className="scenario-chip-arrears">
                  {c.arrears.missed_instalments} {t(lang, "arrears_missed")} ·{" "}
                  {c.arrears.overdue_amount}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <p className="scenario-hint">No seeded customer currently matches this filter.</p>
      ) : null}
    </div>
  );
}
