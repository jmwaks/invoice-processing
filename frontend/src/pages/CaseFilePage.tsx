import { useEffect, useRef, useState } from "react";
import { useRoute } from "wouter";
import { getRun } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { ActionCard } from "../components/casefile/ActionCard.tsx";
import { AgentReasoning } from "../components/casefile/AgentReasoning.tsx";
import { Breadcrumb } from "../components/casefile/Breadcrumb.tsx";
import { ExtractionReceipt } from "../components/casefile/ExtractionReceipt.tsx";
import { HeroCard } from "../components/casefile/HeroCard.tsx";
import { SourcePanel } from "../components/casefile/SourcePanel.tsx";
import { StageStrip } from "../components/casefile/StageStrip.tsx";
import { ValidationEvidence } from "../components/casefile/ValidationEvidence.tsx";
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

  useEffect(() => {
    if (!runId) return;
    if (run) return;
    if (hydratedFor.current === runId) return;
    hydratedFor.current = runId;
    initializeRun(runId);
    setHydrating(true);
    getRun(runId)
      .then((state) => {
        useRunStore.setState((s) => {
          const existing = s.runs[runId];
          if (!existing) return s;
          return {
            runs: {
              ...s.runs,
              [runId]: {
                ...existing,
                state,
                done: state.decision !== null || state.error !== null,
              },
            },
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
  const state = run?.state ?? {};
  const inv = state.invoice;

  // Show skeleton while hydrating a fresh deep-link (prevents the "—" flash).
  if (hydrating && !inv) {
    return (
      <div className="flex flex-col lg:flex-row gap-6">
        <LeftRail />
        <main className="flex-1 min-w-0">
          <div className="h-6 w-48 bg-slate-200/60 rounded animate-pulse mb-4" />
          <div className="h-32 bg-slate-200/60 rounded-lg animate-pulse mb-6" />
          <div className="h-12 bg-slate-200/60 rounded animate-pulse mb-6" />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <div className="h-64 bg-slate-200/60 rounded-lg animate-pulse" />
            <div className="h-64 bg-slate-200/60 rounded-lg animate-pulse" />
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <Breadcrumb runId={runId} />
        <HeroCard state={state} />
        <StageStrip runId={runId} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <SourcePanel runId={runId} signals={state.suspicion_signals ?? []} />
          {inv ? (
            <ExtractionReceipt runId={runId} invoice={inv} />
          ) : (
            <div className="bg-white border border-slate-200 rounded-lg p-6">
              <h3 className="text-base font-semibold mb-3">Extraction</h3>
              <p className="text-sm text-slate-400">Pending…</p>
            </div>
          )}
        </div>
        <div className="mb-6">
          <ValidationEvidence report={state.validation ?? null} />
        </div>
        <div className="mb-6">
          <AgentReasoning decision={state.decision ?? null} />
        </div>
        <div className="mb-6">
          <ActionCard state={state} />
        </div>
      </main>
    </div>
  );
}
