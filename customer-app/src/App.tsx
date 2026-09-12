import { useCallback, useEffect, useState } from "react";
import { api, type CustomerRow, type DecisionResponse } from "./api";
import { LANGUAGES, t, type Lang } from "./i18n";
import { Affordability } from "./screens/Affordability";
import { Assistant } from "./screens/Assistant";
import { Home } from "./screens/Home";
import { KeyFacts } from "./screens/KeyFacts";
import { Privacy } from "./screens/Privacy";

type Tab = "home" | "assistant" | "twin" | "kfs" | "privacy";

const TABS: { id: Tab; glyph: string; key: string }[] = [
  { id: "home", glyph: "◉", key: "your_money" },
  { id: "assistant", glyph: "🎙", key: "tap_to_speak" },
  { id: "twin", glyph: "◪", key: "affordability" },
  { id: "kfs", glyph: "▤", key: "key_facts" },
  { id: "privacy", glyph: "◈", key: "privacy" },
];

export default function App() {
  const [lang, setLang] = useState<Lang>("hi");
  const [tab, setTab] = useState<Tab>("home");
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [token, setToken] = useState<string>("");
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [safetyPhrase, setSafetyPhrase] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ customers: CustomerRow[] }>("/banker/customers")
      .then((r) => {
        setCustomers(r.customers);
        if (r.customers.length > 0) setToken(r.customers[0].customer_token);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const refresh = useCallback(() => {
    if (!token) return;
    api
      .post<DecisionResponse>("/decide", { customer_token: token, language: lang })
      .then(setDecision)
      .catch((e) => setError(String(e)));
  }, [token, lang]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    if (!token) return;
    api
      .post<{ banner: { safety_phrase: string } }>("/journey/start", {
        customer_token: token,
        language: lang,
      })
      .then((s) => setSafetyPhrase(s.banner.safety_phrase))
      .catch(() => setSafetyPhrase(""));
  }, [token, lang]);

  function speak(text: string) {
    // Browser speech synthesis stands in for the Bhashini TTS adapter in the
    // demo. In deployment the audio comes from an in-country endpoint.
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang === "en" ? "en-IN" : `${lang}-IN`;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    }
  }

  return (
    <div className="stage">
      <div className="phone">
        <div className="topbar">
          <span className="wordmark">ARTHA</span>
          <div className="lang-row">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                className="lang-btn"
                aria-pressed={lang === l.code}
                onClick={() => setLang(l.code)}
              >
                {l.native}
              </button>
            ))}
          </div>
        </div>

        <div className="safety">
          <span aria-hidden="true">🔒</span>
          <span>
            <strong>{t(lang, "safety_phrase")}:</strong> {safetyPhrase || "…"} ·{" "}
            {t(lang, "never_ask")}
          </span>
        </div>

        {customers.length > 1 ? (
          <div style={{ padding: "10px 18px 0" }}>
            <label className="note" htmlFor="who">
              Demo customer:
            </label>
            <select
              id="who"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              style={{
                width: "100%",
                marginTop: 4,
                padding: 9,
                borderRadius: 10,
                border: "1px solid var(--border)",
                background: "var(--card-2)",
                color: "var(--ink)",
                font: "inherit",
                fontSize: 14,
              }}
            >
              {customers.map((c) => (
                <option key={c.customer_token} value={c.customer_token}>
                  {c.customer_token.replace(/^tok_/, "")} — {c.income_type.toLowerCase()}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        {error ? (
          <div className="screen">
            <p className="error">{error}</p>
            <p className="note">
              Is the decision service running? <code>uvicorn artha.main:app --reload</code>
            </p>
          </div>
        ) : !decision ? (
          <div className="loading">…</div>
        ) : tab === "home" ? (
          <Home
            lang={lang}
            decision={decision}
            onOpenOffer={() => setTab("kfs")}
            onOpenTwin={() => setTab("twin")}
          />
        ) : tab === "assistant" ? (
          <Assistant lang={lang} />
        ) : tab === "twin" ? (
          <Affordability
            lang={lang}
            decision={decision}
            onAgree={() => setTab("kfs")}
            onDecline={() => setTab("home")}
          />
        ) : tab === "kfs" ? (
          <KeyFacts lang={lang} decision={decision} onSpeak={speak} />
        ) : (
          <Privacy lang={lang} token={token} decision={decision} onChanged={refresh} />
        )}

        <nav className="tabbar">
          {TABS.map((tb) => (
            <button
              key={tb.id}
              className="tab"
              aria-current={tab === tb.id ? "page" : undefined}
              onClick={() => setTab(tb.id)}
            >
              <span className="tab-glyph" aria-hidden="true">
                {tb.glyph}
              </span>
              {t(lang, tb.key)}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
