import { useState } from "react";
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
 * A picture only informs someone who can read it, so the screen now says three
 * things before the chart: what affordability means here, why it is drawn as a
 * projection rather than scored as a ratio, and how to read the reader's own two
 * lines. Without those the chart is decoration, and consent given against
 * decoration is not informed consent.
 *
 * There is no countdown, no pre-ticked box and no "recommended" styling on the
 * agree button over the decline button.
 */
export function Affordability({
  lang,
  decision,
  onAgree,
  onDecline,
  onDispute,
  onStartRequest,
}: {
  lang: Lang;
  decision: DecisionResponse;
  onAgree: () => void;
  onDecline: () => void;
  onDispute: () => void;
  onStartRequest: () => void;
}) {
  const [acknowledgement, setAcknowledgement] = useState<string | null>(null);
  const twin = decision.twin;
  const offer = decision.offer;

  // Every action on this screen acts on a specific proposed repayment. Offering
  // "I agree" when there is nothing to agree to was how the journey reached a
  // Key Facts screen announcing it had nothing to say.
  const hasProposal = Boolean(offer);

  if (!twin) {
    return (
      <div className="screen">
        <h1>{t(lang, "affordability")}</h1>
        <div className="surface-card" style={{ marginTop: 12 }}>
          <h3>{t(lang, "afford_no_obligation_title")}</h3>
          <p className="lede" style={{ marginBottom: 14 }}>
            {t(lang, "afford_no_obligation_body")}
          </p>
          <button className="btn btn-primary" onClick={onStartRequest}>
            {t(lang, "kfs_none_action")} <span aria-hidden="true">→</span>
          </button>
        </div>
      </div>
    );
  }

  const buffer = twin.safe_buffer_paise;
  const lowest = twin.lowest_projected;
  const clears = twin.verdict === "AFFORDABLE";
  const fragile = twin.verdict === "FRAGILE";

  return (
    <div className="screen">
      <h1>{t(lang, "affordability")}</h1>

      <section className="explainer-grid">
        <article className="explainer-card">
          <span className="card-kicker">1</span>
          <h3>{t(lang, "afford_what_title")}</h3>
          <p>{t(lang, "afford_what_body")}</p>
        </article>
        <article className="explainer-card">
          <span className="card-kicker">2</span>
          <h3>{t(lang, "afford_why_graph_title")}</h3>
          <p>{t(lang, "afford_why_graph_body")}</p>
        </article>
        <article className="explainer-card">
          <span className="card-kicker">3</span>
          <h3>{t(lang, "afford_read_title")}</h3>
          <ul className="explainer-list">
            <li>{t(lang, "afford_read_1")}</li>
            <li>{t(lang, "afford_read_2")}</li>
            <li>{t(lang, "afford_read_3")}</li>
          </ul>
        </article>
      </section>

      {!hasProposal ? (
        <p className="lede">{t(lang, "afford_no_obligation_body")}</p>
      ) : null}

      <TwinChart
        pathWith={twin.path_with}
        pathWithout={twin.path_without}
        pathP05={twin.path_p05}
        pathDays={twin.path_days}
        horizonDays={twin.horizon_days || 180}
        safeBufferPaise={buffer}
      />

      <div className={`verdict-card verdict-${twin.verdict.toLowerCase()}`}>
        <span className="card-kicker">{t(lang, "afford_verdict")}</span>
        <h3>{twin.sentence}</h3>
        <p>
          {clears
            ? t(lang, "afford_clears")
            : fragile
              ? t(lang, "afford_fragile")
              : t(lang, "afford_breaches")}
        </p>
        <div className="verdict-figures">
          <div>
            <span>{t(lang, "afford_lowest")}</span>
            <strong>{lowest}</strong>
          </div>
          <div>
            <span>{t(lang, "safe_buffer")}</span>
            <strong>{twin.safe_buffer}</strong>
          </div>
          <div>
            <span>{t(lang, "afford_shocks")}</span>
            <strong>{twin.shocks_absorbed}</strong>
          </div>
        </div>
        {/* Without this line the card contradicts itself: every stress test
            below can pass while this reads zero, because they measure
            different things — one setback applied to a normal month, against
            income failing repeatedly. */}
        <p className="note" style={{ marginTop: 10, marginBottom: 0 }}>
          {t(lang, "afford_shocks_note")}
        </p>
      </div>

      <h2>{t(lang, "afford_scenarios")}</h2>
      {twin.scenarios.map((s) => (
        <div className="kfs-row" key={s.key}>
          <span className="kfs-label">{s.label}</span>
          <span
            className="kfs-value"
            style={{ color: s.passed ? "var(--good)" : "var(--critical)" }}
          >
            {s.passed ? t(lang, "afford_stays_above") : t(lang, "afford_falls_below")}
          </span>
        </div>
      ))}

      {decision.customer.counterfactual ? (
        <div className="refusal" style={{ marginTop: 16 }}>
          <div className="refusal-title">{t(lang, "afford_structure_works")}</div>
          <div className="refusal-body">{decision.customer.counterfactual}</div>
        </div>
      ) : null}

      <div className="affordability-actions">
        {hasProposal ? (
          <>
            <div className="affordability-button-row">
              <button
                className="btn btn-primary"
                onClick={() => {
                  setAcknowledgement(t(lang, "agree_recorded"));
                  onAgree();
                }}
              >
                {t(lang, "agree")}
              </button>
              <button
                className="btn"
                onClick={() => {
                  setAcknowledgement(t(lang, "not_now_recorded"));
                  onDecline();
                }}
              >
                {t(lang, "not_now")}
              </button>
              <button
                className="btn btn-quiet"
                onClick={() => {
                  setAcknowledgement(t(lang, "disagree_recorded"));
                  onDispute();
                }}
              >
                {t(lang, "disagree")}
              </button>
            </div>
            <p className="note affordability-review-note">{t(lang, "disagree_help")}</p>
          </>
        ) : (
          <div className="affordability-button-row">
            <button className="btn btn-primary" onClick={onStartRequest}>
              {t(lang, "kfs_none_action")} <span aria-hidden="true">→</span>
            </button>
          </div>
        )}

        {acknowledgement ? (
          <p className="action-ack" role="status">
            {acknowledgement}
          </p>
        ) : (
          <p className="note affordability-review-note">{t(lang, "human_review")}</p>
        )}
      </div>
    </div>
  );
}
