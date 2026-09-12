import { useState } from "react";
import { api } from "../api";
import { t, type Lang } from "../i18n";

interface SlotResponse {
  slot: string;
  value: number | null;
  confidence: number;
  needs_reask: boolean;
  reask_prompt: string;
  read_back: string;
  code_mixed: boolean;
  note: string;
}

/** The voice assistant.
 *
 * The customer types nothing and only confirms. Two behaviours here are the
 * point rather than the polish:
 *
 *  - **Confidence gating.** Below the threshold the assistant re-asks instead of
 *    guessing, and any large amount is read back regardless of confidence —
 *    ₹1,00,000 misheard as ₹10,00,000 is an unacceptable failure mode.
 *  - **Code-mixing is normal.** "Mujhe ek lakh ka loan chahiye" is how people
 *    actually speak to a bank, and it is handled as a first-class case rather
 *    than as a recognition error.
 *
 * The text box exists because this is a demo without a microphone. In the real
 * journey the customer speaks and never sees it.
 */
export function Assistant({ lang }: { lang: Lang }) {
  const [utterance, setUtterance] = useState("mujhe ek lakh ka loan chahiye");
  const [listening, setListening] = useState(false);
  const [result, setResult] = useState<SlotResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(text: string, confidence: number) {
    setError(null);
    try {
      const r = await api.post<SlotResponse>("/journey/slot", {
        text,
        asr_confidence: confidence,
        language: lang,
        slot: "AMOUNT",
      });
      setResult(r);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="screen">
      <h1>{t(lang, "tap_to_speak")}</h1>
      <p className="lede">
        Say what you need in your own words. You will not have to type anything, and the
        application fills itself in.
      </p>

      <div className="mic">
        <button
          className="mic-btn"
          aria-pressed={listening}
          aria-label={t(lang, "tap_to_speak")}
          onClick={() => {
            setListening(true);
            void send(utterance, 0.93).finally(() => setListening(false));
          }}
        >
          🎙
        </button>
        <div className="mic-hint">{listening ? t(lang, "listening") : t(lang, "tap_to_speak")}</div>
      </div>

      <label className="note" htmlFor="utterance">
        Demo only — the real journey has no text box:
      </label>
      <input
        id="utterance"
        value={utterance}
        onChange={(e) => setUtterance(e.target.value)}
        style={{
          width: "100%",
          padding: 12,
          borderRadius: 12,
          border: "1px solid var(--border)",
          background: "var(--card-2)",
          color: "var(--ink)",
          font: "inherit",
          marginBottom: 12,
        }}
      />

      <div className="channel-strip">
        <button className="btn btn-quiet" style={{ margin: 0 }} onClick={() => void send(utterance, 0.45)}>
          Simulate a noisy line (low confidence)
        </button>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {result ? (
        <>
          <div className="transcript">
            <div className="transcript-role">Heard</div>
            {utterance}
            {result.code_mixed ? (
              <div style={{ marginTop: 6 }}>
                <span className="pill">code-mixed — handled, not rejected</span>
              </div>
            ) : null}
          </div>

          <div className="transcript">
            <div className="transcript-role">Assistant</div>
            {result.needs_reask && result.reask_prompt ? result.reask_prompt : result.read_back}
          </div>

          <div className="kfs-row">
            <span className="kfs-label">Understood amount</span>
            <span className="kfs-value">
              {result.value === null
                ? "—"
                : new Intl.NumberFormat("en-IN", {
                    style: "currency",
                    currency: "INR",
                    maximumFractionDigits: 0,
                  }).format(result.value / 100)}
            </span>
          </div>
          <div className="kfs-row">
            <span className="kfs-label">Confidence</span>
            <span className="kfs-value">{(result.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="kfs-row">
            <span className="kfs-label">Confirm before acting</span>
            <span className="kfs-value">{result.needs_reask ? "Yes" : "No"}</span>
          </div>

          <p className="note" style={{ marginTop: 12 }}>
            {result.note}
          </p>
        </>
      ) : null}
    </div>
  );
}
