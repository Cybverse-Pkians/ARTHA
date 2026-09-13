import { useCallback, useEffect, useState } from "react";
import { api, type CustomerRow, type DecisionResponse } from "./api";
import { LoanRequest } from "./components/LoanRequest";
import { ScenarioPicker, SMA_COLOUR } from "./components/ScenarioPicker";
import { LANGUAGES, LANGUAGE_COVERAGE_NOTE, t, type Lang } from "./i18n";
import { Affordability } from "./screens/Affordability";
import { Assistant, type JourneySession } from "./screens/Assistant";
import { Home } from "./screens/Home";
import { KeyFacts } from "./screens/KeyFacts";
import { Privacy } from "./screens/Privacy";

type Tab = "home" | "twin" | "assistant" | "kfs" | "privacy";

const TABS: { id: Tab; key: string }[] = [
  { id: "home", key: "nav_home" },
  { id: "twin", key: "nav_twin" },
  { id: "assistant", key: "nav_assistant" },
  { id: "kfs", key: "nav_kfs" },
  { id: "privacy", key: "nav_privacy" },
];

export default function App() {
  const [lang, setLang] = useState<Lang>("hi");
  const [tab, setTab] = useState<Tab>("home");
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [token, setToken] = useState("");
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [journey, setJourney] = useState<JourneySession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWelcome, setShowWelcome] = useState(true);
  const [showProvenance, setShowProvenance] = useState(false);
  const [requestedPaise, setRequestedPaise] = useState<number | null>(null);
  // Switching customer used to leave the previous customer's decision on screen
  // with no indication that anything was happening, for as long as the pipeline
  // took. Showing the old answer under the new name is worse than showing
  // nothing, so the decision is cleared and the wait is named.
  const [pending, setPending] = useState(false);

  useEffect(() => {
    api
      .get<{ customers: CustomerRow[] }>("/banker/customers")
      .then((response) => {
        setCustomers(response.customers);
        if (response.customers.length > 0) setToken(response.customers[0].customer_token);
      })
      .catch((reason) => setError(String(reason)));
  }, []);

  const refresh = useCallback(() => {
    if (!token) return;
    setError(null);
    setPending(true);
    api
      .post<DecisionResponse>("/decide", {
        customer_token: token,
        language: lang,
        requested_amount_paise: requestedPaise,
      })
      .then(setDecision)
      .catch((reason) => setError(String(reason)))
      .finally(() => setPending(false));
  }, [token, lang, requestedPaise]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    if (!token) return;
    api
      .post<JourneySession>("/journey/start", {
        customer_token: token,
        language: lang,
        channel: "APP",
      })
      .then(setJourney)
      .catch((reason) => setError(String(reason)));
  }, [token, lang]);

  function selectCustomer(next: string) {
    if (next === token) return;
    setDecision(null);
    setJourney(null);
    setRequestedPaise(null);
    setToken(next);
  }

  /** Rebuild the seeded demo portfolio. Demo affordance, labelled as one. */
  async function resetDemo() {
    setPending(true);
    try {
      await api.post("/banker/demo/reset", {});
      const response = await api.get<{ customers: CustomerRow[] }>("/banker/customers");
      setCustomers(response.customers);
      setRequestedPaise(null);
      setDecision(null);
      refresh();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setPending(false);
    }
  }

  const speak = useCallback(
    async (content: string) => {
      // This call keeps the browser surface on the same language-provider path
      // used in deployment. The prototype provider returns metadata only, so the
      // browser synthesiser provides an audible fallback for the live demo.
      try {
        await api.get(`/journey/tts?lang=${lang}&text=${encodeURIComponent(content)}`);
      } catch {
        // Keep the customer-facing fallback available if the provider is offline.
      }
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        const utterance = new SpeechSynthesisUtterance(content);
        utterance.lang = lang === "en" ? "en-IN" : `${lang}-IN`;
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(utterance);
      }
    },
    [lang],
  );

  async function advanceJourney(body: Record<string, unknown>) {
    if (!journey) return;
    try {
      const next = await api.post<JourneySession>("/journey/advance", {
        session_id: journey.session_id,
        ...body,
      });
      setJourney(next);
    } catch (reason) {
      setError(String(reason));
    }
  }

  async function respondToIntervention(accepted: boolean) {
    if (!decision?.intervention?.recommended || !token) return;
    try {
      await api.post("/banker/intervention-response", {
        customer_token: token,
        accepted,
        do_not_ask_again: !accepted,
        family: decision.intervention.recommended.name,
      });
      refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  /** "Not now" — recorded as a declined offer, never as a risk signal. */
  async function declineOffer() {
    if (!token || !decision?.offer) return;
    try {
      await api.post("/banker/intervention-response", {
        customer_token: token,
        accepted: false,
        do_not_ask_again: false,
        family: decision.offer.family,
      });
      void advanceJourney({ abandon: true });
      refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  /** "I disagree with this decision" — the §9.6 route to a human reviewer. */
  async function disputeDecision() {
    if (!token || !decision) return;
    try {
      await api.post("/banker/intervention-response", {
        customer_token: token,
        accepted: false,
        do_not_ask_again: false,
        family: `DISPUTE:${decision.decision_id}`,
      });
      refresh();
    } catch (reason) {
      setError(String(reason));
    }
  }

  const activeLabel = t(lang, TABS.find((item) => item.id === tab)?.key ?? "nav_home");
  const coverageNote = LANGUAGE_COVERAGE_NOTE[lang];

  return (
    <div className="site-shell">
      {showWelcome ? (
        <div className="welcome-overlay">
          <div className="welcome-modal">
            <span className="welcome-tag">Demo Mode</span>
            <h2>ARTHA Hackathon Demo</h2>
            <p>
              Welcome to ARTHA! This demo simulates an end-to-end suitability-first lending system.
              Use the <strong>Demo scenario</strong> chips below the header to switch between different customer profiles
              and see how the system adapts—from offering a safe loan, to remaining silent, to stepping in with proactive help.
              Customers carrying an <strong>SMA</strong> tag are behind on an instalment, and you can watch Recovery Mode
              activate for them.
            </p>
            <div className="welcome-actions">
              <button className="welcome-start-btn" onClick={() => setShowWelcome(false)}>
                Start Demo
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showProvenance ? (
        <div className="welcome-overlay" onClick={() => setShowProvenance(false)}>
          <div className="welcome-modal" onClick={(e) => e.stopPropagation()}>
            <span className="welcome-tag">{t(lang, "provenance_chip")}</span>
            <h2>{t(lang, "provenance_title")}</h2>
            <p>{t(lang, "provenance_body")}</p>
            {decision ? <p className="note">{decision.data_provenance}</p> : null}
            <div className="welcome-actions">
              <button className="welcome-start-btn" onClick={() => setShowProvenance(false)}>
                {t(lang, "close")}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <header className="site-header">
        <div className="utility-bar">
          <span>{t(lang, "utility_left")}</span>
          <span>{t(lang, "utility_right")}</span>
        </div>
        <div className="header-main">
          <button className="brand" onClick={() => setTab("home")} aria-label="ARTHA home">
            <span className="brand-mark" aria-hidden="true">A</span>
            <span>
              <strong>ARTHA</strong>
              <small>{t(lang, "brand_tagline")}</small>
            </span>
          </button>

          <nav className="primary-nav" aria-label="Customer journey">
            {TABS.map((item) => (
              <button
                key={item.id}
                className="nav-link"
                aria-current={tab === item.id ? "page" : undefined}
                onClick={() => setTab(item.id)}
              >
                {t(lang, item.key)}
              </button>
            ))}
          </nav>

          <div className="header-actions">
            <div className="language-picker" aria-label="Choose language">
              {LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  className="lang-btn"
                  aria-pressed={lang === language.code}
                  onClick={() => setLang(language.code)}
                >
                  {language.native}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main>
        <section className="hero-band">
          <div className="hero-content">
            <div className="eyebrow"><span className="eyebrow-dot" /> {t(lang, "hero_eyebrow")}</div>
            <h1>{t(lang, "hero_title_1")}<br />{t(lang, "hero_title_2")}</h1>
            <p>{t(lang, "hero_body")}</p>
            <div className="hero-actions">
              <button className="hero-cta" onClick={() => setTab(decision?.twin ? "twin" : "assistant")}>
                {decision?.twin ? t(lang, "hero_cta_twin") : t(lang, "hero_cta_needs")}
                <span aria-hidden="true">→</span>
              </button>
              <button className="hero-text-link" onClick={() => setTab("privacy")}>
                {t(lang, "hero_privacy_link")}
              </button>
            </div>
          </div>

          <div className="hero-card" aria-live="polite">
            <div className="hero-card-top">
              <span>{t(lang, "todays_decision")}</span>
              <span className={`status-pill status-${(decision?.outcome ?? "loading").toLowerCase()}`}>
                {decision?.outcome ?? t(lang, "checking")}
              </span>
            </div>
            <div className="hero-card-title">{decision?.customer.headline ?? t(lang, "preparing")}</div>
            <p>{decision?.customer.detail ?? t(lang, "preparing_body")}</p>
            {decision?.offer ? (
              <div className="hero-offer">
                <span>{t(lang, "structured_for_you")}</span>
                <strong>{decision.offer.amount}</strong>
                <small>
                  {decision.offer.emi} {t(lang, "per_month")} · {decision.offer.tenure_months}{" "}
                  {t(lang, "months")}
                </small>
              </div>
            ) : (
              <div className="hero-safety-line"><span>✓</span> {t(lang, "never_push")}</div>
            )}
            {decision && decision.sma_stage !== "STANDARD" ? (
              <div className="hero-arrears">
                <span
                  className="demo-chip-tag"
                  style={{ background: SMA_COLOUR[decision.sma_stage] ?? "#4d6187" }}
                >
                  {decision.sma_stage_label}
                </span>
                <small>
                  {decision.days_past_due} {t(lang, "arrears_days_past_due")} ·{" "}
                  {decision.recovery_state.replace(/_/g, " ")}
                </small>
              </div>
            ) : null}
          </div>
        </section>

        <section className="trust-ribbon">
          <div className="trust-inner">
            <div className="safety-copy">
              <span className="lock" aria-hidden="true">⌑</span>
              <span>
                <strong>{t(lang, "safety_phrase")}:</strong>{" "}
                {journey?.banner?.safety_phrase ?? "…"}
                <em> · {t(lang, "never_ask")}</em>
              </span>
            </div>
            {customers.length > 1 ? (
              <ScenarioPicker
                lang={lang}
                customers={customers}
                selected={token}
                onSelect={selectCustomer}
                onReset={() => void resetDemo()}
                busy={pending}
              />
            ) : null}
          </div>
        </section>

        <section className="content-wrap">
          <div className="section-heading">
            <div>
              <span className="section-kicker">{activeLabel}</span>
              <h2>{tab === "home" ? t(lang, "home_heading") : activeLabel}</h2>
            </div>
            <button
              type="button"
              className="provenance-chip"
              onClick={() => setShowProvenance(true)}
              aria-haspopup="dialog"
            >
              {t(lang, "provenance_chip")}
            </button>
          </div>

          {coverageNote ? <p className="note language-note">{coverageNote}</p> : null}

          {error ? (
            <div className="connection-error">
              <strong>We could not reach the decision service.</strong>
              <span>{error}</span>
              <code>Start the ARTHA API at http://127.0.0.1:8000, then refresh this page.</code>
            </div>
          ) : !decision ? (
            <div aria-busy="true">
              <div className="loading-card">
                <span className="loading-orb" />{" "}
                {pending ? t(lang, "switching") : t(lang, "loading")}
              </div>
              {/* A shape where the answer will be, rather than a blank page: the
                  pipeline takes a moment and an empty screen reads as broken. */}
              <div className="skeleton-card" style={{ marginTop: 12 }}>
                <div className="skeleton-line skeleton-line-lg" />
                <div className="skeleton-line" />
                <div className="skeleton-line skeleton-line-sm" />
              </div>
            </div>
          ) : (
            <div className="fade-in" key={`${token}:${lang}:${requestedPaise ?? "none"}`}>
              {pending ? (
                <>
                  <div className="decision-busy" role="status" aria-label={t(lang, "switching")} />
                  <p className="note language-note">{t(lang, "switching")}</p>
                </>
              ) : null}

              {tab === "home" ? (
                <>
                  <LoanRequest
                    lang={lang}
                    requestedPaise={requestedPaise}
                    onRequest={setRequestedPaise}
                    onClear={() => setRequestedPaise(null)}
                    busy={pending}
                  />
                  <Home
                    lang={lang}
                    decision={decision}
                    onOpenOffer={() => setTab("kfs")}
                    onOpenTwin={() => setTab("twin")}
                    onInterventionResponse={respondToIntervention}
                  />
                </>
              ) : tab === "assistant" ? (
                <Assistant lang={lang} session={journey} onSessionChange={setJourney} />
              ) : tab === "twin" ? (
                <Affordability
                  lang={lang}
                  decision={decision}
                  onAgree={() => {
                    void advanceJourney({ stage: "KFS_READING" });
                    setTab("kfs");
                  }}
                  onDecline={() => void declineOffer()}
                  onDispute={() => void disputeDecision()}
                  onStartRequest={() => setTab("home")}
                />
              ) : tab === "kfs" ? (
                <KeyFacts
                  lang={lang}
                  decision={decision}
                  onSpeak={speak}
                  onStartRequest={() => setTab("home")}
                />
              ) : (
                <Privacy lang={lang} token={token} decision={decision} onChanged={refresh} />
              )}
            </div>
          )}
        </section>
      </main>

      <footer className="site-footer">
        <div>
          <span className="footer-brand">ARTHA</span>
          <span> {t(lang, "footer_line")}</span>
        </div>
        <span>{t(lang, "footer_note")}</span>
      </footer>
    </div>
  );
}
