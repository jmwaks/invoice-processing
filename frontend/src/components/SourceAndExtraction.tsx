import { useEffect, useState } from "react";
import { useRunStore } from "../store/runStore.ts";
import { getSource } from "../api/client.ts";

export function SourceAndExtraction() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const [source, setSource] = useState<string>("");

  useEffect(() => {
    if (!activeId) return;
    getSource(activeId).then((s) => setSource(s.text)).catch(() => setSource(""));
  }, [activeId]);

  if (!run) return null;
  const inv = run.state.invoice;
  const signals = run.state.suspicion_signals ?? [];

  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Raw</h3>
        <pre className="text-xs font-mono whitespace-pre-wrap break-words max-h-80 overflow-auto">{source || "—"}</pre>
      </div>
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Extracted</h3>
        {inv ? (
          <pre className="text-xs font-mono whitespace-pre-wrap max-h-80 overflow-auto">
            {JSON.stringify(inv, null, 2)}
          </pre>
        ) : <div className="text-slate-400 text-sm">Pending…</div>}
        {signals.length > 0 && (
          <div className="mt-2 space-x-1">
            {signals.map((s, i) => (
              <span key={i} className="inline-block text-xs px-2 py-0.5 rounded bg-rose-100 text-rose-800" title={s.detail}>
                {s.kind} ({s.severity})
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
