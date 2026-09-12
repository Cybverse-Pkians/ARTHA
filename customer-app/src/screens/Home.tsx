import { useState } from "react";
import type { DecisionResponse } from "../api";
import { t, type Lang } from "../i18n";

/** A customer view of the exact same Decision Object seen by the banker. */
export function Home({
  lang,
  decision,
  onOpenOffer,
  onOpenTwin,
  onInterventionResponse,
}: {
  lang: Lang;
  decision: DecisionResponse;
  onOpenOffer: () => void;
  onOpenTwin: () => void;
  onInterventionResponse: (accepted: boolean) => Promise<void>;
}) {
  const [interventionResponse, setInterventionResponse] = useState<string | null>(null);
  const inRecovery = decision.recovery_state !== "STABLE";
  const offer = decision.offer;

  async function respond(accepted: boolean) {
    await onInterventionResponse(accepted);
    setInterventionResponse(
      accepted
        ? "Your preference has been recorded. The support team can continue with this option."
        : "That is okay. Saying no is never recorded as a risk signal.",
    );
  }

  return (
    <div className="screen home-screen">
      <div className="decision-banner">
        <div className="decision-banner-copy">
          <span className="card-kicker">Your ARTHA answer</span>
          <h3>{decision.customer.spoken || decision.customer.headline}</h3>
          <p>{decision.customer.detail}</p>
        </div>
        {decision.twin ? (
          <div className="buffer-snapshot">
            <span>{t(lang, "safe_buffer")}</span>
            <strong>{decision.twin.safe_buffer}</strong>
            <small>kept aside in your plan</small>
          </div>
        ) : null}
      </div>

      {inRecovery ? (
        <div className="recovery-callout">
          <span className="callout-icon" aria-hidden="true">♡</span>
          <div>
            <strong>{t(lang, "recovery_title")}</strong>
            <p>{t(lang, "recovery_body")}</p>
          </div>
        </div>
      ) : null}

      <div className="home-grid">
        <section className="surface-card offer-card">
          <div className="card-title-row">
            <div>
              <span className="card-kicker">{offer ? t(lang, "what_we_offer") : t(lang, "nothing_today")}</span>
              <h3>{offer ? offer.product_name : "No new obligation today"}</h3>
            </div>
            <span className="card-symbol" aria-hidden="true">₹</span>
          </div>

          {offer ? (
            <>
              <div className="offer-amount">{offer.amount}</div>
              <div className="offer-terms">
                <span>{offer.emi} / month</span>
                <i />
                <span>{offer.tenure_months} months</span>
                <i />
                <span>due on {offer.day_of_month}</span>
              </div>
              {offer.reduced_from_eligibility ? (
                <div className="offer-explanation">
                  You could qualify for <strong>{offer.eligible_amount}</strong>. We recommend
                  <strong> {offer.amount}</strong> because it stays within the cash flow your plan can carry.
                </div>
              ) : null}
              <div className="card-actions">
                <button className="btn btn-primary" onClick={onOpenTwin}>Check affordability <span>→</span></button>
                <button className="btn btn-secondary" onClick={onOpenOffer}>Read key facts</button>
              </div>
            </>
          ) : (
            <>
              <p className="empty-copy">{t(lang, "nothing_today_body")}</p>
              <button className="btn btn-secondary" onClick={onOpenTwin}>See your cash-flow view</button>
            </>
          )}
        </section>

        <section className="surface-card clarity-card">
          <span className="card-kicker">Why this answer</span>
          <h3>Clear, not just convenient.</h3>
          <div className="clarity-list">
            <div><span className="clarity-mark">1</span><p>We test a repayment against your projected balance—not a generic score.</p></div>
            <div><span className="clarity-mark">2</span><p>We show the offer and everything deliberately not offered, with the reason.</p></div>
            <div><span className="clarity-mark">3</span><p>You see the total cost and your data choices before you continue.</p></div>
          </div>
        </section>
      </div>

      <section className="withheld-section">
        <div className="subsection-head">
          <div>
            <span className="card-kicker">{t(lang, "what_we_dont")}</span>
            <h3>What we are protecting you from</h3>
          </div>
          <span className="transparent-label">Always explained</span>
        </div>

        {decision.customer.counterfactual ? (
          <article className="withheld-card counterfactual-card">
            <span className="withheld-mark" aria-hidden="true">↗</span>
            <div>
              <strong>A structure that could work</strong>
              <p>{decision.customer.counterfactual}</p>
            </div>
          </article>
        ) : null}

        {decision.suppressed_candidates.map((candidate) => (
          <article className="withheld-card" key={`${candidate.product_id}-${candidate.reason}`}>
            <span className="withheld-mark" aria-hidden="true">−</span>
            <div>
              <strong>{candidate.product_id.replace(/_/g, " ")}</strong>
              <p>{candidate.reason}</p>
            </div>
          </article>
        ))}

        {decision.suppressed_candidates.length === 0 && !decision.customer.counterfactual ? (
          <div className="nothing-withheld">Nothing is currently being withheld from you.</div>
        ) : null}
      </section>

      {decision.intervention?.recommended ? (
        <section className="support-card">
          <div>
            <span className="card-kicker">Support before stress becomes a problem</span>
            <h3>{decision.intervention.recommended.name}</h3>
            <p>{decision.intervention.recommended.customer_sentence}</p>
            {decision.intervention.recommended.new_emi ? (
              <span className="support-detail">New payment: {decision.intervention.recommended.new_emi}</span>
            ) : null}
          </div>
          <div className="support-actions">
            <button className="btn btn-primary" onClick={() => void respond(true)}>Choose this support</button>
            <button className="btn btn-secondary" onClick={() => void respond(false)}>Not now</button>
          </div>
          {interventionResponse ? <p className="response-note">{interventionResponse}</p> : null}
        </section>
      ) : null}

      <p className="provenance-note">{decision.data_provenance}</p>
    </div>
  );
}
