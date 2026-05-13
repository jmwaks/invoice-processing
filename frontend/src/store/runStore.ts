import { create } from "zustand";
import type { RunEvent } from "../types/events.ts";
import type { Decision, InvoiceState } from "../types/state.ts";

type NodeStatus = "pending" | "running" | "complete" | "error";

interface NodeStageView {
  status: NodeStatus;
  startedAt?: string;
  completedAt?: string;
  summary?: any;
}

interface ApproveSubStages {
  propose: NodeStatus;
  critique: NodeStatus;
  finalize: NodeStatus;
}

export interface ActiveRunView {
  runId: string;
  events: RunEvent[];
  stages: Record<"ingest" | "validate" | "approve" | "pay" | "log", NodeStageView>;
  approveSubStages: ApproveSubStages;
  state: Partial<InvoiceState>;
  done: boolean;
}

interface Store {
  activeRunId: string | null;
  runs: Record<string, ActiveRunView>;
  selectRun: (runId: string) => void;
  appendEvent: (runId: string, e: RunEvent) => void;
  initializeRun: (runId: string) => void;
}

const emptyStages = (): ActiveRunView["stages"] => ({
  ingest: { status: "pending" },
  validate: { status: "pending" },
  approve: { status: "pending" },
  pay: { status: "pending" },
  log: { status: "pending" },
});

export const useRunStore = create<Store>((set, get) => ({
  activeRunId: null,
  runs: {},
  selectRun: (runId) => set({ activeRunId: runId }),
  initializeRun: (runId) =>
    set((s) => ({
      activeRunId: runId,
      runs: {
        ...s.runs,
        [runId]: {
          runId,
          events: [],
          stages: emptyStages(),
          approveSubStages: { propose: "pending", critique: "pending", finalize: "pending" },
          state: { run_id: runId },
          done: false,
        },
      },
    })),
  appendEvent: (runId, e) => {
    const current = get().runs[runId];
    if (!current) {
      get().initializeRun(runId);
    }
    set((s) => {
      const r = { ...(s.runs[runId] ?? { runId, events: [], stages: emptyStages(),
        approveSubStages: { propose: "pending", critique: "pending", finalize: "pending" },
        state: { run_id: runId }, done: false }) };
      r.events = [...r.events, e];
      if (e.kind === "node.start") r.stages[e.node].status = "running";
      if (e.kind === "node.complete") {
        r.stages[e.node].status = "complete";
        r.stages[e.node].summary = e.output;
      }
      if (e.kind === "approve.propose.start") r.approveSubStages.propose = "running";
      if (e.kind === "approve.propose.complete") r.approveSubStages.propose = "complete";
      if (e.kind === "approve.critique.start") r.approveSubStages.critique = "running";
      if (e.kind === "approve.critique.complete") r.approveSubStages.critique = "complete";
      if (e.kind === "approve.finalize.start") r.approveSubStages.finalize = "running";
      if (e.kind === "approve.finalize.complete") r.approveSubStages.finalize = "complete";
      if (e.kind === "approve.decision") r.state.decision = e.output as Decision;
      if (e.kind === "run.complete") {
        r.state = e.final_state;
        r.done = true;
      }
      if (e.kind === "run.error") r.done = true;
      return { runs: { ...s.runs, [runId]: r } };
    });
  },
}));
