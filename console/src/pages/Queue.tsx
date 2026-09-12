import { useEffect, useState } from "react";
import { api, type CorrelatedAlert, type QueueResponse } from "../api";
import { Badge, verdictTone } from "../components/Badge";
import { Provenance } from "../components/Provenance";
import { StatTile } from "../components/StatTile";
import { formatPercent, titleCase } from "../components/format";

export function Queue({ onSelect }: { onSelect: (token: string) => void }) {
  const [data, setData] = useState<QueueResponse | null>(null);
  const [alerts, setAlerts] = useState<CorrelatedAlert[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<QueueResponse>("/banker/queue"),
      api.get<{ alerts: CorrelatedAlert[] }>("/banker/correlated"),
    ])
      .then(([q, c]) => {
        setData(q);
        setAlerts(c.alerts);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="loading">Loading queue…</p>;

  return (
    <>
      <div className="page-head">
        <h1>Early-warning queue</h1>
        <p>
          Ranked at the bank&rsquo;s actual daily contact capacity. The question is not who is
          risky, but which {data.capacity} customers should be contacted today — so customers for
          whom intervention would not change the outcome are excluded before ranking, not ranked
          and then ignored.
        </p>
      </div>
      <Provenance />

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <StatTile label="Contact capacity" value={data.capacity} note="Precision is evaluated at this N." />
        <StatTile label="In queue today" value={data.in_queue} note={`${data.assessed} customers assessed`} />
        <StatTile
          label="Excluded as unactionable"
          value={data.excluded_as_unactionable}
          note="Contact would not change the outcome."
        />
      </div>

      {alerts.length > 0 ? (
        <div className="card">
          <h2>Correlated portfolio alerts</h2>
          {alerts.map((a) => (
            <div key={a.key} className="check-row">
              <span className="check-mark check-fail">▲</span>
              <span className="check-name">{a.key}</span>
              <span className="check-detail">
                {a.description}
                <div className="muted small" style={{ marginTop: 3 }}>
                  Grouped by {a.dimension} · median delay {a.median_delay_days} days ·{" "}
                  {a.affected_customers} customers
                </div>
              </span>
            </div>
          ))}
        </div>
      ) : null}

      <div className="card">
        <h2>Queue</h2>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Signal</th>
                <th className="num">PD uplift (90d)</th>
                <th className="num">Lead time</th>
                <th>Ability</th>
                <th>Income type</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {data.queue.map((r) => (
                <tr
                  key={r.customer_token}
                  onClick={() => onSelect(r.customer_token)}
                  style={{ cursor: "pointer" }}
                >
                  <td className="mono">{r.customer_token}</td>
                  <td>
                    <Badge tone={verdictTone(r.verdict)}>{titleCase(r.verdict)}</Badge>
                  </td>
                  <td className="num">+{formatPercent(r.pd_uplift_90d)}</td>
                  <td className="num">
                    {r.lead_time_days === null ? "—" : `${r.lead_time_days} d`}
                  </td>
                  <td className="small">{titleCase(r.pay_intent)}</td>
                  <td className="small">{titleCase(r.income_type)}</td>
                  <td className="small secondary">{r.evidence[0] ?? "—"}</td>
                </tr>
              ))}
              {data.queue.length === 0 ? (
                <tr>
                  <td colSpan={7} className="muted">
                    Nobody needs contacting today. That is a valid outcome.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          Lead time is reported in days before the projected first missed payment rather than as
          model accuracy: days convert into rungs on the Intervention Ladder, and rungs differ by
          orders of magnitude in cost.
        </p>
      </div>

      {data.excluded.length > 0 ? (
        <div className="card">
          <h2>Assessed but not contacted</h2>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Signal</th>
                  <th>Reason for exclusion</th>
                </tr>
              </thead>
              <tbody>
                {data.excluded.map((r) => (
                  <tr key={r.customer_token}>
                    <td className="mono">{r.customer_token}</td>
                    <td>
                      <Badge tone={verdictTone(r.verdict)}>{titleCase(r.verdict)}</Badge>
                    </td>
                    <td className="small secondary">{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </>
  );
}
