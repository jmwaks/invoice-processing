export type Severity = "info" | "warn" | "block";
export type SuspicionSeverity = "low" | "medium" | "high";
export type Outcome = "approved" | "rejected" | "needs_review";

export interface LineItem {
  item: string;
  quantity: number;
  unit_price: number | null;
  notes: string | null;
}

export interface InvoiceData {
  invoice_number: string | null;
  vendor: string | null;
  date: string | null;
  due_date: string | null;
  line_items: LineItem[];
  subtotal: number | null;
  tax_amount: number | null;
  total: number | null;
  currency: string;
  payment_terms: string | null;
  raw_text: string;
}

export interface SuspicionSignal {
  kind: string;
  detail: string;
  severity: SuspicionSeverity;
}

export interface ValidationIssue {
  kind: string;
  item: string | null;
  detail: string;
  severity: Severity;
}

export interface InventoryLookupRow {
  found: boolean;
  item: string;
  stock: number | null;
  unit_price: number | null;
}

export interface ValidationReport {
  issues: ValidationIssue[];
  inventory_lookups: InventoryLookupRow[];
  vendor_lookup: { found: boolean; name: string; status: string | null } | null;
}

export interface Proposal {
  outcome: Outcome;
  rationale: string;
  rules_applied: string[];
  unresolved_concerns: string[];
}

export interface Critique {
  agrees: boolean;
  objections: string[];
  missed_signals: string[];
  rule_misapplications: string[];
}

export type ToolCall = {
  tool: "lookup_inventory" | "lookup_vendor" | "recompute_totals";
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  latency_ms: number;
};

export interface Decision {
  outcome: Outcome;
  rationale: string;
  rules_applied: string[];
  initial_proposal: Proposal;
  critique: Critique;
  final_proposal: Proposal;
  tool_calls: ToolCall[];
}

export interface InvoiceState {
  run_id: string;
  source_path: string;
  file_format: "txt" | "json" | "csv" | "xml" | "pdf" | "email";
  invoice: InvoiceData | null;
  suspicion_signals: SuspicionSignal[];
  extraction_confidence: number | null;
  validation: ValidationReport | null;
  decision: Decision | null;
  payment_receipt: Record<string, unknown> | null;
  error: string | null;
}
