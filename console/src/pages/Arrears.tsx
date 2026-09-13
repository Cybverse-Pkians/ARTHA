import { useEffect, useState } from "react";
import { api } from "../api";
import { Provenance } from "../components/Provenance";
import { SmaBadge } from "../components/SmaBadge";
import { StatTile } from "../components/StatTile";
import { titleCase } from "../components/format";

interface ArrearsAccount {
  customer_token: string;
  name: string;
  stage: string;
  stage_label: string;
  days_past_due: number;
  missed_instalments: number;
  overdue_amount: string;
  instalment: string;
  oldest_unpaid_due: string | null;
  last_payment_on: string | null;
  recovery_state: string;
  income_type: string;
  district: string;
  evidence: string[];
}

interface ArrearsResponse {
  buckets: Record<string, number>;
  flagged: number;
  accounts: ArrearsAccount[];
  note: string;
  verify_against_circular: boolean;
  regulatory_note: string;
  data_provenance: string;
}

const ORDER = ["STANDARD", "SMA_0", "SMA_1", "SMA_2", "NPA"];
const LABEL: Record<string, string> = {
  STANDARD: "Standard",
  SMA_0: "SMA-0",
  SMA_1: "SMA-1",
  SMA_2: "SMA-2",
  NPA: "NPA",
};
const BAND: Record<string, string> = {
  STANDARD: "Nothing overdue",
  SMA_0: "1–30 days past due",
  SMA_1: "31–60 days past due",
  SMA_2: "61–90 days past due",
  NPA: "Beyond 90 days past due",
};

/** The book by Special Mention Account stage.
 *
 * Separate from the early-warning queue on purpose. The queue is a prediction
 * about customers who are still paying; this is a record of the ones who have
 * stopped. They call for different work and carry different evidential weight,
 * and a screen that mixed them would let a banker mistake one for the other.
 */
export function Arrears({ onSelect }: { onSelect: (token: string) => void }) {
  const [data, setData] = useState<ArrearsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ArrearsResponse>("/banker/arrears")
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="loading">Reading the arrears book…</p>;

  const total = ORDER.reduce((sum, k) => sum + (data.buckets[k] ?? 0), 0) || 1;

  return (
    <>
      <div className="page-head">
        <h1>Arrears &amp; SMA stage</h1>
        <p>
          Stage follows from days past due on the currently active instalment mandate. An account
          whose mandate has been restructured is aged from the new mandate, so the arrears the
          restructuring resolved stop counting against it.
        </p>
      </div>
      <Provenance />

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <StatTile label="Accounts flagged" value={data.flagged} note={`${total} accounts assessed`} />
        <StatTile
          label="Two or more behind"
          value={(data.buckets.SMA_1 ?? 0) + (data.buckets.SMA_2 ?? 0) + (data.buckets.NPA ?? 0)}
          note="Recovery Mode active: selling suppressed in every family."
        />
        <StatTile
          label="One instalment behind"
          value={data.buckets.SMA_0 ?? 0}
          note="At risk: options offered as a service."
        />
      </div>

      <div className="card">
        <h2>Distribution by stage</h2>
        <div className="sma-bars">
          {ORDER.map((key) => {
            const count = data.buckets[key] ?? 0;
            return (
              <div className="sma-bar-row" key={key}>
                <span className="sma-bar-label">
                  <SmaBadge stage={key} label={LABEL[key]} />
                </span>
                <span className="sma-bar-track">
                  <span
                    className={`sma-bar-fill sma-fill-${key.toLowerCase()}`}
                    style={{ width: `${Math.max((count / total) * 100, count > 0 ? 2 : 0)}%` }}
                  />
                </span>
                <span className="sma-bar-count num">{count}</span>
                <span className="sma-bar-band small muted">{BAND[key]}</span>
              </div>
            );
          })}
        </div>
        <p className="small muted" style={{ marginBottom: 0, marginTop: 10 }}>
          {data.regulatory_note}
        </p>
      </div>

      <div className="card">
        <h2>Flagged accounts</h2>
        {data.accounts.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            No account is currently past due. That is a valid outcome, not an empty screen.
          </p>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Stage</th>
                  <th className="num">Days past due</th>
                  <th className="num">Outstanding</th>
                  <th className="num">In arrears</th>
                  <th>Recovery</th>
                  <th>Oldest unpaid</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.accounts.map((a) => (
                  <>
                    <tr key={a.customer_token}>
                      <td style={{ cursor: "pointer" }} onClick={() => onSelect(a.customer_token)}>
                        <strong>{a.name}</strong>
                        <div className="mono small muted">{a.customer_token}</div>
                      </td>
                      <td>
                        <SmaBadge stage={a.stage} label={a.stage_label} />
                      </td>
                      <td className="num">{a.days_past_due}</td>
                      <td className="num">{a.missed_instalments}</td>
                      <td className="num">{a.overdue_amount}</td>
                      <td className="small">{titleCase(a.recovery_state)}</td>
                      <td className="mono small">{a.oldest_unpaid_due ?? "—"}</td>
                      <td>
                        <button
                          className="btn"
                          onClick={() => setOpen(open === a.customer_token ? null : a.customer_token)}
                        >
                          {open === a.customer_token ? "Hide evidence" : "Evidence"}
                        </button>
                      </td>
                    </tr>
                    {open === a.customer_token ? (
                      <tr key={`${a.customer_token}-ev`}>
                        <td colSpan={8}>
                          <ul className="small secondary" style={{ margin: "6px 0", paddingLeft: 18 }}>
                            {a.evidence.map((e, i) => (
                              <li key={i}>{e}</li>
                            ))}
                          </ul>
                        </td>
                      </tr>
                    ) : null}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
          {data.note}
        </p>
      </div>
    </>
  );
}
