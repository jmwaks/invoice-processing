import type { Decision, InvoiceState } from "./state.ts";

export type NodeName = "ingest" | "validate" | "approve" | "pay" | "log";

export type RunEvent =
  | { kind: "node.start"; node: NodeName; ts: string }
  | { kind: "node.complete"; node: NodeName; ts: string; output?: any }
  | { kind: "llm.call"; node: NodeName; ts: string; sub?: string; tokens_in: number; tokens_out: number; latency_ms: number; model: string }
  | { kind: "tool.call"; node: NodeName; ts: string; tool: string; args: any; result: any }
  | { kind: "approve.rules_evaluated"; node: NodeName; ts: string; evaluation: any }
  | { kind: "approve.propose.start"; node: NodeName; ts: string }
  | { kind: "approve.propose.complete"; node: NodeName; ts: string; output: any }
  | { kind: "approve.critique.start"; node: NodeName; ts: string }
  | { kind: "approve.critique.complete"; node: NodeName; ts: string; output: any }
  | { kind: "approve.finalize.start"; node: NodeName; ts: string }
  | { kind: "approve.finalize.complete"; node: NodeName; ts: string; output: any }
  | { kind: "approve.decision"; node: NodeName; ts: string; output: Decision }
  | { kind: "pay.skipped_duplicate"; node: NodeName; ts: string; output: any }
  | { kind: "log.rejection_written"; node: NodeName; ts: string; output: any }
  | { kind: "log.unprocessable_written"; node: NodeName; ts: string; output: any }
  | { kind: "run.complete"; ts: string; final_state: InvoiceState }
  | { kind: "run.error"; ts: string; error: string };
