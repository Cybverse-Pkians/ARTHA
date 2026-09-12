import { useEffect, useState } from "react";
import { api } from "../api";
import { Provenance } from "../components/Provenance";
import { StatTile } from "../components/StatTile";
import { formatPercent, titleCase } from "../components/format";

interface SuppressionReport {
  outcomes: Record<string, number>;
  suppression_rate: number;
  trend_indicator: string;
  blocking_checks: Record<string, number>;
  suppressed_by_product: Record<string, number>;
  note: string;
  product_design_feedback: string;
}

interface DualLedger {
  customer: {
    over_exposure_avoided: string;
    offers_suppressed: number;
    counterfactuals_offered: number;
    interventions_offered: number;
  };
  bank: { projected_interest_on_sustainable_lending: string };
  note: string;
}

export function Suppression() {
  const [s, setS] = useState<SuppressionReport | null>(null);
  const [ledger, setLedger] = useState<DualLedger | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<SuppressionReport>("/banker/suppression"),
      api.get<DualLedger>("/banker/dual-ledger"),
    ])
      .then(([a, b]) => {
        setS(a);
        setLedger(b);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!s || !ledger) return <p className="loading">Loading…</p>;

  const maxBlock = Math.max(1, ...Object.values(s.blocking_checks));

  return (
    <>
      <div className="page-head">
        <h1>Suppression &amp; the dual ledger</h1>
        <p>
          The number of offers the Suitability Gate suppressed is reported here as a{" "}
          <strong>success metric</strong>, with a positive trend indicator. It is the tail of
          unsuitable lending from which conduct penalties and supervisory action arise.
        </p>
      </div>
      <Provenance />

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <StatTile
          label="Offers suppressed"
          value={
            <span>
              {(s.outcomes.SUPPRESS ?? 0) + (s.outcomes.PROTECT ?? 0)}{" "}
              <span style={{ color: "var(--good)", fontSize: 17 }} aria-label="positive trend">
                ▲
              </span>
            </span>
          }
          note="A high value is the system working."
        />
        <StatTile label="Suppression rate" value={formatPercent(s.suppression_rate)} />
        <StatTile
          label="Acted on"
          value={s.outcomes.ACT ?? 0}
          note={`${s.outcomes.VERIFY ?? 0} routed to verification`}
        />
      </div>

      <div className="card">
        <h2>Which constraint blocked the offer</h2>
        {Object.entries(s.blocking_checks).length === 0 ? (
          <p className="muted small">Nothing blocked in this window.</p>
        ) : (
          Object.entries(s.blocking_checks)
            .sort((a, b) => b[1] - a[1])
            .map(([check, count]) => (
              <div key={check} style={{ marginBottom: 9 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 12.5,
                    marginBottom: 3,
                  }}
                >
                  <span>{titleCase(check)}</span>
                  <span className="mono">{count}</span>
                </div>
                <div style={{ background: "var(--surface-2)", borderRadius: 4, height: 8 }}>
                  <div
                    style={{
                      width: `${(count / maxBlock) * 100}%`,
                      background: "var(--series-1)",
                      height: 8,
                      borderRadius: 4,
                    }}
                  />
                </div>
              </div>
            ))
        )}
        <p className="small muted" style={{ marginTop: 12, marginBottom: 0 }}>
          {s.product_design_feedback}
        </p>
      </div>

      <div className="card">
        <h2>The dual ledger</h2>
        <p className="small secondary" style={{ marginTop: 0 }}>
          {ledger.note}
        </p>
        <div className="grid grid-2">
          <div>
            <h3>Value created for the customer</h3>
            <table>
              <tbody>
                <tr>
                  <th>Over-exposure avoided</th>
                  <td className="num mono">{ledger.customer.over_exposure_avoided}</td>
                </tr>
                <tr>
                  <th>Offers suppressed</th>
                  <td className="num mono">{ledger.customer.offers_suppressed}</td>
                </tr>
                <tr>
                  <th>Counterfactuals offered</th>
                  <td className="num mono">{ledger.customer.counterfactuals_offered}</td>
                </tr>
                <tr>
                  <th>Interventions offered</th>
                  <td className="num mono">{ledger.customer.interventions_offered}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <h3>Risk-adjusted value created for the bank</h3>
            <table>
              <tbody>
                <tr>
                  <th>Projected interest on sustainable lending</th>
                  <td className="num mono">
                    {ledger.bank.projected_interest_on_sustainable_lending}
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="small muted">
              A borrower pushed past capacity produces a default, a collection cost, a provisioning
              event and a lost relationship. The same borrower, structured correctly, keeps paying.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
