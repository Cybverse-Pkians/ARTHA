import { useEffect, useState } from "react";
import { api, type CustomerRow, type DecisionResponse } from "../api";
import { Badge, outcomeTone, verdictTone } from "../components/Badge";
import { GateTrace, ReasonCodes } from "../components/GateTrace";
import { Provenance } from "../components/Provenance";
import { StatTile } from "../components/StatTile";
import { TwinChart } from "../components/TwinChart";
import { formatPercent, titleCase } from "../components/format";

export function Explain({
  token,
  onSelect,
}: {
  token: string | null;
  onSelect: (t: string) => void;
}) {
  const [customers, setCustomers] = useState<CustomerRow[]>([]);
  const [decision, setDecision] = useState<DecisionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api
      .get<{ customers: CustomerRow[] }>("/banker/customers")
      .then((r) => {
        setCustomers(r.customers);
        if (!token && r.customers.length > 0) onSelect(r.customers[0].customer_token);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    api
      .post<DecisionResponse>("/decide", { customer_token: token })
      .then(setDecision)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [token]);

  if (error) return <p className="error">{error}</p>;

  return (
    <>
      <div className="page-head">
        <h1>Decision explainability</h1>
        <p>
          One Decision Object, rendered twice from a single source of truth: a regulator-grade
          trace with reason codes, and one spoken sentence for the customer. Because both derive
          from the same object, what the auditor is told and what the customer is told cannot
          drift apart.
        </p>
      </div>
      <Provenance />

      <div className="btn-row">
        {customers.map((c) => (
          <button
            key={c.customer_token}
            className="btn"
            onClick={() => onSelect(c.customer_token)}
            style={
              c.customer_token === token
                ? { borderColor: "var(--series-1)", fontWeight: 600 }
                : undefined
            }
          >
            {c.customer_token.replace(/^tok_/, "")}
          </button>
        ))}
      </div>

      {loading ? <p className="loading">Running the decision pipeline…</p> : null}
      {decision ? <DecisionView d={decision} /> : null}
    </>
  );
}

function DecisionView({ d }: { d: DecisionResponse }) {
  const reg = d.regulator;
  return (
    <>
      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <StatTile
          label="Outcome"
          value={<Badge tone={outcomeTone(d.outcome)}>{d.outcome}</Badge>}
          note={
            d.outcome === "SUPPRESS"
              ? "Silence is an explicit, valid output."
              : d.outcome === "PROTECT"
                ? "Stress detected — assist, never sell."
                : d.outcome === "VERIFY"
                  ? "Step-up authentication or human review first."
                  : "Cleared every constraint."
          }
        />
        <StatTile label="Recovery state" value={titleCase(d.recovery_state)} />
        <StatTile
          label="Adverse action"
          value={d.is_adverse_action ? "Yes" : "No"}
          note={d.is_adverse_action ? "Human review required before this stands." : undefined}
        />
      </div>

      <div className="card">
        <h2>What the customer hears</h2>
        <div className="spoken">{d.customer.spoken || d.customer.headline}</div>
        {d.customer.counterfactual ? (
          <>
            <h3>Counterfactual</h3>
            <p className="secondary" style={{ margin: 0 }}>
              {d.customer.counterfactual}
            </p>
          </>
        ) : null}
        <h3>Privacy ledger</h3>
        <p className="small secondary" style={{ margin: 0 }}>
          {d.customer.privacy_note}
        </p>
      </div>

      {d.twin ? (
        <div className="card">
          <h2>Financial Twin — projected balance</h2>
          <p className="small secondary" style={{ marginTop: 0 }}>
            {d.twin.sentence}
          </p>
          <TwinChart
            pathWith={d.twin.path_with}
            pathWithout={d.twin.path_without}
            pathP05={d.twin.path_p05}
            safeBufferPaise={d.twin.safe_buffer_paise}
          />
          <div className="grid grid-3" style={{ marginTop: 12 }}>
            <StatTile
              label="Verdict"
              value={<Badge tone={verdictTone(d.twin.verdict)}>{titleCase(d.twin.verdict)}</Badge>}
            />
            <StatTile
              label="Resilience"
              value={`${d.twin.resilience_score.toFixed(0)}/100`}
              note={`Absorbs ${d.twin.shocks_absorbed} income shock(s)`}
            />
            <StatTile
              label="Breach probability"
              value={formatPercent(d.twin.breach_probability)}
              note={`Baseline without the obligation: ${formatPercent(d.twin.baseline_breach_probability)}`}
            />
          </div>
          <h3>Stress scenarios tested</h3>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Scenario</th>
                  <th>Result</th>
                  <th className="num">Breach probability</th>
                </tr>
              </thead>
              <tbody>
                {d.twin.scenarios.map((s) => (
                  <tr key={s.key}>
                    <td>{s.label}</td>
                    <td>
                      <Badge tone={s.passed ? "good" : "critical"}>
                        {s.passed ? "Clears" : "Breaches"}
                      </Badge>
                    </td>
                    <td className="num">{formatPercent(s.breach_probability)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {d.offer ? (
        <div className="card">
          <h2>Structured offer</h2>
          <div className="grid grid-3">
            <StatTile
              label="Recommended"
              value={d.offer.amount}
              note={
                d.offer.reduced_from_eligibility
                  ? `Eligible for ${d.offer.eligible_amount} — sized to Twin-safe exposure, not maximum eligibility.`
                  : undefined
              }
            />
            <StatTile
              label="EMI"
              value={d.offer.emi}
              note={`${d.offer.tenure_months} months, due on the ${d.offer.day_of_month}`}
            />
            <StatTile
              label="Total interest"
              value={d.offer.total_interest}
              note={`${(d.offer.annual_rate * 100).toFixed(2)}% p.a.`}
            />
          </div>
          <p className="small secondary" style={{ marginBottom: 0 }}>
            {d.offer.rationale}
          </p>
        </div>
      ) : null}

      {d.kfs ? (
        <div className="card">
          <h2>Key Fact Statement — read aloud before consent</h2>
          <div className="spoken">{d.kfs.spoken_script}</div>
          <h3>Tenure options, priced honestly</h3>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th className="num">Months</th>
                  <th className="num">EMI</th>
                  <th className="num">Total interest</th>
                  <th className="num">Extra vs shortest</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.kfs.tenure_options.map((t) => (
                  <tr key={t.tenure_months}>
                    <td className="num">{t.tenure_months}</td>
                    <td className="num">{t.emi}</td>
                    <td className="num">{t.total_interest}</td>
                    <td className="num">{t.additional_cost}</td>
                    <td>{t.recommended ? <Badge tone="good">Recommended</Badge> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted" style={{ marginBottom: 0 }}>
            A longer tenure lowers the monthly payment and raises the total cost. Both halves of
            that sentence are spoken before consent is taken.
          </p>
        </div>
      ) : null}

      {d.sentinel ? (
        <div className="card">
          <h2>Sentinel</h2>
          <div className="grid grid-3">
            <StatTile
              label="Verdict"
              value={<Badge tone={verdictTone(d.sentinel.verdict)}>{titleCase(d.sentinel.verdict)}</Badge>}
            />
            <StatTile label="PD uplift (90d)" value={`+${formatPercent(d.sentinel.pd_uplift_90d)}`} />
            <StatTile
              label="Ability vs willingness"
              value={titleCase(d.sentinel.pay_intent)}
              note={
                d.sentinel.pay_intent === "UNWILLING"
                  ? "Forbearance withheld; capacity to pay appears intact."
                  : undefined
              }
            />
          </div>
          <h3>Evidence</h3>
          <ul className="small secondary" style={{ margin: 0, paddingLeft: 18 }}>
            {d.sentinel.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
          {d.sentinel.fraud_signals.length > 0 ? (
            <>
              <h3>Fraud signals</h3>
              <div className="scroll-x">
                <table>
                  <thead>
                    <tr>
                      <th>Pattern</th>
                      <th>Detection</th>
                      <th>Response</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.sentinel.fraud_signals.map((f) => (
                      <tr key={f.pattern}>
                        <td>{titleCase(f.pattern)}</td>
                        <td className="small secondary">{f.description}</td>
                        <td className="small">{f.response}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {d.intervention ? (
        <div className="card">
          <h2>Intervention Ladder</h2>
          {d.intervention.recommended ? (
            <>
              <div className="reason reason-favourable">
                <div className="reason-code">Rung {d.intervention.recommended.rung}</div>
                <div className="reason-title">{d.intervention.recommended.name}</div>
                <div className="reason-desc">{d.intervention.recommended.description}</div>
              </div>
              <p className="small secondary">
                <strong>Regulatory cost:</strong> {d.intervention.recommended.regulatory_cost}
              </p>
              <p className="small secondary">
                <strong>Economic cost:</strong> {d.intervention.recommended.economic_cost}
              </p>
              <h3>Alternatives considered</h3>
              <div className="scroll-x">
                <table>
                  <thead>
                    <tr>
                      <th className="num">Rung</th>
                      <th>Intervention</th>
                      <th className="num">Economic cost</th>
                      <th>Regulatory treatment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.intervention.alternatives.map((a) => (
                      <tr key={a.rung}>
                        <td className="num">{a.rung}</td>
                        <td>{a.name}</td>
                        <td className="num">{a.economic_cost}</td>
                        <td className="small secondary">{a.regulatory_cost}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="secondary" style={{ margin: 0 }}>
              {d.intervention.withheld_reason}
            </p>
          )}
        </div>
      ) : null}

      <div className="card">
        <h2>Gate trace</h2>
        <GateTrace trace={reg.gate_trace} />
      </div>

      <div className="card">
        <h2>Reason codes</h2>
        <ReasonCodes codes={reg.reason_codes} />
      </div>

      {d.suppressed_candidates.length > 0 ? (
        <div className="card">
          <h2>What we are not offering, and why</h2>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Blocking check</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {d.suppressed_candidates.map((s, i) => (
                  <tr key={i}>
                    <td className="mono">{s.product_id}</td>
                    <td className="small">{s.blocking_check ?? "—"}</td>
                    <td className="small secondary">{s.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <div className="card">
        <h2>Provenance and audit</h2>
        <table>
          <tbody>
            <tr>
              <th>Decision id</th>
              <td className="mono">{reg.decision_id}</td>
            </tr>
            <tr>
              <th>Created</th>
              <td className="mono">{reg.created_at}</td>
            </tr>
            <tr>
              <th>Policy version</th>
              <td className="mono">{reg.policy_version}</td>
            </tr>
            <tr>
              <th>Input hash</th>
              <td className="mono">{reg.input_hash.slice(0, 32)}…</td>
            </tr>
            <tr>
              <th>Model versions</th>
              <td className="mono">
                {Object.entries(reg.model_versions)
                  .map(([k, v]) => `${k}=${v}`)
                  .join("  ")}
              </td>
            </tr>
            <tr>
              <th>Consent used</th>
              <td className="small">{reg.consent.purposes_used.join(", ") || "—"}</td>
            </tr>
            <tr>
              <th>Consent excluded</th>
              <td className="small secondary">{reg.consent.purposes_excluded.join(", ") || "—"}</td>
            </tr>
          </tbody>
        </table>
        <details style={{ marginTop: 10 }}>
          <summary>Full regulator rendering (JSON)</summary>
          <pre className="json">{JSON.stringify(reg, null, 2)}</pre>
        </details>
      </div>
    </>
  );
}
