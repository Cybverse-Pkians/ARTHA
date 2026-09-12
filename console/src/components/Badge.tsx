import type { ReactNode } from "react";

type Tone = "good" | "warning" | "serious" | "critical" | "neutral";

/** Status colours ship with an icon and a label, never colour alone. */
const GLYPH: Record<Tone, string> = {
  good: "●",
  warning: "▲",
  serious: "◆",
  critical: "■",
  neutral: "○",
};

export function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`badge badge-${tone}`}>
      <span aria-hidden="true">{GLYPH[tone]}</span>
      {children}
    </span>
  );
}

export function outcomeTone(outcome: string): Tone {
  switch (outcome) {
    case "ACT":
      return "good";
    case "PROTECT":
      return "serious";
    case "VERIFY":
      return "critical";
    default:
      return "neutral";
  }
}

export function verdictTone(verdict: string): Tone {
  switch (verdict) {
    case "FRAUD":
      return "critical";
    case "FINANCIAL_DISTRESS":
      return "serious";
    case "BENIGN_LIFE_CHANGE":
      return "warning";
    case "UNAFFORDABLE":
      return "critical";
    case "FRAGILE":
      return "warning";
    case "AFFORDABLE":
      return "good";
    default:
      return "neutral";
  }
}
