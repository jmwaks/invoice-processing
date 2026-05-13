import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { getMetrics, listRuns, type Metrics } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";

const fmtCompactUSD = (n: number) => {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n)}`;
};

export function LeftRail() {
  const { data: m } = useQuery<Metrics>({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 1500,
  });
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });
  const batch = useRunStore((s) => s.currentBatch);

  const doneCount = (() => {
    if (!batch || !runs) return 0;
    const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
    return batch.runIds.filter((rid) => {
      const o = byId.get(rid);
      return o && o !== "running";
    }).length;
  })();

  return (
    <aside className="w-[280px] shrink-0">
      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">
          Session
        </h2>
        {m && (
          <p className="text-sm text-slate-700">
            {m.total_runs} runs · {m.approved_count} approved ·{" "}
            {fmtCompactUSD(m.total_dollars_approved)} approved
          </p>
        )}
        <Link
          href="/"
          className="block mt-3 text-sm text-indigo-600 hover:text-indigo-700"
        >
          ▶ Batch overview
        </Link>
        {batch && (
          <div className="mt-3">
            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-600 transition-all duration-300"
                style={{ width: `${(doneCount / batch.runIds.length) * 100}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {doneCount} / {batch.runIds.length} done
            </p>
          </div>
        )}
      </div>
      {/* Runs list will be added in the next task */}
    </aside>
  );
}
