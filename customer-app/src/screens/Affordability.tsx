import type { DecisionResponse } from "../api";
import { TwinChart } from "../components/TwinChart";
import { t, type Lang } from "../i18n";

/** The Financial Twin as the consent screen.
 *
 * Report §5.1: the same chart is the affordability engine, the customer-facing
 * explanation *and* the consent screen — so consent becomes informed by
 * construction rather than by disclosure. The customer is not agreeing to a
 * paragraph of terms; they are agreeing to a picture of their own balance with
 * and without the obligation.
 *
 * There is no countdown, no pre-ticked box and no "recommended" styling on the
 * agree button over the decline button.
 */
export function Affordability({
  lang,
  decision,
  onAgree,
  onDecline,
}: {
  lang: Lang;
  decision: DecisionResponse;
  onAgree: () => void;
  onDecline: () => void;
}) {
  const twin = decision.twin;
  if (!twin) {
    return (
      <div className="screen">
        <h1>{t(lang, "affordability")}</h1>
        <p className="lede">No obligation is being proposed, so there is nothing to test.</p>
      </div>
    );
  }

  return (
    <div className="screen">
      <h1>{t(lang, "affordability")}</h1>
      <p className="lede">{twin.sentence}</p>

      <TwinChart
        pathWith={twin.path_with}
        pathWithout={twin.path_without}
        pathP05={twin.path_p05}
        safeBufferPaise={twin.safe_buffer_paise}
      />

      <h2>If things go wrong</h2>
      {twin.scenarios.map((s) => (
        <div className="kfs-row" key={s.key}>
          <span className="kfs-label">{s.label}</span>
          <span className="kfs-value" style={{ color: s.passed ? "var(--good)" : "var(--critical)" }}>
            {s.passed ? "you stay above" : "you fall below"}
          </span>
        </div>
      ))}

      <div className="kfs-row">
        <span className="kfs-label">Lowest your balance would go</span>
        <span className="kfs-value">{twin.lowest_projected}</span>
      </div>
      <div className="kfs-row">
        <span className="kfs-label">{t(lang, "safe_buffer")}</span>
        <span className="kfs-value">{twin.safe_buffer}</span>
      </div>

      {decision.customer.counterfactual ? (
        <div className="refusal" style={{ marginTop: 16 }}>
          <div className="refusal-title">A structure that would work</div>
          <div className="refusal-body">{decision.customer.counterfactual}</div>
        </div>
      ) : null}

      <div style={{ marginTop: 20 }}>
        <button className="btn btn-primary" onClick={onAgree}>
          {t(lang, "agree")}
        </button>
        <button className="btn" onClick={onDecline}>
          {t(lang, "not_now")}
        </button>
        <button className="btn btn-quiet">{t(lang, "disagree")}</button>
        <p className="note" style={{ textAlign: "center" }}>
          {t(lang, "human_review")}
        </p>
      </div>
    </div>
  );
}
