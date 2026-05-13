import { useCallback, useState } from "react";
import { uploadInvoice } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { useRunStore } from "../store/runStore.ts";

export function UploadZone() {
  const [drag, setDrag] = useState(false);
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);

  const onFiles = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const file = files[0];
    const { run_id } = await uploadInvoice(file);
    initializeRun(run_id);
    subscribeToRun(run_id, (e) => appendEvent(run_id, e));
  }, [initializeRun, appendEvent]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); onFiles(e.dataTransfer.files); }}
      className={`border-2 border-dashed rounded p-6 text-center text-sm cursor-pointer transition
        ${drag ? "border-amber-400 bg-amber-50" : "border-slate-300 bg-white"}`}
      onClick={() => document.getElementById("file-input")?.click()}
    >
      <input id="file-input" type="file" hidden onChange={(e) => onFiles(e.target.files)} />
      Drag an invoice here or click to upload
    </div>
  );
}
