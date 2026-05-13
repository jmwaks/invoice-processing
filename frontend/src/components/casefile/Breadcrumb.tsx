import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { listRuns } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";
import { ArrowLeft } from "../common/Icons.tsx";

export function Breadcrumb({ runId }: { runId: string }) {
  const batch = useRunStore((s) => s.currentBatch);
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: listRuns, refetchInterval: 1500 });

  const thisRun = runs?.find((r) => r.run_id === runId);
  const isRetryChild = thisRun?.parent_run_id !== null && thisRun?.parent_run_id !== undefined;
  const parent = isRetryChild
    ? runs?.find((r) => r.run_id === thisRun!.parent_run_id)
    : null;
  const supersededBy = runs?.find((r) => r.parent_run_id === runId);

  if (isRetryChild && parent) {
    return (
      <div className="mb-4 text-sm text-slate-600">
        <Link href={`/runs/${parent.run_id}`} className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-700">
          ↳ Retry of {parent.invoice_number ?? parent.run_id.slice(0, 8)}
        </Link>
      </div>
    );
  }

  if (batch && runs) {
    const done = batch.runIds.filter((rid) => {
      const o = runs.find((r) => r.run_id === rid)?.outcome;
      return o && o !== "running";
    }).length;
    return (
      <div className="mb-4">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900">
          <ArrowLeft size={16} /> Back to batch overview · {done}/{batch.runIds.length} done
        </Link>
        {supersededBy && (
          <Link
            href={`/runs/${supersededBy.run_id}`}
            className="block mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5 hover:bg-amber-100"
          >
            Superseded by retry · run {supersededBy.run_id.slice(0, 8)}
          </Link>
        )}
      </div>
    );
  }

  return (
    <div className="mb-4">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft size={16} /> Back to overview
      </Link>
      {supersededBy && (
        <Link
          href={`/runs/${supersededBy.run_id}`}
          className="block mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5 hover:bg-amber-100"
        >
          Superseded by retry · run {supersededBy.run_id.slice(0, 8)}
        </Link>
      )}
    </div>
  );
}
