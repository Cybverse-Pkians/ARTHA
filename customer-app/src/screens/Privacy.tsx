import { useEffect, useState } from "react";
import { api, type DecisionResponse } from "../api";
import { t, type Lang } from "../i18n";

interface PurposeRow {
  purpose: string;
  label: string;
  legal_basis: string;
  withdrawable: boolean;
  live: boolean;
  days_remaining: number;
}

/** The privacy ledger.
 *
 * Report §6.6: every nudge carries an entry naming exactly which data was used,
 * which data was explicitly **not** used, when the permission expires, and a
 * one-tap revocation. Naming what was refused is the part customers find
 * credible, and it costs nothing to produce because the Gate already knows.
 *
 * Revocation here is real: the purpose goes dead in the consent manager and the
 * associated features are excluded at inference time, not merely from a policy
 * document.
 */
export function Privacy({
  lang,
  token,
  decision,
  onChanged,
}: {
  lang: Lang;
  token: string;
  decision: DecisionResponse;
  onChanged: () => void;
}) {
  const [purposes, setPurposes] = useState<PurposeRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    api
      .get<{ purposes: PurposeRow[] }>(`/journey/consent/${token}?lang=${lang}`)
      .then((r) => setPurposes(r.purposes))
      .catch((e) => setError(String(e)));
  }

  useEffect(load, [token, lang]);

  async function toggle(p: PurposeRow) {
    setBusy(p.purpose);
    setError(null);
    try {
      await api.post("/journey/consent", {
        customer_token: token,
        purpose: p.purpose,
        grant: !p.live,
      });
      load();
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const used = decision.regulator.consent.purposes_used;
  const excluded = decision.regulator.consent.purposes_excluded;

  return (
    <div className="screen">
      <h1>{t(lang, "privacy")}</h1>
      <p className="lede">{decision.customer.privacy_note}</p>

      <h2>For the message you just saw</h2>
      {used.map((p) => (
        <div className="ledger-row" key={p}>
          <span className="ledger-mark ledger-used">✓</span>
          <span>
            <strong>{t(lang, "data_used")}</strong> — {p.replace(/_/g, " ").toLowerCase()}
          </span>
        </div>
      ))}
      {excluded.slice(0, 6).map((p) => (
        <div className="ledger-row" key={p}>
          <span className="ledger-mark ledger-unused">✕</span>
          <span className="note" style={{ fontSize: 14 }}>
            <strong>{t(lang, "data_not_used")}</strong> — {p.replace(/_/g, " ").toLowerCase()}
          </span>
        </div>
      ))}

      <h2>What you have turned on</h2>
      {error ? <p className="error">{error}</p> : null}
      {purposes.map((p) => (
        <div key={p.purpose} style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
            <div>
              <div style={{ fontWeight: 600, fontSize: 14.5 }}>{p.label}</div>
              <div className="note">
                {p.live ? `Expires in ${p.days_remaining} days` : "Off"} ·{" "}
                {p.withdrawable ? "you can turn this off" : "required to run your account"}
              </div>
            </div>
            <button
              className="lang-btn"
              disabled={!p.withdrawable || busy === p.purpose}
              aria-pressed={p.live}
              onClick={() => void toggle(p)}
              style={{ alignSelf: "center", flex: "0 0 auto" }}
            >
              {p.live ? t(lang, "revoke") : "Turn on"}
            </button>
          </div>
        </div>
      ))}

      <p className="note" style={{ marginTop: 16 }}>
        We never use your contact list, your location, your social connections or any psychometric
        scoring. Turning a permission off removes that data from the next decision, not just from a
        policy document.
      </p>
    </div>
  );
}
