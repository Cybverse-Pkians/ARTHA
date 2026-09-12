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
}: {
  lang: Lang;
  decision: DecisionResponse;
  onSpeak: (text: string) => void;
}) {
  const kfs = decision.kfs;
  if (!kfs) {
    return (
      <div className="screen">
        <h1>{t(lang, "key_facts")}</h1>
        <p className="lede">There is no offer on the table, so there is no statement to read.</p>
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

      <h2>The numbers</h2>
      {kfs.lines.map((l) => (
        <div className="kfs-row" key={l.key}>
          <span className="kfs-label">{l.label}</span>
          <span className="kfs-value">{l.value}</span>
        </div>
      ))}

      {kfs.tenure_options.length > 0 ? (
        <>
          <h2>What a longer tenure really costs</h2>
          <table className="tenure-table">
            <thead>
              <tr>
                <th>Months</th>
                <th>Every month</th>
                <th>Extra in total</th>
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
          <p className="tenure-warn">
            A smaller monthly payment is not a smaller loan. The last column is what the extra
            months cost you.
          </p>
        </>
      ) : null}

      <p className="note" style={{ marginTop: 18 }}>
        Key Fact Statement content and format must be verified against the current RBI Digital
        Lending Directions before any live use.
      </p>
    </div>
  );
}
