import * as React from "react";
import { getMetrics, type Metrics } from "../api/client.ts";

const fmtUSD = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);

type Props = {
  /** Bump this number when a run completes to trigger a refresh. */
  refreshKey: number;
};

export function MetricsTile({ refreshKey }: Props) {
  const [m, setM] = React.useState<Metrics | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getMetrics()
      .then((data) => {
        if (!cancelled) setM(data);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  if (error) {
    return (
      <div className="text-sm text-rose-600 p-3">Metrics unavailable: {error}</div>
    );
  }
  if (m === null) {
    return (
      <div className="text-sm text-slate-500 p-3">Loading metrics…</div>
    );
  }

  const autoApprovedPct =
    m.total_runs === 0
      ? 0
      : Math.round((m.approved_count / m.total_runs) * 100);
  const avgSec =
    m.avg_run_seconds === null ? "—" : `${m.avg_run_seconds.toFixed(1)}s`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 p-3 bg-white border rounded-lg shadow-sm">
      <Stat label="Invoices processed" value={String(m.total_runs)} />
      <Stat
        label="Auto-approved"
        value={`${m.approved_count} (${autoApprovedPct}%)`}
      />
      <Stat
        label="Avg processing time"
        value={avgSec}
        sub="vs. ~5 days manual"
      />
      <Stat label="Total approved" value={fmtUSD(m.total_dollars_approved)} />
      <Stat
        label="Simulated savings"
        value={fmtUSD(m.simulated_dollars_saved)}
        sub={`@ ${fmtUSD(m.manual_cost_per_invoice_usd)}/invoice manual cost`}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <span className="text-2xl font-semibold text-slate-900">{value}</span>
      {sub && <span className="text-xs text-slate-500 mt-0.5">{sub}</span>}
    </div>
  );
}
