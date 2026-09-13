import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { t, type Lang } from "../i18n";

/** Minimal shape of the browser speech-recognition API.
 *
 * Typed locally rather than pulled from lib.dom: the interface is still vendor
 * prefixed in most browsers, so the app has to feature-detect it at runtime
 * anyway and a declaration here keeps that check honest.
 */
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: { 0: { 0: { transcript: string }; }; length: number }[] & { [k: number]: { 0: { transcript: string } } } }) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
}

type RecognitionCtor = new () => SpeechRecognitionLike;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const BCP47: Record<Lang, string> = {
  hi: "hi-IN",
  en: "en-IN",
  mr: "mr-IN",
  ta: "ta-IN",
  bn: "bn-IN",
};

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
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<SlotResponse | null>(null);
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const recogniser = useRef<SpeechRecognitionLike | null>(null);
  const supportsSpeech = recognitionCtor() !== null;

  // Stop the microphone if the customer navigates away mid-utterance. A
  // recogniser left running after its screen is gone keeps the mic indicator
  // lit, which on a bank app reads as the app listening to you in secret.
  useEffect(() => () => recogniser.current?.stop(), []);

  async function send(confidence: number, text?: string) {
    const spoken = (text ?? utterance).trim();
    if (!spoken) {
      setError("Say or type what you need first.");
      return;
    }
    setError(null);
    setSending(true);
    try {
      const response = await api.post<SlotResponse>("/journey/slot", {
        text: spoken,
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
      setSending(false);
    }
  }

  /** Actually listen, where the browser can.
   *
   * The mic button previously re-sent whatever was already typed, so pressing
   * it looked like nothing happened. Where speech recognition is unavailable
   * the control now says so and points at the text box instead of pretending.
   */
  const toggleListening = useCallback(() => {
    if (listening) {
      recogniser.current?.stop();
      setListening(false);
      return;
    }
    const Ctor = recognitionCtor();
    if (!Ctor) {
      setNotice(t(lang, "voice_unsupported"));
      return;
    }
    setError(null);
    setNotice(null);
    const recognition = new Ctor();
    recogniser.current = recognition;
    recognition.lang = BCP47[lang];
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const heard = event.results[0]?.[0]?.transcript ?? "";
      if (heard) {
        setUtterance(heard);
        void send(0.93, heard);
      }
    };
    recognition.onerror = (event) => {
      setListening(false);
      setNotice(
        event.error === "not-allowed"
          ? "Microphone access was declined. Type your request below instead."
          : t(lang, "voice_unsupported"),
      );
    };
    recognition.onend = () => setListening(false);
    try {
      recognition.start();
      setListening(true);
    } catch {
      setNotice(t(lang, "voice_unsupported"));
    }
  }, [lang, listening, utterance]);

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
            className={`mic-btn${listening ? " mic-btn-live" : ""}`}
            aria-pressed={listening}
            aria-label={listening ? t(lang, "stop_listening") : t(lang, "tap_to_speak")}
            onClick={toggleListening}
          >
            <span aria-hidden="true">{listening ? "■" : "⌁"}</span>
          </button>
          <h4>{listening ? t(lang, "listening") : t(lang, "tap_to_speak")}</h4>
          <p>ARTHA understands natural, code-mixed language and reads a large amount back before anything happens.</p>
          {!supportsSpeech ? <p className="note">{t(lang, "voice_unsupported")}</p> : null}
          {notice ? <p className="note" role="status">{notice}</p> : null}
          <label className="voice-input-label" htmlFor="utterance">{t(lang, "voice_demo_transcript")}</label>
          <input id="utterance" value={utterance} onChange={(event) => setUtterance(event.target.value)} />
          <div className="voice-actions">
            <button className="btn btn-primary" disabled={sending} onClick={() => void send(0.93)}>
              {t(lang, "voice_use_request")} <span>→</span>
            </button>
            <button className="link-button" disabled={sending} onClick={() => void send(0.45)}>
              {t(lang, "voice_low_confidence")}
            </button>
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
