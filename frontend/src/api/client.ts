import type { InvoiceState } from "../types/state.ts";

export async function uploadInvoice(file: File): Promise<{ run_id: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const resp = await fetch("/api/runs", { method: "POST", body: fd });
  if (!resp.ok) throw new Error(`upload failed: ${resp.status}`);
  return resp.json();
}

export async function getInventory(): Promise<{
  inventory: { item: string; stock: number; unit_price: number }[];
  vendors: { name: string; display_name: string; status: string }[];
}> {
  const resp = await fetch("/api/inventory");
  if (!resp.ok) throw new Error("inventory fetch failed");
  return resp.json();
}

export async function listRuns(): Promise<Array<{
  run_id: string;
  source_path: string;
  invoice_number: string | null;
  vendor: string | null;
  total: number | null;
  outcome: string;
  error: string | null;
}>> {
  const resp = await fetch("/api/runs");
  if (!resp.ok) throw new Error("list runs failed");
  return resp.json();
}

export async function getRun(runId: string): Promise<InvoiceState> {
  const resp = await fetch(`/api/runs/${runId}`);
  if (!resp.ok) throw new Error("run fetch failed");
  return resp.json();
}

export async function getSource(runId: string): Promise<{ text: string; format: string }> {
  const resp = await fetch(`/api/runs/${runId}/source`);
  if (!resp.ok) throw new Error("source fetch failed");
  return resp.json();
}

export async function runBatch(): Promise<{ run_ids: string[]; total: number }> {
  const resp = await fetch("/api/runs/batch", { method: "POST" });
  if (!resp.ok) throw new Error("batch failed");
  return resp.json();
}
