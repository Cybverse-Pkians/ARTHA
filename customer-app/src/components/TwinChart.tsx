import { useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { formatCompactPaise, formatPaise } from "./format";

/** The Financial Twin, drawn.
 *
 * Report §5.1: "the same chart serves three purposes: it is the affordability
 * engine, it is the customer-facing explanation, and it is the consent screen.
 * Consent becomes informed by construction rather than by disclosure."
 *
 * So this is not a dashboard ornament. Two things it must always show, because
 * they are the argument:
 *
 *  - the projected balance **with and without** the obligation, together, so the
 *    cost of the product is visible as a change in the customer's own line
 *    rather than stated as a ratio;
 *  - the **safe buffer** as a threshold the lines can be seen approaching.
 *
 * Colours are the validated categorical slots 1 and 2. Both series are direct-
 * labelled at their right-hand end in addition to the legend, so identity never
 * rests on colour alone.
 */

const W = 720;
const H = 260;
const PAD = { top: 16, right: 92, bottom: 28, left: 58 };

export interface TwinChartProps {
  pathWith: number[];
  pathWithout: number[];
  pathP05?: number[];
  safeBufferPaise: number;
  horizonDays?: number;
  labelWith?: string;
  labelWithout?: string;
}

export function TwinChart({
  pathWith,
  pathWithout,
  pathP05 = [],
  safeBufferPaise,
  horizonDays = 180,
  labelWith = "With this loan",
  labelWithout = "Without it",
}: TwinChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const n = Math.max(pathWith.length, pathWithout.length);
  const geom = useMemo(() => {
    const all = [...pathWith, ...pathWithout, ...pathP05, safeBufferPaise, 0];
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const span = hi - lo || 1;
    const padY = span * 0.12;
    const yMin = lo - padY;
    const yMax = hi + padY;

    const x = (i: number) =>
      PAD.left + (i / Math.max(n - 1, 1)) * (W - PAD.left - PAD.right);
    const y = (v: number) =>
      PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (H - PAD.top - PAD.bottom);

    const line = (series: number[]) =>
      series.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

    // Uncertainty band between the 5th-percentile path and the median path.
    const band =
      pathP05.length === pathWith.length && pathP05.length > 1
        ? `${pathWith.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} ` +
          `${pathP05
            .map((v, i) => `L${x(pathP05.length - 1 - i).toFixed(1)},${y(pathP05[pathP05.length - 1 - i]).toFixed(1)}`)
            .join(" ")} Z`
        : "";

    const ticks = [yMin, (yMin + yMax) / 2, yMax].map((v) => ({ v, y: y(v) }));
    return { x, y, line, band, ticks, yMin, yMax };
  }, [pathWith, pathWithout, pathP05, safeBufferPaise, n]);

  const daysPerPoint = horizonDays / Math.max(n - 1, 1);

  function onMove(e: ReactMouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const ratio = (px - PAD.left) / (W - PAD.left - PAD.right);
    const idx = Math.round(ratio * (n - 1));
    setHover(idx >= 0 && idx < n ? idx : null);
  }

  const bufferY = geom.y(safeBufferPaise);
  const endWithoutY = pathWithout.length > 0 ? geom.y(pathWithout[pathWithout.length - 1]) : 0;
  const endWithY = pathWith.length > 0 ? geom.y(pathWith[pathWith.length - 1]) : 0;
  const endLabelsOverlap = Math.abs(endWithoutY - endWithY) < 18;
  const labelWithoutY = endLabelsOverlap ? Math.max(PAD.top + 10, endWithoutY - 8) : endWithoutY + 4;
  const labelWithY = endLabelsOverlap ? Math.min(H - PAD.bottom - 2, endWithY + 13) : endWithY + 4;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <div className="legend">
        <span className="legend-item">
          <span className="swatch" style={{ background: "var(--series-1)" }} />
          {labelWithout}
        </span>
        <span className="legend-item">
          <span className="swatch" style={{ background: "var(--series-2)" }} />
          {labelWith}
        </span>
        <span className="legend-item">
          <span className="swatch-dash" />
          Safe buffer {formatPaise(safeBufferPaise)}
        </span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`Projected balance over ${horizonDays} days, with and without the obligation, against a safe buffer of ${formatPaise(safeBufferPaise)}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: "block", overflow: "visible" }}
      >
        {/* recessive grid */}
        {geom.ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={t.y}
              y2={t.y}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={t.y + 4}
              textAnchor="end"
              fontSize="10.5"
              fill="var(--text-muted)"
            >
              {formatCompactPaise(t.v)}
            </text>
          </g>
        ))}

        {/* the region below the buffer — where the customer should never be */}
        <rect
          x={PAD.left}
          y={bufferY}
          width={W - PAD.left - PAD.right}
          height={Math.max(H - PAD.bottom - bufferY, 0)}
          fill="var(--critical)"
          opacity={0.05}
        />

        {geom.band ? (
          <path d={geom.band} fill="var(--series-2)" opacity={0.11} stroke="none" />
        ) : null}

        {/* safe buffer threshold */}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={bufferY}
          y2={bufferY}
          stroke="var(--critical)"
          strokeWidth={2}
          strokeDasharray="5 4"
        />
        <text
          x={W - PAD.right + 6}
          y={bufferY + 4}
          fontSize="10.5"
          fill="var(--critical)"
          fontWeight={600}
        >
          Safe buffer
        </text>

        <path d={geom.line(pathWithout)} fill="none" stroke="var(--series-1)" strokeWidth={2} />
        <path d={geom.line(pathWith)} fill="none" stroke="var(--series-2)" strokeWidth={2} />

        {/* direct labels at the line ends */}
        {pathWithout.length > 0 ? (
          <g>
            {endLabelsOverlap ? (
              <line
                x1={geom.x(pathWithout.length - 1) + 2}
                y1={endWithoutY}
                x2={geom.x(pathWithout.length - 1) + 5}
                y2={labelWithoutY - 3}
                stroke="var(--series-1)"
                strokeWidth={1}
              />
            ) : null}
            <text
              x={geom.x(pathWithout.length - 1) + 7}
              y={labelWithoutY}
              fontSize="11"
              fill="var(--series-1)"
              fontWeight={600}
            >
              {labelWithout}
            </text>
          </g>
        ) : null}
        {pathWith.length > 0 ? (
          <g>
            {endLabelsOverlap ? (
              <line
                x1={geom.x(pathWith.length - 1) + 2}
                y1={endWithY}
                x2={geom.x(pathWith.length - 1) + 5}
                y2={labelWithY - 3}
                stroke="var(--series-2)"
                strokeWidth={1}
              />
            ) : null}
            <text
              x={geom.x(pathWith.length - 1) + 7}
              y={labelWithY}
              fontSize="11"
              fill="var(--series-2)"
              fontWeight={600}
            >
              {labelWith}
            </text>
          </g>
        ) : null}

        {/* x axis */}
        <text x={PAD.left} y={H - 8} fontSize="10.5" fill="var(--text-muted)">
          today
        </text>
        <text x={W - PAD.right} y={H - 8} fontSize="10.5" fill="var(--text-muted)" textAnchor="end">
          +{horizonDays} days
        </text>

        {hover !== null && hover < pathWith.length ? (
          <g>
            <line
              x1={geom.x(hover)}
              x2={geom.x(hover)}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="var(--border-strong)"
              strokeWidth={1}
            />
            <circle
              cx={geom.x(hover)}
              cy={geom.y(pathWithout[hover] ?? 0)}
              r={4}
              fill="var(--series-1)"
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
            <circle
              cx={geom.x(hover)}
              cy={geom.y(pathWith[hover] ?? 0)}
              r={4}
              fill="var(--series-2)"
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
          </g>
        ) : null}
      </svg>

      {hover !== null && hover < pathWith.length ? (
        <div
          className="tooltip"
          style={{
            left: `${(geom.x(hover) / W) * 100}%`,
            top: 44,
            transform: geom.x(hover) > W * 0.6 ? "translateX(-108%)" : "translateX(8px)",
          }}
        >
          <div className="tooltip-row">
            <span className="tooltip-key">Day</span>
            <span className="tooltip-val">+{Math.round(hover * daysPerPoint)}</span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-key">{labelWithout}</span>
            <span className="tooltip-val">{formatPaise(pathWithout[hover] ?? 0)}</span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-key">{labelWith}</span>
            <span className="tooltip-val">{formatPaise(pathWith[hover] ?? 0)}</span>
          </div>
        </div>
      ) : null}

      {/* The table view is the accessibility relief for the chart. */}
      <details>
        <summary>Table view</summary>
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th className="num">Day</th>
                <th className="num">{labelWithout}</th>
                <th className="num">{labelWith}</th>
                <th className="num">Above buffer?</th>
              </tr>
            </thead>
            <tbody>
              {pathWith.map((v, i) => (
                <tr key={i}>
                  <td className="num">+{Math.round(i * daysPerPoint)}</td>
                  <td className="num">{formatPaise(pathWithout[i] ?? 0)}</td>
                  <td className="num">{formatPaise(v)}</td>
                  <td className="num">{v >= safeBufferPaise ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
