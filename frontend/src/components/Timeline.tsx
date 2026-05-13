import { useRunStore } from "../store/runStore.ts";
import type { RunEvent } from "../types/events.ts";
import { StatusBadge } from "./StatusBadge.tsx";

const STAGES = ["ingest", "validate", "approve", "pay", "log"] as const;

type ToolCallEvent = Extract<RunEvent, { kind: "tool.call" }>;

export function Timeline() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const toolCallEvents = run
    ? (run.events.filter((e): e is ToolCallEvent => e.kind === "tool.call"))
    : [];
  if (!run) {
    return <div className="text-slate-400 text-sm p-4">No active run. Upload an invoice to start.</div>;
  }
  return (
    <div className="bg-white border rounded p-4 space-y-2">
      <h2 className="font-semibold">Timeline · {run.runId.slice(0, 8)}</h2>
      <ul className="space-y-1">
        {STAGES.map((s) => {
          const stage = run.stages[s];
          return (
            <li key={s}>
              <div className="flex items-center gap-2 text-sm">
                <StatusBadge status={stage.status} />
                <span className="font-mono uppercase w-20">{s}</span>
                {stage.summary && (
                  <span className="text-slate-500 truncate">
                    {JSON.stringify(stage.summary).slice(0, 80)}
                  </span>
                )}
              </div>
              {s === "approve" && stage.status !== "pending" && (
                <ul className="ml-8 mt-1 space-y-1">
                  {(["propose", "critique", "finalize"] as const).map((sub) => (
                    <li key={sub} className="flex items-center gap-2 text-xs">
                      <StatusBadge status={run.approveSubStages[sub]} />
                      <span className="font-mono">{sub}</span>
                    </li>
                  ))}
                  {toolCallEvents.map((tc, i) => (
                    <li key={`tool-${i}`} className="flex items-start gap-2 text-xs py-0.5">
                      <span className="text-purple-600 font-mono">tool</span>
                      <span className="font-medium">{tc.tool}</span>
                      <span className="text-slate-500 truncate">
                        {JSON.stringify(tc.args)} → {JSON.stringify(tc.result)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
