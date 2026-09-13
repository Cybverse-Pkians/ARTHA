import { useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { formatCompactPaise, formatPaise } from "./format";

/** The Financial Twin, drawn.
 *
 * Report §5.1: "the same chart serves three purposes: it is the affordability
 * engine, it is the customer-facing explanation, and it is the consent screen.
 * Consent becomes informed by construction rather than by disclosure."
 *
 * So this is not a dashboard ornament. Three things it must always show,
 * because they are the argument:
 *
 *  - the projected balance **with and without** the obligation, together, so the
 *    cost of the product is visible as a change in the customer's own line
 *    rather than stated as a ratio;
 *  - the **safe buffer** as a threshold the lines can be seen approaching;
 *  - **when**, on a time axis the reader can actually read a date off.
 *
 * The third one is why `dayAt` exists. The backend samples the simulation every
 * few days and sends the day offset of each sample; spreading those points
 * evenly across the horizon instead would misdate every one of them, by up to a
 * week at the right-hand end. A customer consenting to a picture of their own
 * balance is entitled to have the dates on it be true.
 *
 * Colours are the validated categorical slots 1 and 2. Both series are direct-
 * labelled at their right-hand end in addition to the legend, so identity never
 * rests on colour alone.
 */

const W = 720;
const H = 280;
const PAD = { top: 16, right: 92, bottom: 44, left: 58 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

export interface TwinChartProps {
  pathWith: number[];
  pathWithout: number[];
  pathP05?: number[];
  /** Day offset of each sample. Falls back to an even spread when absent. */
  pathDays?: number[];
  safeBufferPaise: number;
  horizonDays?: number;
  labelWith?: string;
  labelWithout?: string;
}

export function TwinChart({
  pathWith,
  pathWithout,
  pathP05 = [],
  pathDays = [],
  safeBufferPaise,
  horizonDays = 180,
  labelWith = "With this loan",
  labelWithout = "Without it",
}: TwinChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const n = Math.max(pathWith.length, pathWithout.length);

  // The two series are identical whenever no obligation is being tested — a
  // suppression, or a customer being assisted rather than sold to. Drawing one
  // opaque line straight over the other then hides it completely and collides
  // the two end labels into an unreadable overlap, which is how the chart came
  // to read "Withoutthisloan".
  const identical =
    pathWith.length > 0 &&
    pathWith.length === pathWithout.length &&
    pathWith.every((v, i) => v === pathWithout[i]);

  const geom = useMemo(() => {
    const all = [...pathWith, ...pathWithout, ...pathP05, safeBufferPaise, 0];
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const span = hi - lo || 1;
    const padY = span * 0.12;
    const yMin = lo - padY;
    const yMax = hi + padY;

    // Day of sample i, from the backend where it sent them.
    const dayAt = (i: number) => {
      if (pathDays.length === n && pathDays.length > 0) return pathDays[i];
      return Math.round((i / Math.max(n - 1, 1)) * horizonDays);
    };
    const lastDay = n > 0 ? dayAt(n - 1) : horizonDays;
    const axisMax = Math.max(lastDay, 1);

    // x is a function of the day, not of the index, so unevenly spaced samples
    // land where they belong on the time axis.
    const xForDay = (day: number) => PAD.left + (day / axisMax) * PLOT_W;
    const x = (i: number) => xForDay(dayAt(i));
    const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * PLOT_H;

    const line = (series: number[]) =>
      series
        .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
        .join(" ");

    // Uncertainty band between the 5th-percentile path and the median path.
    const band =
      pathP05.length === pathWith.length && pathP05.length > 1
        ? `${line(pathWith)} ` +
          `${pathP05
            .map(
              (_, i) =>
                `L${x(pathP05.length - 1 - i).toFixed(1)},${y(
                  pathP05[pathP05.length - 1 - i],
                ).toFixed(1)}`,
            )
            .join(" ")} Z`
        : "";

    const ticks = [yMin, (yMin + yMax) / 2, yMax].map((v) => ({ v, y: y(v) }));

    // Month-ish gridlines the reader can count off, rather than a bare "today"
    // at one end and the horizon at the other.
    const step = axisMax > 120 ? 30 : axisMax > 60 ? 15 : 7;
    const dayTicks: { day: number; x: number }[] = [];
    for (let d = 0; d <= axisMax; d += step) dayTicks.push({ day: d, x: xForDay(d) });
    if (dayTicks[dayTicks.length - 1].day !== axisMax) {
      dayTicks.push({ day: axisMax, x: xForDay(axisMax) });
    }

    return { x, y, xForDay, line, band, ticks, dayTicks, dayAt, lastDay, axisMax };
  }, [pathWith, pathWithout, pathP05, pathDays, safeBufferPaise, n, horizonDays]);

  function onMove(e: ReactMouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    if (n === 0) return;
    // Clamp rather than blank. Nulling the readout outside the plot made the
    // right-hand twelfth of the chart — every day past the last sample's x —
    // silently unreadable, so the day readout appeared to stop partway along.
    const day = ((px - PAD.left) / PLOT_W) * geom.axisMax;
    let nearest = 0;
    let best = Infinity;
    for (let i = 0; i < n; i += 1) {
      const d = Math.abs(geom.dayAt(i) - day);
      if (d < best) {
        best = d;
        nearest = i;
      }
    }
    setHover(nearest);
  }

  const bufferY = geom.y(safeBufferPaise);
  const endWithoutY = pathWithout.length > 0 ? geom.y(pathWithout[pathWithout.length - 1]) : 0;
  const endWithY = pathWith.length > 0 ? geom.y(pathWith[pathWith.length - 1]) : 0;
  const endLabelsOverlap = Math.abs(endWithoutY - endWithY) < 18;
  const labelWithoutY = endLabelsOverlap ? Math.max(PAD.top + 10, endWithoutY - 8) : endWithoutY + 4;
  const labelWithY = endLabelsOverlap ? Math.min(H - PAD.bottom - 2, endWithY + 13) : endWithY + 4;

  const hoverDay = hover !== null ? geom.dayAt(hover) : null;

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

      {identical ? (
        <p className="small muted" style={{ margin: "0 0 6px" }}>
          No obligation is being tested, so both lines are the same projection.
        </p>
      ) : null}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`Projected balance over ${geom.lastDay} days, with and without the obligation, against a safe buffer of ${formatPaise(safeBufferPaise)}`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: "block", overflow: "visible" }}
      >
        {/* recessive grid */}
        {geom.ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.left}
              x2={PAD.left + PLOT_W}
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
          width={PLOT_W}
          height={Math.max(H - PAD.bottom - bufferY, 0)}
          fill="var(--critical)"
          opacity={0.05}
        />

        {/* day axis */}
        {geom.dayTicks.map((t) => (
          <g key={t.day}>
            <line
              x1={t.x}
              x2={t.x}
              y1={PAD.top}
              y2={H - PAD.bottom}
              stroke="var(--border)"
              strokeWidth={1}
              strokeDasharray="2 4"
              opacity={t.day === 0 ? 0 : 0.7}
            />
            <text
              x={t.x}
              y={H - PAD.bottom + 16}
              textAnchor="middle"
              fontSize="10.5"
              fill="var(--text-muted)"
            >
              {t.day === 0 ? "today" : `+${t.day}d`}
            </text>
          </g>
        ))}
        <text
          x={PAD.left + PLOT_W / 2}
          y={H - 8}
          textAnchor="middle"
          fontSize="10.5"
          fill="var(--text-muted)"
        >
          days from today
        </text>

        {geom.band ? (
          <path d={geom.band} fill="var(--series-2)" opacity={0.11} stroke="none" />
        ) : null}

        {/* safe buffer threshold */}
        <line
          x1={PAD.left}
          x2={PAD.left + PLOT_W}
          y1={bufferY}
          y2={bufferY}
          stroke="var(--critical)"
          strokeWidth={2}
          strokeDasharray="5 4"
        />
        <text
          x={PAD.left + PLOT_W + 6}
          y={bufferY + 4}
          fontSize="10.5"
          fill="var(--critical)"
          fontWeight={600}
        >
          Safe buffer
        </text>

        {/* When the two projections coincide, the lower line is drawn wider and
            dashed so it stays visible underneath rather than being painted over. */}
        <path
          d={geom.line(pathWithout)}
          fill="none"
          stroke="var(--series-1)"
          strokeWidth={identical ? 5 : 2}
          strokeDasharray={identical ? "2 6" : undefined}
          strokeLinecap="round"
        />
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

      {/* The readout is pinned to one side rather than following the cursor.
          Flipping it mid-track made it jump backwards as the reader moved
          forwards, which reads as the chart having stopped responding. */}
      {hover !== null && hover < pathWith.length ? (
        <div
          className="tooltip"
          style={{ left: geom.x(hover) > W * 0.55 ? 8 : undefined, right: geom.x(hover) > W * 0.55 ? undefined : 8, top: 44 }}
        >
          <div className="tooltip-row">
            <span className="tooltip-key">Day</span>
            <span className="tooltip-val">+{hoverDay}</span>
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
                  <td className="num">+{geom.dayAt(i)}</td>
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
