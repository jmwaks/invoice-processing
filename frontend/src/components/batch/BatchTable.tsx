import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { listRuns } from "../../api/client.ts";
import { OutcomeChip } from "../common/OutcomeChip.tsx";

type RunSummary = Awaited<ReturnType<typeof listRuns>>[number];

type Filter = "all" | "approved" | "rejected" | "needs_review" | "unprocessable";
type Sort = "time" | "vendor" | "amount" | "outcome";

const fmtUSD = (n: number | null) =>
  n === null
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

export function BatchTable() {
  const [, setLocation] = useLocation();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("time");

  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });

  if (!runs) return null;

  const filtered = runs.filter((r) => filter === "all" || r.outcome === filter);
  const sorted = [...filtered].sort((a, b) => {
    if (sort === "vendor") return (a.vendor ?? "").localeCompare(b.vendor ?? "");
    if (sort === "amount") return (b.total ?? 0) - (a.total ?? 0);
    if (sort === "outcome") return a.outcome.localeCompare(b.outcome);
    return 0; // time = insertion order from the backend
  });

  return (
    <div className="bg-white border border-slate-200 rounded-lg">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-100">
        <label className="text-xs uppercase tracking-wide text-slate-500">Filter</label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          className="text-sm border border-slate-200 rounded px-2 py-1 bg-white"
        >
          <option value="all">All</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="needs_review">Needs review</option>
          <option value="unprocessable">Unprocessable</option>
        </select>
        <label className="text-xs uppercase tracking-wide text-slate-500 ml-4">Sort</label>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          className="text-sm border border-slate-200 rounded px-2 py-1 bg-white"
        >
          <option value="time">Time</option>
          <option value="vendor">Vendor</option>
          <option value="amount">Amount</option>
          <option value="outcome">Outcome</option>
        </select>
      </div>
      <table className="w-full">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-100">
            <th className="px-4 py-2 font-medium">Invoice #</th>
            <th className="px-4 py-2 font-medium">Vendor</th>
            <th className="px-4 py-2 font-medium">Total</th>
            <th className="px-4 py-2 font-medium">Outcome</th>
            <th className="px-4 py-2 font-medium">Signals</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <BatchRow key={r.run_id} run={r} onClick={() => setLocation(`/runs/${r.run_id}`)} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BatchRow({ run, onClick }: { run: RunSummary; onClick: () => void }) {
  return (
    <tr
      onClick={onClick}
      className="cursor-pointer hover:bg-slate-50 border-b border-slate-100 last:border-0"
    >
      <td className="px-4 py-3 font-mono text-sm">
        {run.invoice_number ?? run.run_id.slice(0, 8)}
      </td>
      <td className="px-4 py-3 text-sm text-slate-700">{run.vendor ?? "—"}</td>
      <td className="px-4 py-3 font-mono text-sm">{fmtUSD(run.total)}</td>
      <td className="px-4 py-3">
        <OutcomeChip outcome={run.outcome} />
      </td>
      <td className="px-4 py-3">
        {/* Signal flag only when suspicion_signals is non-empty — but listRuns
            doesn't include those yet, so for now we omit. The Case File shows them. */}
      </td>
    </tr>
  );
}
