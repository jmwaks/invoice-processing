import { useEffect, useRef, useState } from "react";
import { useRoute } from "wouter";
import { getRun } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { Breadcrumb } from "../components/casefile/Breadcrumb.tsx";
import { HeroCard } from "../components/casefile/HeroCard.tsx";
import { StageStrip } from "../components/casefile/StageStrip.tsx";
import { LeftRail } from "../components/layout/LeftRail.tsx";
import { useRunStore } from "../store/runStore.ts";
import { useToastStore } from "../store/toastStore.ts";

export function CaseFilePage() {
  const [, params] = useRoute<{ id: string }>("/runs/:id");
  const runId = params?.id ?? null;
  const run = useRunStore((s) => (runId ? s.runs[runId] : null));
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);
  const pushToast = useToastStore((s) => s.pushToast);
  const [hydrating, setHydrating] = useState(false);
  const hydratedFor = useRef<string | null>(null);
  const sseFor = useRef<{ id: string; close: () => void } | null>(null);

  // Hydrate on cold load.
  useEffect(() => {
    if (!runId) return;
    if (run) return;
    if (hydratedFor.current === runId) return;
    hydratedFor.current = runId;
    initializeRun(runId);
    setHydrating(true);
    getRun(runId)
      .then((state) => {
        // Replace the store's state for this run with the server's view.
        useRunStore.setState((s) => {
          const existing = s.runs[runId];
          if (!existing) return s;
          return {
            runs: { ...s.runs, [runId]: { ...existing, state, done: state.decision !== null || state.error !== null } },
          };
        });
      })
      .catch((err) =>
        pushToast({
          kind: "error",
          message: `Failed to load run: ${err instanceof Error ? err.message : String(err)}`,
        }),
      )
      .finally(() => setHydrating(false));
  }, [runId, run, initializeRun, pushToast]);

  // Open SSE if run is in progress.
  useEffect(() => {
    if (!runId || !run) return;
    if (run.done) return;
    if (sseFor.current?.id === runId) return;
    sseFor.current?.close();
    const close = subscribeToRun(runId, (e) => appendEvent(runId, e));
    sseFor.current = { id: runId, close };
    return () => {
      sseFor.current?.close();
      sseFor.current = null;
    };
  }, [runId, run?.done, appendEvent]);

  if (!runId) return null;

  // Show skeleton while hydrating a fresh deep-link (prevents the "—" flash).
  if (hydrating && !run?.state.invoice) {
    return (
      <div className="flex flex-col lg:flex-row gap-6">
        <LeftRail />
        <main className="flex-1 min-w-0">
          <div className="h-6 w-48 bg-slate-200/60 rounded animate-pulse mb-4" />
          <div className="h-32 bg-slate-200/60 rounded-lg animate-pulse mb-6" />
          <div className="h-8 bg-slate-200/60 rounded animate-pulse" />
        </main>
      </div>
    );
  }

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <Breadcrumb runId={runId} />
        <HeroCard state={run?.state ?? {}} />
        <StageStrip runId={runId} />
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          Case file body (stub — sections coming in Phase 7+)
        </div>
      </main>
    </div>
  );
}
