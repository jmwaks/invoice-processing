import type { RunEvent } from "../types/events.ts";

export function subscribeToRun(runId: string, onEvent: (e: RunEvent) => void): () => void {
  const es = new EventSource(`/api/runs/${runId}/events`);
  es.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as RunEvent;
      onEvent(data);
      if (data.kind === "run.complete" || data.kind === "run.error") {
        es.close();
      }
    } catch (e) {
      console.error("bad event", e, msg.data);
    }
  };
  es.onerror = () => es.close();
  return () => es.close();
}
