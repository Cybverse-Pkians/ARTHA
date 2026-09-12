import { useCallback, useEffect, useState } from "react";
import { api, type CustomerRow, type DecisionResponse } from "./api";
import { LANGUAGES, type Lang } from "./i18n";
import { Affordability } from "./screens/Affordability";
import { Assistant, type JourneySession } from "./screens/Assistant";
import { Home } from "./screens/Home";
import { KeyFacts } from "./screens/KeyFacts";
import { Privacy } from "./screens/Privacy";

type Tab = "home" | "twin" | "assistant" | "kfs" | "privacy";

const TABS: { id: Tab; label: string }[] = [
  { id: "home", label: "Overview" },
  { id: "twin", label: "Affordability" },
  { id: "assistant", label: "Voice guide" },
  { id: "kfs", label: "Key facts" },
  { id: "privacy", label: "Data & privacy" },
];

const SCENARIO_BADGES: Record<string, { tag: string; color: string }> = {
  tok_salaried_stable: { tag: "ACT", color: "#14835d" },
  tok_gig: { tag: "SUPPRESS", color: "#bd7712" },
  tok_gig_worker: { tag: "SUPPRESS", color: "#bd7712" },
  tok_stressed: { tag: "PROTECT", color: "#c74055" },
  tok_stressed_salaried: { tag: "PROTECT", color: "#c74055" },
  tok_salaried_stressed: { tag: "PROTECT", color: "#c74055" },
  tok_seasonal: { tag: "SUPPRESS", color: "#bd7712" },
  tok_rural_farmer: { tag: "ACT", color: "#14835d" },
  tok_pensioner: { tag: "ACT", color: "#14835d" },
  tok_nri: { tag: "ACT", color: "#14835d" },
  tok_self_employed: { tag: "ACT", color: "#14835d" },
  tok_new_to_credit: { tag: "VERIFY", color: "#5848b0" },
  tok_recovery: { tag: "PROTECT", color: "#c74055" },
  tok_injection: { tag: "VERIFY", color: "#5848b0" },
};

export default function App() {
  const [lang, setLang] = useState<Lang>("hi");
  const [tab, setTab] = useState<Tab>("home");
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [token, setToken] = useState("");
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [journey, setJourney] = useState<JourneySession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showWelcome, setShowWelcome] = useState(true);

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
    api
      .post<DecisionResponse>("/decide", { customer_token: token, language: lang })
      .then(setDecision)
      .catch((reason) => setError(String(reason)));
  }, [token, lang]);

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

  const activeLabel = TABS.find((item) => item.id === tab)?.label ?? "Overview";

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
            </p>
            <div className="welcome-actions">
              <button className="welcome-start-btn" onClick={() => setShowWelcome(false)}>
                Start Demo
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <header className="site-header">
        <div className="utility-bar">
          <span>ARTHA · Suitability-first lending</span>
          <span>Every figure in this experience is illustrative</span>
        </div>
        <div className="header-main">
          <button className="brand" onClick={() => setTab("home")} aria-label="ARTHA home">
            <span className="brand-mark" aria-hidden="true">A</span>
            <span>
              <strong>ARTHA</strong>
              <small>banking that stays human</small>
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
                {item.label}
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
            <div className="eyebrow"><span className="eyebrow-dot" /> Your financial wellbeing</div>
            <h1>Borrowing designed<br />around real life.</h1>
            <p>
              ARTHA checks whether a repayment fits your cash flow before it ever suggests a product.
            </p>
            <div className="hero-actions">
              <button className="hero-cta" onClick={() => setTab(decision?.twin ? "twin" : "assistant")}>
                {decision?.twin ? "See your affordability" : "Start with your needs"}
                <span aria-hidden="true">→</span>
              </button>
              <button className="hero-text-link" onClick={() => setTab("privacy")}>How your data is used</button>
            </div>
          </div>

          <div className="hero-card" aria-live="polite">
            <div className="hero-card-top">
              <span>Today&apos;s decision</span>
              <span className={`status-pill status-${(decision?.outcome ?? "loading").toLowerCase()}`}>
                {decision?.outcome ?? "Checking"}
              </span>
            </div>
            <div className="hero-card-title">{decision?.customer.headline ?? "Understanding your cash flow…"}</div>
            <p>{decision?.customer.detail ?? "We are preparing an explanation you can understand."}</p>
            {decision?.offer ? (
              <div className="hero-offer">
                <span>Structured for you</span>
                <strong>{decision.offer.amount}</strong>
                <small>{decision.offer.emi} per month · {decision.offer.tenure_months} months</small>
              </div>
            ) : (
              <div className="hero-safety-line"><span>✓</span> We will never push a product that does not fit.</div>
            )}
          </div>
        </section>

        <section className="trust-ribbon">
          <div className="trust-inner">
            <div className="safety-copy">
              <span className="lock" aria-hidden="true">⌑</span>
              <span>
                <strong>Your safety phrase:</strong> {journey?.banner?.safety_phrase ?? "Preparing…"}
                <em> · We will never ask for an OTP, PIN or CVV.</em>
              </span>
            </div>
            {customers.length > 1 ? (
              <div className="demo-scenario-picker">
                <span className="demo-picker-label">Demo scenario</span>
                <div className="demo-scenario-chips">
                  {customers.map((customer) => {
                    const name = customer.customer_token.replace(/^tok_/, "").replace(/_/g, " ");
                    const badge = SCENARIO_BADGES[customer.customer_token] ?? { tag: "Demo", color: "#4d6187" };
                    return (
                      <button
                        key={customer.customer_token}
                        className={`demo-chip${token === customer.customer_token ? " demo-chip-active" : ""}`}
                        onClick={() => setToken(customer.customer_token)}
                        aria-pressed={token === customer.customer_token}
                      >
                        <span className="demo-chip-tag" style={{ background: badge.color }}>{badge.tag}</span>
                        <span className="demo-chip-name">{name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section className="content-wrap">
          <div className="section-heading">
            <div>
              <span className="section-kicker">{activeLabel}</span>
              <h2>{tab === "home" ? "A clear answer, before you commit." : activeLabel}</h2>
            </div>
            {decision ? <span className="provenance-chip">Synthetic demo data</span> : null}
          </div>

          {error ? (
            <div className="connection-error">
              <strong>We could not reach the decision service.</strong>
              <span>{error}</span>
              <code>Start the ARTHA API at http://127.0.0.1:8000, then refresh this page.</code>
            </div>
          ) : !decision ? (
            <div className="loading-card"><span className="loading-orb" /> Preparing your ARTHA view…</div>
          ) : tab === "home" ? (
            <Home
              lang={lang}
              decision={decision}
              onOpenOffer={() => setTab("kfs")}
              onOpenTwin={() => setTab("twin")}
              onInterventionResponse={respondToIntervention}
            />
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
              onDecline={() => {
                void advanceJourney({ abandon: true });
                setTab("home");
              }}
            />
          ) : tab === "kfs" ? (
            <KeyFacts lang={lang} decision={decision} onSpeak={speak} />
          ) : (
            <Privacy lang={lang} token={token} decision={decision} onChanged={refresh} />
          )}
        </section>
      </main>

      <footer className="site-footer">
        <div>
          <span className="footer-brand">ARTHA</span>
          <span> We do not maximise how much you borrow. We maximise the chance that you keep paying.</span>
        </div>
        <span>Concept prototype · synthetic data only</span>
      </footer>
    </div>
  );
}
