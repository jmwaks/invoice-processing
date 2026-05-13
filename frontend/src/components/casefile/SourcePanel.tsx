import { useEffect, useState } from "react";
import { getSource } from "../../api/client.ts";
import { annotateSource } from "../../lib/sourceAnnotation.ts";
import type { SuspicionSignal } from "../../types/state.ts";
import { Flag } from "../common/Icons.tsx";

export function SourcePanel({
  runId,
  signals,
}: {
  runId: string;
  signals: SuspicionSignal[];
}) {
  const [source, setSource] = useState<string>("");
  useEffect(() => {
    getSource(runId)
      .then((s) => setSource(s.text))
      .catch(() => setSource(""));
  }, [runId]);

  const { segments, unplaced } = annotateSource(source, signals);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-3">Source</h3>
      {unplaced.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {unplaced.map((s, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200"
              title={s.detail}
            >
              <Flag size={11} /> {s.kind} ({s.severity})
            </span>
          ))}
        </div>
      )}
      <pre className="font-mono text-xs whitespace-pre-wrap break-words max-h-[480px] overflow-auto text-slate-800">
        {segments.map((seg, i) =>
          seg.signal ? (
            <span
              key={i}
              title={`${seg.signal.kind} (${seg.signal.severity}) — ${seg.signal.detail}`}
              className="underline decoration-rose-400 decoration-1 underline-offset-2 hover:bg-rose-50"
            >
              {seg.text}
            </span>
          ) : (
            <span key={i}>{seg.text}</span>
          ),
        )}
      </pre>
    </div>
  );
}
