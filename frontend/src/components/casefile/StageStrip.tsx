import { useRunStore } from "../../store/runStore.ts";

const STAGES = [
  { key: "ingest", label: "Ingest" },
  { key: "validate", label: "Validate" },
  { key: "approve", label: "Approve" },
  { key: "pay", label: "Pay / Log" },
] as const;

export function StageStrip({ runId }: { runId: string }) {
  const run = useRunStore((s) => s.runs[runId]);
  if (!run) return null;

  return (
    <div className="sticky top-0 z-10 bg-slate-50 -mx-6 px-6 py-3 mb-6 border-b border-slate-200">
      <div className="flex items-center gap-2">
        {STAGES.map((s, i) => {
          const status =
            s.key === "pay"
              ? run.stages.pay.status === "pending"
                ? run.stages.log.status
                : run.stages.pay.status
              : run.stages[s.key].status;
          return (
            <div key={s.key} className="flex items-center gap-2">
              <Pip status={status} />
              <span className="text-xs uppercase tracking-wide text-slate-500">
                {s.label}
              </span>
              {i < STAGES.length - 1 && (
                <span className="w-6 h-px bg-slate-200 mx-1" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Pip({ status }: { status: string }) {
  if (status === "complete") {
    return <span className="w-2.5 h-2.5 rounded-full bg-emerald-600" />;
  }
  if (status === "running") {
    return <span className="w-2.5 h-2.5 rounded-full bg-indigo-600 animate-pulse" />;
  }
  if (status === "error") {
    return <span className="w-2.5 h-2.5 rounded-full bg-rose-600" />;
  }
  return <span className="w-2.5 h-2.5 rounded-full border border-slate-300" />;
}
