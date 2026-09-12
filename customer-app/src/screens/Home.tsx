import type { DecisionResponse } from "../api";
import { t, type Lang } from "../i18n";

/** The personalised dashboard.
 *
 * Two things sit side by side here, and the second is the unusual one: what the
 * bank is offering, and a permanent panel showing **what it is not offering and
 * why** (report §6.6). A refusal the customer can read is simultaneously a
 * refusal, a piece of financial education and a reason to trust the next offer.
 */
export function Home({
  lang,
  decision,
  onOpenOffer,
  onOpenTwin,
}: {
  lang: Lang;
  decision: DecisionResponse;
  onOpenOffer: () => void;
  onOpenTwin: () => void;
}) {
  const inRecovery = decision.recovery_state !== "STABLE";

  return (
    <div className="screen">
      <h1>{t(lang, "your_money")}</h1>

      {decision.twin ? (
        <div className="balance-card">
          <div className="balance-label">{t(lang, "safe_buffer")}</div>
          <div className="balance-value">{decision.twin.safe_buffer}</div>
          <div className="balance-sub">{decision.twin.sentence}</div>
        </div>
      ) : null}

      {inRecovery ? (
        <div className="refusal" style={{ borderLeftColor: "var(--series-1)" }}>
          <div className="refusal-title">{t(lang, "recovery_title")}</div>
          <div className="refusal-body">{t(lang, "recovery_body")}</div>
        </div>
      ) : null}

      <div className="spoken">{decision.customer.spoken || decision.customer.headline}</div>

      {decision.offer ? (
        <>
          <h2>{t(lang, "what_we_offer")}</h2>
          <div className="offer">
            <div className="offer-name">{decision.offer.product_name}</div>
            <div className="offer-amount">{decision.offer.amount}</div>
            <div className="offer-terms">
              {decision.offer.emi} × {decision.offer.tenure_months} · due on the{" "}
              {decision.offer.day_of_month}
            </div>
            {decision.offer.reduced_from_eligibility ? (
              <div className="offer-eligible">
                You are eligible for <strong>{decision.offer.eligible_amount}</strong>. We
                recommend <strong>{decision.offer.amount}</strong>, because that is what your cash
                flow carries comfortably.
              </div>
            ) : null}
          </div>
          <button className="btn btn-primary" onClick={onOpenTwin}>
            {t(lang, "affordability")}
          </button>
          <button className="btn" onClick={onOpenOffer}>
            {t(lang, "key_facts")}
          </button>
        </>
      ) : (
        <>
          <h2>{t(lang, "nothing_today")}</h2>
          <p className="note">{t(lang, "nothing_today_body")}</p>
        </>
      )}

      <h2>{t(lang, "what_we_dont")}</h2>
      {decision.suppressed_candidates.length === 0 && !decision.customer.counterfactual ? (
        <p className="note">Nothing is currently being withheld from you.</p>
      ) : null}

      {decision.customer.counterfactual ? (
        <div className="refusal">
          <div className="refusal-title">{decision.customer.headline}</div>
          <div className="refusal-body">{decision.customer.counterfactual}</div>
        </div>
      ) : null}

      {decision.suppressed_candidates.map((s, i) => (
        <div className="refusal" key={i}>
          <div className="refusal-title">{s.product_id.replace(/_/g, " ")}</div>
          <div className="refusal-body">{s.reason}</div>
        </div>
      ))}

      {decision.intervention?.recommended ? (
        <>
          <h2>{t(lang, "recovery_title")}</h2>
          <div className="refusal" style={{ borderLeftColor: "var(--good)" }}>
            <div className="refusal-title">{decision.intervention.recommended.name}</div>
            <div className="refusal-body">
              {decision.intervention.recommended.customer_sentence}
            </div>
          </div>
          <button className="btn btn-quiet">{t(lang, "talk_to_person")}</button>
        </>
      ) : null}

      <p className="note" style={{ marginTop: 22 }}>
        {decision.data_provenance}
      </p>
    </div>
  );
}
