import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { listRuns } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";

export function BatchHeader() {
  const batch = useRunStore((s) => s.currentBatch);
  const clearBatchIfComplete = useRunStore((s) => s.clearBatchIfComplete);
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });

  useEffect(() => {
    if (!batch || !runs) return;
    const doneIds = new Set(
      runs.filter((r) => r.outcome !== "running").map((r) => r.run_id),
    );
    clearBatchIfComplete(doneIds);
  }, [batch, runs, clearBatchIfComplete]);

  if (!batch || !runs) {
    return (
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Batch overview</h1>
      </header>
    );
  }
  const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
  const done = batch.runIds.filter((rid) => {
    const o = byId.get(rid);
    return o && o !== "running";
  }).length;
  const pct = (done / batch.runIds.length) * 100;

  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold">Batch overview</h1>
      <p className="text-sm text-slate-500 mt-1">
        {batch.runIds.length} invoices · processing in 4-way parallel
      </p>
      <div className="mt-3 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-indigo-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-500 mt-1">
        {done} / {batch.runIds.length} done
      </p>
    </header>
  );
}
