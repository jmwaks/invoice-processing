import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listRuns, runBatch } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { useRunStore } from "../store/runStore.ts";

export function BatchQueue() {
  const { data, refetch } = useQuery({ queryKey: ["runs"], queryFn: listRuns, refetchInterval: 1500 });
  const selectRun = useRunStore((s) => s.selectRun);
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);
  const activeId = useRunStore((s) => s.activeRunId);
  const runs = useRunStore((s) => s.runs);
  const [running, setRunning] = useState(false);

  // NOTE: We deliberately do NOT open an SSE connection for every run in a
  // batch. HTTP/1.1 caps at ~6 concurrent connections per origin, so 16 streams
  // would queue and stall. Instead, the batch endpoint triggers all runs
  // server-side; this queue refreshes every 1.5s via `listRuns` polling for
  // outcome updates. SSE only opens lazily for the currently selected run
  // (handled in the row onClick below).
  const handleBatch = async () => {
    setRunning(true);
    await runBatch();
    setRunning(false);
    refetch();
  };

  return (
    <div className="bg-white border rounded p-3 h-full">
      <div className="flex justify-between items-center mb-2">
        <h3 className="font-semibold text-sm">Runs</h3>
        <button
          onClick={handleBatch}
          disabled={running}
          className="text-xs px-2 py-1 rounded bg-slate-900 text-white disabled:opacity-50"
        >
          {running ? "Starting…" : "Run all 16"}
        </button>
      </div>
      <ul className="text-xs space-y-1 max-h-[70vh] overflow-auto">
        {(data ?? []).map((r) => (
          <li
            key={r.run_id}
            onClick={() => {
              if (!runs[r.run_id]) {
                initializeRun(r.run_id);
                subscribeToRun(r.run_id, (e) => appendEvent(r.run_id, e));
              }
              selectRun(r.run_id);
            }}
            className={`cursor-pointer flex justify-between gap-2 p-1 rounded
              ${activeId === r.run_id ? "bg-slate-100" : "hover:bg-slate-50"}`}
          >
            <span className="font-mono truncate max-w-[110px]">{r.invoice_number ?? r.run_id.slice(0, 8)}</span>
            <span className="truncate max-w-[80px] text-slate-500">{r.vendor ?? "—"}</span>
            <OutcomeChip outcome={r.outcome} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function OutcomeChip({ outcome }: { outcome: string }) {
  const cls =
    outcome === "approved" ? "bg-emerald-100 text-emerald-800" :
    outcome === "rejected" ? "bg-rose-100 text-rose-800" :
    outcome === "needs_review" ? "bg-amber-100 text-amber-800" :
    outcome === "unprocessable" ? "bg-slate-200 text-slate-700" :
    "bg-slate-100 text-slate-500";
  return <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls}`}>{outcome}</span>;
}
