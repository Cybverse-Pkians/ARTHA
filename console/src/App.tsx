import { useState } from "react";
import { Arrears } from "./pages/Arrears";
import { Audit } from "./pages/Audit";
import { Explain } from "./pages/Explain";
import { Fairness } from "./pages/Fairness";
import { Queue } from "./pages/Queue";
import { Suppression } from "./pages/Suppression";

type Page = "queue" | "arrears" | "explain" | "suppression" | "fairness" | "audit";

const NAV: { id: Page; label: string }[] = [
  { id: "queue", label: "Early-warning queue" },
  { id: "arrears", label: "Arrears & SMA" },
  { id: "explain", label: "Decision explainability" },
  { id: "suppression", label: "Suppression & ledger" },
  { id: "fairness", label: "Fairness" },
  { id: "audit", label: "Audit trail" },
];

export default function App() {
  const [page, setPage] = useState<Page>("queue");
  const [token, setToken] = useState<string | null>(null);

  function openCustomer(t: string) {
    setToken(t);
    setPage("explain");
  }

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">ARTHA</div>
        <div className="brand-sub">Banker console</div>
        {NAV.map((n) => (
          <button
            key={n.id}
            className="nav-item"
            aria-current={page === n.id ? "page" : undefined}
            onClick={() => setPage(n.id)}
          >
            {n.label}
          </button>
        ))}
        <div className="brand-sub" style={{ marginTop: 26, marginBottom: 0 }}>
          Every bank can decide whether to lend. ARTHA decides how much, when, structured how — and
          when to stay silent.
        </div>
      </nav>
      <main className="main">
        {page === "queue" ? <Queue onSelect={openCustomer} /> : null}
        {page === "arrears" ? <Arrears onSelect={openCustomer} /> : null}
        {page === "explain" ? <Explain token={token} onSelect={setToken} /> : null}
        {page === "suppression" ? <Suppression /> : null}
        {page === "fairness" ? <Fairness /> : null}
        {page === "audit" ? <Audit /> : null}
      </main>
    </div>
  );
}
