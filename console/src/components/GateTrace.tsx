import type { GateCheckRow, ReasonCodeRow } from "../api";

/** The gate trace — every constraint and its outcome, including the ones that
 * passed (report §6.7).
 *
 * Showing only the failing check would be shorter and would defeat the purpose:
 * a supervisor is entitled to see that the other five constraints ran.
 */
export function GateTrace({ trace }: { trace: GateCheckRow[] }) {
  return (
    <div>
      {trace.map((c) => (
        <div className="check-row" key={c.check}>
          <span className={`check-mark ${c.passed ? "check-pass" : "check-fail"}`}>
            {c.passed ? "✓" : "✕"}
          </span>
          <span className="check-name">{c.check.replace(/_/g, " ")}</span>
          <span className="check-detail">
            {c.detail}
            {c.reason_code ? (
              <span className="mono muted"> · {c.reason_code}</span>
            ) : null}
            {!c.passed ? (
              <span className="mono muted"> · → {c.outcome_if_failed}</span>
            ) : null}
          </span>
        </div>
      ))}
    </div>
  );
}

export function ReasonCodes({ codes }: { codes: ReasonCodeRow[] }) {
  if (codes.length === 0) return <p className="muted small">No reason codes recorded.</p>;
  return (
    <div>
      {codes.map((r) => (
        <div
          key={r.code + r.title}
          className={
            "reason " +
            (r.polarity === "ADVERSE"
              ? "reason-adverse"
              : r.polarity === "FAVOURABLE"
                ? "reason-favourable"
                : "")
          }
        >
          <div className="reason-code">
            {r.code} · weight {r.weight.toFixed(2)}
            {r.adverse_action ? " · adverse action — human review required" : ""}
          </div>
          <div className="reason-title">{r.title}</div>
          <div className="reason-desc">{r.description}</div>
        </div>
      ))}
    </div>
  );
}
