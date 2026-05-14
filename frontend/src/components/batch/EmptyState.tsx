import { useRef, useState } from "react";
import { useLocation } from "wouter";
import { createSampleRun, uploadInvoice } from "../../api/client.ts";
import { useToastStore } from "../../store/toastStore.ts";
import { Upload } from "../common/Icons.tsx";

const SAMPLES: Array<{ filename: string; label: string; subtitle: string }> = [
  { filename: "invoice_1001.txt", label: "INV-1001", subtitle: "Clean approval" },
  { filename: "invoice_1003.txt", label: "INV-1003", subtitle: "Fraud catch" },
  { filename: "invoice_1012.pdf", label: "INV-1012", subtitle: "OCR resilience" },
];

export function EmptyState() {
  const [, setLocation] = useLocation();
  const [pending, setPending] = useState<string | null>(null);
  const pushToast = useToastStore((s) => s.pushToast);
  const fileRef = useRef<HTMLInputElement>(null);

  const onSample = async (filename: string) => {
    setPending(filename);
    try {
      const { run_id } = await createSampleRun(filename);
      setLocation(`/runs/${run_id}`);
    } catch (e) {
      pushToast({
        kind: "error",
        message: `Sample run failed: ${e instanceof Error ? e.message : String(e)}`,
      });
    } finally {
      setPending(null);
    }
  };

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    try {
      const { run_id } = await uploadInvoice(files[0]);
      setLocation(`/runs/${run_id}`);
    } catch (e) {
      pushToast({
        kind: "error",
        message: `Upload failed: ${e instanceof Error ? e.message : String(e)}`,
      });
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-12 text-center">
      <h2 className="text-xl font-semibold mb-2">Process your first invoice</h2>
      <p className="text-sm text-slate-500 mb-8">
        Drop a file or try a sample to see the agents work.
      </p>
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onFiles(e.dataTransfer.files);
        }}
        onClick={() => fileRef.current?.click()}
        className="border-2 border-dashed border-slate-300 rounded-lg py-12 mb-8 cursor-pointer hover:border-indigo-400 hover:bg-slate-50"
      >
        <input
          ref={fileRef}
          type="file"
          hidden
          onChange={(e) => onFiles(e.target.files)}
        />
        <Upload size={24} className="mx-auto text-slate-400 mb-2" />
        <p className="text-sm text-slate-500">Drag an invoice here or click to upload</p>
      </div>
      <p className="text-xs uppercase tracking-wide text-slate-500 mb-3">
        Or try a sample
      </p>
      <div className="grid grid-cols-3 gap-3">
        {SAMPLES.map((s) => (
          <button
            key={s.filename}
            onClick={() => onSample(s.filename)}
            disabled={pending !== null}
            className="border border-slate-200 rounded-lg p-4 text-left hover:border-indigo-400 hover:bg-slate-50 disabled:opacity-50"
          >
            <div className="font-mono text-sm font-semibold">{s.label}</div>
            <div className="text-xs text-slate-500 mt-1">{s.subtitle}</div>
            {pending === s.filename && (
              <div className="text-xs text-indigo-600 mt-2">Starting…</div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
