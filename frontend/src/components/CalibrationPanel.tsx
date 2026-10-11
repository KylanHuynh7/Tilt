import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  ComposedChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CalibrationResponse, MetricBlock } from "../types";

type Props = {
  data: CalibrationResponse;
  paramsLabel: string;  // e.g. "K=10/10, c=0.85, home=40"
};

function fmt(x: number, digits = 4): string {
  return Number.isFinite(x) ? x.toFixed(digits) : "—";
}

function pass(value: number, predicate: (v: number) => boolean): string {
  return predicate(value) ? "pass" : "fail";
}

function MetricRow({ label, m, targets }: { label: string; m: MetricBlock; targets?: CalibrationResponse["section_6_targets"] }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num">{fmt(m.log_loss, 5)}</td>
      <td className="num">{fmt(m.brier, 5)}</td>
      <td className="num">{fmt(m.ece, 4)}</td>
      <td className="num dim">{m.n}</td>
      {targets && (
        <td className={`tag ${pass(m.log_loss, v => v < targets.log_loss_max)}`}>
          {pass(m.log_loss, v => v < targets.log_loss_max).toUpperCase()}
        </td>
      )}
    </tr>
  );
}

export function CalibrationPanel({ data, paramsLabel }: Props) {
  const { metrics, section_6_targets: targets, calibration_buckets } = data;

  const plotData = useMemo(() =>
    calibration_buckets
      .filter((b) => b.n >= 30) // §9 stopping criterion #6
      .map((b) => ({
        mid: (b.lo + b.hi) / 2,
        mean_predicted: b.mean_predicted,
        mean_actual: b.mean_actual,
        n: b.n,
      })),
    [calibration_buckets]
  );

  return (
    <div className="cal">
      <div className="cal-meta">
        Evaluated {new Date(data.evaluated_at).toLocaleDateString()} ·
        Frozen params {paramsLabel} ·
        n={data.n_test_predictions} test predictions ·
        seasons {data.test_seasons.join(", ")}
      </div>

      <div className="cal-grid">
        <div className="cal-col">
          <h3 className="cal-h">Test-set metrics (§6)</h3>
          <table className="metrics">
            <thead>
              <tr>
                <th></th>
                <th className="num">log-loss</th>
                <th className="num">Brier</th>
                <th className="num">ECE</th>
                <th className="num dim">n</th>
              </tr>
            </thead>
            <tbody>
              <MetricRow label="Model" m={metrics.model} />
              {metrics.home_rate_baseline && (
                <MetricRow label="Home-rate baseline" m={metrics.home_rate_baseline} />
              )}
              <MetricRow label="Static-rating baseline" m={metrics.static_rating_baseline} />
              <MetricRow label="Naive 50% baseline" m={metrics.naive_baseline} />
              <tr className="target">
                <td>§6 target</td>
                <td className="num">{`< ${targets.log_loss_max}`}</td>
                <td className="num">{`${targets.brier_band[0]}–${targets.brier_band[1]}`}</td>
                <td className="num">{`< ${targets.ece_max}`}</td>
                <td></td>
              </tr>
            </tbody>
          </table>

          <h3 className="cal-h">§6 pass / fail</h3>
          <ul className="pass-list">
            <li className={pass(metrics.model.log_loss, v => v < targets.log_loss_max)}>
              log-loss &lt; {targets.log_loss_max}: {fmt(metrics.model.log_loss, 5)}
            </li>
            <li className={pass(metrics.model.brier, v => v >= targets.brier_band[0] && v <= targets.brier_band[1])}>
              Brier in [{targets.brier_band[0]}, {targets.brier_band[1]}]: {fmt(metrics.model.brier, 5)}
            </li>
            <li className={pass(metrics.model.ece, v => v < targets.ece_max)}>
              ECE &lt; {targets.ece_max}: {fmt(metrics.model.ece, 4)}
            </li>
            {metrics.home_rate_baseline && (
              <li className={pass(metrics.model.log_loss, v => v < metrics.home_rate_baseline!.log_loss)}>
                beats home-rate baseline on log-loss: {fmt(metrics.model.log_loss, 5)} vs{" "}
                {fmt(metrics.home_rate_baseline.log_loss, 5)}
              </li>
            )}
          </ul>
        </div>

        <div className="cal-col">
          <h3 className="cal-h">Calibration plot (model)</h3>
          <div className="cal-chart">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={plotData} margin={{ top: 8, right: 16, bottom: 24, left: 0 }}>
                <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="mean_predicted"
                  type="number"
                  domain={[0, 1]}
                  stroke="var(--text-dim)"
                  fontSize={11}
                  label={{ value: "Predicted probability", position: "insideBottom", offset: -8, fontSize: 11, fill: "var(--text-dim)" }}
                />
                <YAxis
                  dataKey="mean_actual"
                  type="number"
                  domain={[0, 1]}
                  stroke="var(--text-dim)"
                  fontSize={11}
                  width={42}
                  label={{ value: "Actual rate", angle: -90, position: "insideLeft", fontSize: 11, fill: "var(--text-dim)" }}
                />
                <ReferenceLine
                  segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
                  stroke="var(--text-dim)"
                  strokeDasharray="3 3"
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--panel)",
                    border: "1px solid var(--panel-edge)",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  formatter={(value: number, name: string) =>
                    [value.toFixed(3), name === "mean_actual" ? "actual" : name]
                  }
                  labelFormatter={(v: number) => `predicted ≈ ${v.toFixed(2)}`}
                />
                <Line
                  type="linear"
                  dataKey="mean_actual"
                  stroke="var(--accent)"
                  strokeWidth={2}
                  dot={{ fill: "var(--accent)", r: 4 }}
                  isAnimationActive={false}
                  name="actual"
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="cal-foot">
            Buckets with fewer than 30 predictions are hidden per §9 stopping criterion #6.
            Dashed diagonal = perfect calibration.
          </div>
        </div>
      </div>
    </div>
  );
}
