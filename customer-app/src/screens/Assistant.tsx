import { useState } from "react";
import { api } from "../api";
import { t, type Lang } from "../i18n";

export interface JourneySession {
  session_id: string;
  customer_token: string;
  language: string;
  channel: string;
  stage: string;
  completed_stages: string[];
  affordability_presentation: string;
  banner: { safety_phrase: string; never_asks: string[]; notice: string };
}

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

interface PreflightResponse {
  ready: boolean;
  checks: { name: string; passed: boolean; detail: string; remedy: string }[];
  blockers: string[];
  recommendation: string;
}

/** Voice-first capture, backed by the confidence gate and journey state APIs. */
export function Assistant({
  lang,
  session,
  onSessionChange,
}: {
  lang: Lang;
  session: JourneySession | null;
  onSessionChange: (next: JourneySession) => void;
}) {
  const [utterance, setUtterance] = useState("mujhe ek lakh ka loan chahiye");
  const [listening, setListening] = useState(false);
  const [result, setResult] = useState<SlotResponse | null>(null);
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send(confidence: number) {
    setError(null);
    setListening(true);
    try {
      const response = await api.post<SlotResponse>("/journey/slot", {
        text: utterance,
        asr_confidence: confidence,
        language: lang,
        slot: "AMOUNT",
      });
      setResult(response);
      if (session) {
        const next = await api.post<JourneySession>("/journey/advance", {
          session_id: session.session_id,
          stage: "AMOUNT_CAPTURE",
        });
        onSessionChange(next);
      }
    } catch (reason) {
      setError(String(reason));
    } finally {
      setListening(false);
    }
  }

  async function runPreflight() {
    setError(null);
    try {
      const response = await api.post<PreflightResponse>("/journey/video-kyc/preflight", {
        lighting_lux: 200,
        bandwidth_kbps: 512,
        has_pan: true,
        has_aadhaar_ref: true,
        front_camera: true,
        battery_percent: 70,
      });
      setPreflight(response);
      if (session) {
        const next = await api.post<JourneySession>("/journey/advance", {
          session_id: session.session_id,
          stage: "VIDEO_KYC_PREFLIGHT",
        });
        onSessionChange(next);
      }
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function useNextChannel() {
    if (!session) return;
    setError(null);
    try {
      const next = await api.post<JourneySession>("/journey/advance", {
        session_id: session.session_id,
        degrade: true,
      });
      onSessionChange(next);
    } catch (reason) {
      setError(String(reason));
    }
  }

  return (
    <div className="screen guide-screen">
      <div className="guide-intro">
        <div>
          <span className="card-kicker">Voice-first journey</span>
          <h3>{t(lang, "tap_to_speak")}</h3>
          <p>Say what you need in your own words. ARTHA confirms important details instead of guessing.</p>
        </div>
        <div className="journey-status">
          <span>Journey stage</span>
          <strong>{session?.stage.replace(/_/g, " ") ?? "Preparing"}</strong>
        </div>
      </div>

      <div className="voice-grid">
        <section className="voice-card">
          <button
            className="mic-btn"
            aria-pressed={listening}
            aria-label={t(lang, "tap_to_speak")}
            onClick={() => void send(0.93)}
          >
            <span aria-hidden="true">⌁</span>
          </button>
          <h4>{listening ? t(lang, "listening") : "Tell us what you need"}</h4>
          <p>ARTHA understands natural, code-mixed language and reads a large amount back before anything happens.</p>
          <label className="voice-input-label" htmlFor="utterance">Demo transcript</label>
          <input id="utterance" value={utterance} onChange={(event) => setUtterance(event.target.value)} />
          <div className="voice-actions">
            <button className="btn btn-primary" onClick={() => void send(0.93)}>Use this request <span>→</span></button>
            <button className="link-button" onClick={() => void send(0.45)}>Test a low-confidence line</button>
          </div>
        </section>

        <section className="journey-card">
          <span className="card-kicker">A journey that does not give up on you</span>
          <h4>Continue even when connectivity changes.</h4>
          <p>Your progress can move from the app to a lower-bandwidth channel without making you start again.</p>
          <div className="channel-flow" aria-label="Current journey channel">
            {["APP", "WHATSAPP", "IVR", "SMS", "USSD"].map((channel, index) => (
              <span key={channel} data-active={session?.channel === channel}>
                {index > 0 ? <i aria-hidden="true">→</i> : null}{channel}
              </span>
            ))}
          </div>
          <button className="btn btn-secondary" disabled={!session || session.channel === "USSD"} onClick={() => void useNextChannel()}>
            Use the next available channel
          </button>
          {session ? <p className="channel-note">On {session.channel}, your affordability explanation is delivered as {session.affordability_presentation.replace(/_/g, " ")}.</p> : null}
        </section>
      </div>

      {error ? <p className="error">{error}</p> : null}

      {result ? (
        <section className="recognition-result">
          <div className="result-head">
            <div><span className="card-kicker">What ARTHA heard</span><h3>{result.needs_reask ? "Let’s confirm that" : "Here is what we understood"}</h3></div>
            <span className={`confidence-chip ${result.needs_reask ? "needs-confirmation" : ""}`}>{(result.confidence * 100).toFixed(0)}% confidence</span>
          </div>
          <div className="transcript-grid">
            <div><span>You said</span><strong>{utterance}</strong>{result.code_mixed ? <small>Code-mixed language recognised</small> : null}</div>
            <div><span>ARTHA says</span><strong>{result.needs_reask && result.reask_prompt ? result.reask_prompt : result.read_back}</strong><small>{result.note}</small></div>
          </div>
        </section>
      ) : null}

      <section className="kyc-card">
        <div>
          <span className="card-kicker">Before a video KYC call</span>
          <h3>Check the connection before booking time.</h3>
          <p>We test light, bandwidth, identity references, camera and battery first, so an appointment is only booked when it can work.</p>
        </div>
        <button className="btn btn-primary" onClick={() => void runPreflight()}>Run readiness check <span>→</span></button>
      </section>

      {preflight ? (
        <section className="preflight-result">
          <div className="result-head">
            <div><span className="card-kicker">Video KYC readiness</span><h3>{preflight.ready ? "You are ready to continue" : "Resolve these first"}</h3></div>
            <span className={`status-pill ${preflight.ready ? "status-act" : "status-protect"}`}>{preflight.ready ? "Ready" : "Not ready"}</span>
          </div>
          <div className="preflight-checks">
            {preflight.checks.map((check) => (
              <div className="preflight-check" key={check.name}>
                <span className={check.passed ? "check-pass" : "check-fail"}>{check.passed ? "✓" : "!"}</span>
                <div><strong>{check.name}</strong><p>{check.detail}{!check.passed && check.remedy ? ` ${check.remedy}` : ""}</p></div>
              </div>
            ))}
          </div>
          <p className="response-note">{preflight.recommendation}</p>
        </section>
      ) : null}
    </div>
  );
}
