import { useEffect, useRef, useState } from "react";
import { useRunStore } from "../store/runStore.ts";
import { getSource } from "../api/client.ts";
import type { InvoiceData, LineItem } from "../types/state.ts";
import { RetryButton } from "./RetryButton.tsx";

function emptyDraft(): InvoiceData {
  return {
    invoice_number: null,
    vendor: null,
    date: null,
    due_date: null,
    line_items: [],
    subtotal: null,
    tax_amount: null,
    total: null,
    currency: "USD",
    payment_terms: null,
    raw_text: "",
  };
}

function cloneDraft(inv: InvoiceData): InvoiceData {
  return { ...inv, line_items: inv.line_items.map((li) => ({ ...li })) };
}

function ScalarField({
  label,
  value,
  type = "text",
  onChange,
}: {
  label: string;
  value: string;
  type?: "text" | "number" | "date";
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] uppercase tracking-wider text-slate-500">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border rounded px-2 py-0.5 text-xs font-mono"
      />
    </div>
  );
}

function LineItemRow({
  item,
  index,
  onChange,
  onRemove,
}: {
  item: LineItem;
  index: number;
  onChange: (index: number, updated: LineItem) => void;
  onRemove: (index: number) => void;
}) {
  const set = (patch: Partial<LineItem>) => onChange(index, { ...item, ...patch });
  return (
    <div className="flex gap-1 items-center">
      <input
        type="text"
        value={item.item}
        placeholder="item"
        onChange={(e) => set({ item: e.target.value })}
        className="border rounded px-2 py-0.5 text-xs font-mono flex-1"
      />
      <input
        type="number"
        value={item.quantity ?? ""}
        placeholder="qty"
        onChange={(e) => {
          const v = e.target.value;
          if (v === "") return; // ignore empty — leave previous value
          set({ quantity: parseFloat(v) });
        }}
        className="border rounded px-2 py-0.5 text-xs font-mono w-16"
      />
      <input
        type="number"
        value={item.unit_price ?? ""}
        placeholder="price"
        onChange={(e) => set({ unit_price: parseFloat(e.target.value) || null })}
        className="border rounded px-2 py-0.5 text-xs font-mono w-20"
      />
      <button
        type="button"
        onClick={() => onRemove(index)}
        className="text-xs text-rose-600 hover:underline shrink-0"
      >
        Remove
      </button>
    </div>
  );
}

export function SourceAndExtraction() {
  const activeId = useRunStore((s) => s.activeRunId);
  const run = useRunStore((s) => (activeId ? s.runs[activeId] : null));
  const selectRun = useRunStore((s) => s.selectRun);
  const [source, setSource] = useState<string>("");
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<InvoiceData | null>(null);
  const keysRef = useRef<string[]>([]);

  useEffect(() => {
    if (!activeId) return;
    getSource(activeId).then((s) => setSource(s.text)).catch(() => setSource(""));
  }, [activeId]);

  const inv = run?.state.invoice ?? null;

  useEffect(() => {
    setDraft(inv ? cloneDraft(inv) : null);
    setIsEditing(false);
  }, [inv]);

  // Keep keys array length aligned with draft.line_items
  useEffect(() => {
    const needed = draft?.line_items.length ?? 0;
    while (keysRef.current.length < needed) {
      keysRef.current.push(crypto.randomUUID());
    }
    if (keysRef.current.length > needed) {
      keysRef.current.length = needed;
    }
  }, [draft?.line_items.length]);

  if (!run) return null;

  const runId = run.state.run_id;
  const parentRunId = run.state.parent_run_id ?? null;
  const signals = run.state.suspicion_signals ?? [];
  const canEdit = !!inv && !!runId;

  const handleRetried = (newRunId: string) => {
    setIsEditing(false);
    selectRun(newRunId);
  };

  const updateLineItem = (index: number, updated: LineItem) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const items = [...prev.line_items];
      items[index] = updated;
      return { ...prev, line_items: items };
    });
  };

  const removeLineItem = (index: number) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, line_items: prev.line_items.filter((_, i) => i !== index) };
    });
  };

  const addLineItem = () => {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        line_items: [...prev.line_items, { item: "", quantity: 1, unit_price: null, notes: null }],
      };
    });
  };

  const setScalar = <K extends keyof InvoiceData>(key: K, raw: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const numKeys: (keyof InvoiceData)[] = ["subtotal", "tax_amount", "total"];
      const value = numKeys.includes(key)
        ? raw === "" ? null : (parseFloat(raw) as InvoiceData[K])
        : (raw as InvoiceData[K]);
      return { ...prev, [key]: value };
    });
  };

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Raw source panel */}
      <div className="bg-white border rounded p-3">
        <h3 className="font-semibold text-sm mb-2">Raw</h3>
        <pre className="text-xs font-mono whitespace-pre-wrap break-words max-h-80 overflow-auto">
          {source || "—"}
        </pre>
      </div>

      {/* Extracted / edit panel */}
      <div className="bg-white border rounded p-3">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold text-sm">Extracted</h3>
          {canEdit && !isEditing && (
            <button
              type="button"
              onClick={() => {
                setDraft(inv ? cloneDraft(inv) : emptyDraft());
                setIsEditing(true);
              }}
              className="text-xs px-2 py-0.5 border rounded hover:bg-slate-50"
            >
              Edit
            </button>
          )}
          {isEditing && (
            <button
              type="button"
              onClick={() => setIsEditing(false)}
              className="text-xs text-slate-500 hover:underline"
            >
              Cancel
            </button>
          )}
        </div>

        {!isEditing && (
          <>
            {inv ? (
              <pre className="text-xs font-mono whitespace-pre-wrap max-h-80 overflow-auto">
                {JSON.stringify(inv, null, 2)}
              </pre>
            ) : (
              <div className="text-slate-400 text-sm">Pending…</div>
            )}
            {signals.length > 0 && (
              <div className="mt-2 space-x-1">
                {signals.map((s, i) => (
                  <span
                    key={i}
                    className="inline-block text-xs px-2 py-0.5 rounded bg-rose-100 text-rose-800"
                    title={s.detail}
                  >
                    {s.kind} ({s.severity})
                  </span>
                ))}
              </div>
            )}
          </>
        )}

        {isEditing && draft && runId && (
          <div className="space-y-2 max-h-96 overflow-auto pr-1">
            <ScalarField
              label="Invoice #"
              value={draft.invoice_number ?? ""}
              onChange={(v) => setScalar("invoice_number", v)}
            />
            <ScalarField
              label="Vendor"
              value={draft.vendor ?? ""}
              onChange={(v) => setScalar("vendor", v)}
            />
            <ScalarField
              label="Date"
              value={draft.date ?? ""}
              type="date"
              onChange={(v) => setScalar("date", v)}
            />
            <ScalarField
              label="Due date"
              value={draft.due_date ?? ""}
              type="date"
              onChange={(v) => setScalar("due_date", v)}
            />
            <ScalarField
              label="Currency"
              value={draft.currency}
              onChange={(v) => setScalar("currency", v)}
            />
            <ScalarField
              label="Payment terms"
              value={draft.payment_terms ?? ""}
              onChange={(v) => setScalar("payment_terms", v)}
            />
            <ScalarField
              label="Subtotal"
              value={draft.subtotal?.toString() ?? ""}
              type="number"
              onChange={(v) => setScalar("subtotal", v)}
            />
            <ScalarField
              label="Tax amount"
              value={draft.tax_amount?.toString() ?? ""}
              type="number"
              onChange={(v) => setScalar("tax_amount", v)}
            />
            <ScalarField
              label="Total"
              value={draft.total?.toString() ?? ""}
              type="number"
              onChange={(v) => setScalar("total", v)}
            />

            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                Line items
              </div>
              <div className="space-y-1">
                {draft.line_items.map((li, i) => (
                  <LineItemRow
                    key={keysRef.current[i] ?? i}
                    item={li}
                    index={i}
                    onChange={updateLineItem}
                    onRemove={removeLineItem}
                  />
                ))}
              </div>
              <button
                type="button"
                onClick={addLineItem}
                className="mt-1 text-xs text-slate-600 hover:underline"
              >
                + Add line
              </button>
            </div>

            <div className="pt-1 border-t">
              <RetryButton
                parentRunId={runId}
                invoice={draft}
                onRetried={handleRetried}
              />
            </div>
          </div>
        )}
      </div>

      {/* Parent-run chip — shown below both panels when this is a retry */}
      {parentRunId && (
        <div className="col-span-2">
          <button
            type="button"
            onClick={() => selectRun(parentRunId)}
            className="text-xs px-2 py-0.5 bg-slate-100 rounded border hover:bg-slate-200"
          >
            ↩ Retry of {parentRunId.slice(0, 8)}
          </button>
        </div>
      )}
    </div>
  );
}
