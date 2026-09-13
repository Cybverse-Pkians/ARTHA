import { useState } from "react";
import { t, type Lang } from "../i18n";

/** Ask the customer what they actually want to borrow.
 *
 * Report §6.2: the journey starts from a need stated in the customer's own
 * words, not from a product the bank picked. Without an input the app could only
 * ever show what the bank had decided to offer, which inverts that.
 *
 * The amount goes to the Twin as a requested principal, so the simulation tests
 * the number the customer asked for. When it does not clear, the counterfactual
 * already in the pipeline answers with the amount that would — which is why an
 * input here costs nothing in safety: asking for more cannot produce more, it
 * can only produce a more specific refusal.
 */

const MIN_RUPEES = 5_000;
const MAX_RUPEES = 20_00_000;

export function LoanRequest({
  lang,
  requestedPaise,
  onRequest,
  onClear,
  busy,
}: {
  lang: Lang;
  requestedPaise: number | null;
  onRequest: (paise: number) => void;
  onClear: () => void;
  busy: boolean;
}) {
  const [value, setValue] = useState(
    requestedPaise ? String(Math.round(requestedPaise / 100)) : "",
  );
  const [error, setError] = useState<string | null>(null);

  const parsed = Number(value.replace(/[^0-9]/g, ""));
  const valid = Number.isFinite(parsed) && parsed >= MIN_RUPEES && parsed <= MAX_RUPEES;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid) {
      setError(t(lang, "request_invalid"));
      return;
    }
    setError(null);
    onRequest(parsed * 100);
  }

  return (
    <section className="surface-card request-card">
      <span className="card-kicker">{t(lang, "what_we_offer")}</span>
      <h3>{t(lang, "request_title")}</h3>
      <p>{t(lang, "request_body")}</p>

      <form className="request-form" onSubmit={submit}>
        <label htmlFor="loan-amount">{t(lang, "request_label")}</label>
        <div className="request-input-row">
          <span className="request-prefix" aria-hidden="true">
            ₹
          </span>
          <input
            id="loan-amount"
            inputMode="numeric"
            autoComplete="off"
            placeholder="1,00,000"
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setError(null);
            }}
            aria-describedby="loan-amount-hint"
            aria-invalid={error ? true : undefined}
          />
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t(lang, "request_submit")}
          </button>
        </div>
        <p className="note" id="loan-amount-hint">
          {error ?? t(lang, "request_hint")}
        </p>
      </form>

      {requestedPaise ? (
        <div className="request-active">
          <span>
            {t(lang, "request_active")}: <strong>₹{(requestedPaise / 100).toLocaleString("en-IN")}</strong>
          </span>
          <button className="link-button" type="button" onClick={onClear} disabled={busy}>
            {t(lang, "request_clear")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
