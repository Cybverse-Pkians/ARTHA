import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Provenance } from "../components/Provenance";
import { StatTile } from "../components/StatTile";
import { formatPercent } from "../components/format";

interface SliceRow {
  decisions: number;
  benefit_rate: number;
  gap_vs_population: number;
  suppressed: number;
  protected: number;
  in_tolerance: boolean;
}

interface FairnessReport {
  population_benefit_rate: number;
  population_decisions: number;
  slices: Record<string, SliceRow>;
  breaching: [string, number][];
  excluded_data_sources: string[];
  permitted_alternate_data: string[];
  note: string;
}

export function Fairness() {
  const [data, setData] = useState<FairnessReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<FairnessReport>("/banker/fairness").then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="loading">Loading fairness report…</p>;

  const slices = Object.entries(data.slices);

  return (
    <>
      <div className="page-head">
        <h1>Fairness</h1>
        <p>
          Two things are measured, and the second is the one that matters: error parity, and{" "}
          <em>benefit distribution</em> — who receives the favourable offers. A system can have
          perfectly equal error rates while routing every good offer to one cohort.
        </p>
      </div>
      <Provenance />

      <div className="grid grid-3" style={{ marginBottom: 14 }}>
        <StatTile
          label="Population benefit rate"
          value={formatPercent(data.population_benefit_rate)}
          note={`${data.population_decisions} decisions`}
        />
        <StatTile
          label="Slices monitored"
          value={slices.length}
          note="Gender, rural/urban, language, thin-file status, income type"
        />
        <StatTile
          label="Slices out of tolerance"
          value={data.breaching.length}
          note={
            data.breaching.length > 0
              ? "Decisions in these slices route to human review."
              : "All slices within ±20% of the population rate."
          }
        />
      </div>

      <div className="card">
        <h2>Benefit distribution by slice</h2>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Slice</th>
                <th className="num">Decisions</th>
                <th className="num">Benefit rate</th>
                <th className="num">Gap vs population</th>
                <th className="num">Suppressed</th>
                <th className="num">Protected</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {slices.map(([key, s]) => (
                <tr key={key}>
                  <td className="mono">{key}</td>
                  <td className="num">{s.decisions}</td>
                  <td className="num">{formatPercent(s.benefit_rate)}</td>
                  <td className="num">
                    {s.gap_vs_population >= 0 ? "+" : ""}
                    {formatPercent(s.gap_vs_population)}
                  </td>
                  <td className="num">{s.suppressed}</td>
                  <td className="num">{s.protected}</td>
                  <td>
                    <Badge tone={s.in_tolerance ? "good" : "warning"}>
                      {s.in_tolerance ? "In tolerance" : "Review"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          {data.note}
        </p>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h2>Published exclusion list</h2>
          <p className="small secondary" style={{ marginTop: 0 }}>
            Naming what the system refuses to use is a stronger commitment than listing what it
            does.
          </p>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {data.excluded_data_sources.map((s) => (
              <li key={s} style={{ marginBottom: 3 }}>
                {s}
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h2>Ethically bounded alternate data</h2>
          <p className="small secondary" style={{ marginTop: 0 }}>
            Used to construct history where a bureau file is thin — which is what brings women and
            first-time borrowers into scope at all.
          </p>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {data.permitted_alternate_data.map((s) => (
              <li key={s} style={{ marginBottom: 3 }}>
                {s}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
