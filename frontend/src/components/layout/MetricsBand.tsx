import { useQuery } from "@tanstack/react-query";
import { getMetrics, type Metrics } from "../../api/client.ts";

const fmtUSD = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);

export function MetricsBand() {
  const { data: m, error } = useQuery<Metrics>({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 1500,
  });

  if (error) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6 mb-6">
        <p className="text-sm text-rose-600">Metrics unavailable — retrying</p>
      </div>
    );
  }
  if (!m) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6 mb-6 h-[112px]" />
    );
  }

  const approvedPct =
    m.total_runs === 0 ? 0 : Math.round((m.approved_count / m.total_runs) * 100);
  const avgSec = m.avg_run_seconds === null ? "—" : `${m.avg_run_seconds.toFixed(1)}s`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-6 bg-white border border-slate-200 rounded-lg p-6 mb-6">
      <Stat label="Runs processed" value={String(m.total_runs)} mono />
      <Stat label="Auto-approved" value={`${m.approved_count}`} suffix={`(${approvedPct}%)`} mono />
      <Stat label="Avg processing time" value={avgSec} sub="vs. ~5 days manual" mono />
      <Stat label="Total approved" value={fmtUSD(m.total_dollars_approved)} mono />
      <Stat
        label="Simulated savings"
        value={fmtUSD(m.simulated_dollars_saved)}
        sub={`@ ${fmtUSD(m.manual_cost_per_invoice_usd)}/invoice manual cost`}
        mono
      />
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  suffix,
  mono,
}: {
  label: string;
  value: string;
  sub?: string;
  suffix?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <span className="text-3xl font-semibold text-slate-900 leading-none">
        <span className={mono ? "font-mono" : ""}>{value}</span>
        {suffix && <span className="ml-1.5 text-2xl text-slate-500">{suffix}</span>}
      </span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  );
}
