import type { DecisionResponse } from "../api";
import { t, type Lang } from "../i18n";

/** The Key Fact Statement, read aloud before consent.
 *
 * Report §6.2 and §9.3. The tenure table below always carries its last column —
 * what a longer tenure actually costs. A longer tenure lowers the monthly
 * payment *and* raises the total; the customer hears both halves before they
 * agree, not after.
 */
export function KeyFacts({
  lang,
  decision,
  onSpeak,
  onStartRequest,
}: {
  lang: Lang;
  decision: DecisionResponse;
  onSpeak: (text: string) => void;
  onStartRequest: () => void;
}) {
  const kfs = decision.kfs;
  if (!kfs) {
    // Reaching this screen with nothing to read used to be a cul-de-sac: one
    // flat sentence, no explanation of why, and no way onward. Say what a Key
    // Fact Statement is for, why there is not one, and offer the step that
    // would produce one.
    return (
      <div className="screen">
        <h1>{t(lang, "key_facts")}</h1>
        <div className="surface-card" style={{ marginTop: 12 }}>
          <h3>{t(lang, "kfs_none_title")}</h3>
          <p className="lede" style={{ marginBottom: 14 }}>{t(lang, "kfs_none_body")}</p>
          {decision.customer.counterfactual ? (
            <div className="refusal" style={{ marginBottom: 14 }}>
              <div className="refusal-title">{t(lang, "afford_structure_works")}</div>
              <div className="refusal-body">{decision.customer.counterfactual}</div>
            </div>
          ) : null}
          <button className="btn btn-primary" onClick={onStartRequest}>
            {t(lang, "kfs_none_action")} <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="screen">
      <h1>{t(lang, "key_facts")}</h1>
      <div className="spoken">{kfs.spoken_script}</div>
      <button className="btn" onClick={() => onSpeak(kfs.spoken_script)}>
        🔊 {t(lang, "read_aloud")}
      </button>

      <h2>{t(lang, "kfs_numbers")}</h2>
      {kfs.lines.map((l) => (
        <div className="kfs-row" key={l.key}>
          <span className="kfs-label">{l.label}</span>
          <span className="kfs-value">{l.value}</span>
        </div>
      ))}

      {kfs.tenure_options.length > 0 ? (
        <>
          <h2>{t(lang, "kfs_tenure")}</h2>
          <table className="tenure-table">
            <thead>
              <tr>
                <th>{t(lang, "kfs_months")}</th>
                <th>{t(lang, "kfs_every_month")}</th>
                <th>{t(lang, "kfs_extra")}</th>
              </tr>
            </thead>
            <tbody>
              {kfs.tenure_options.map((o) => (
                <tr key={o.tenure_months}>
                  <td>
                    {o.tenure_months}
                    {o.recommended ? " ✓" : ""}
                  </td>
                  <td>{o.emi}</td>
                  <td>{o.additional_cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="tenure-warn">{t(lang, "kfs_warn")}</p>
        </>
      ) : null}

      <p className="note" style={{ marginTop: 18 }}>{t(lang, "kfs_note")}</p>
    </div>
  );
}
