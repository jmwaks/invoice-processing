import { useRef } from "react";
import { useLocation } from "wouter";
import { runBatch, uploadInvoice } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";
import { useToastStore } from "../../store/toastStore.ts";
import { Play, Upload } from "../common/Icons.tsx";

export function TopBar() {
  const [, setLocation] = useLocation();
  const startBatch = useRunStore((s) => s.startBatch);
  const pushToast = useToastStore((s) => s.pushToast);
  const fileRef = useRef<HTMLInputElement>(null);

  const onUploadClick = () => fileRef.current?.click();

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

  const onRunAll = async () => {
    try {
      const { run_ids } = await runBatch();
      startBatch(run_ids);
      setLocation("/");
    } catch (e) {
      pushToast({
        kind: "error",
        message: `Run all failed: ${e instanceof Error ? e.message : String(e)}`,
      });
    }
  };

  return (
    <header className="flex items-center justify-between h-12 mb-6">
      <h1 className="text-base font-semibold tracking-tight">Acme AP</h1>
      <div className="flex items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          hidden
          onChange={(e) => onFiles(e.target.files)}
        />
        <button
          onClick={onUploadClick}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-slate-200 bg-white hover:bg-slate-50"
        >
          <Upload size={16} /> Upload invoice
        </button>
        <button
          onClick={onRunAll}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          <Play size={16} /> Run all 16
        </button>
      </div>
    </header>
  );
}
