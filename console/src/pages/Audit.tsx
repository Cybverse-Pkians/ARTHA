import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Provenance } from "../components/Provenance";
import { StatTile } from "../components/StatTile";
import { titleCase } from "../components/format";

interface VerifyResponse {
  verified: boolean;
  detail: string;
  records: number;
  note: string;
}

interface RecordRow {
  seq: number;
  type: string;
  customer_token: string;
  at: string;
  actor: string;
  hash: string;
  payload_keys: string[];
}

export function Audit() {
  const [verify, setVerify] = useState<VerifyResponse | null>(null);
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [pack, setPack] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<VerifyResponse>("/audit/verify"),
      api.get<{ records: RecordRow[] }>("/audit/records?limit=60"),
    ])
      .then(([v, r]) => {
        setVerify(v);
        setRecords(r.records);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!verify) return <p className="loading">Verifying the chain…</p>;

  const stress = records.filter((r) => r.type === "STRESS_OBSERVATION").length;
  const interventions = records.filter((r) => r.type.startsWith("INTERVENTION")).length;

  return (
    <>
      <div className="page-head">
        <h1>Audit trail</h1>
        <p>
          Hash-chained and append-only. Stress observations and interventions are separate record
          types: detection is reported to the risk function unconditionally, and the decision to
          assist is a distinct, separately logged step. That separation is the structural answer to
          an evergreening reading.
        </p>
      </div>
      <Provenance />

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <StatTile
          label="Chain integrity"
          value={
            <Badge tone={verify.verified ? "good" : "critical"}>
              {verify.verified ? "Verified" : "Broken"}
            </Badge>
          }
          note={verify.detail}
        />
        <StatTile label="Stress observations" value={stress} note="Logged whether or not assistance followed." />
        <StatTile label="Intervention records" value={interventions} note="A separate, logged decision." />
      </div>

      <div className="card">
        <h2>Records</h2>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th className="num">Seq</th>
                <th>Type</th>
                <th>Customer</th>
                <th>Actor</th>
                <th>At</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr
                  key={r.seq}
                  style={{ cursor: "pointer" }}
                  onClick={() =>
                    api
                      .get(`/audit/evidence/${r.customer_token}`)
                      .then(setPack)
                      .catch((e) => setError(String(e)))
                  }
                >
                  <td className="num mono">{r.seq}</td>
                  <td className="small">{titleCase(r.type)}</td>
                  <td className="mono">{r.customer_token}</td>
                  <td className="small">{r.actor}</td>
                  <td className="mono small">{r.at}</td>
                  <td className="mono small muted">{r.hash}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          Select a row to build that customer&rsquo;s evidence pack.
        </p>
      </div>

      {pack ? (
        <div className="card">
          <h2>Evidence pack</h2>
          <pre className="json">{JSON.stringify(pack, null, 2)}</pre>
        </div>
      ) : null}
    </>
  );
}
