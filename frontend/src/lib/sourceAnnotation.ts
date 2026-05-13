import type { SuspicionSignal } from "../types/state.ts";

export interface AnnotatedSegment {
  text: string;
  signal: SuspicionSignal | null;
}

export interface AnnotationResult {
  segments: AnnotatedSegment[];
  unplaced: SuspicionSignal[]; // signals whose text_match couldn't be found (or was null)
}

/**
 * Split source text into segments, marking any segments that match a
 * suspicion signal's text_match (case-insensitive, first occurrence).
 * Signals with null text_match or no match in the source are returned
 * in `unplaced` so the UI can render them as fallback chips.
 */
export function annotateSource(
  source: string,
  signals: SuspicionSignal[],
): AnnotationResult {
  if (signals.length === 0) return { segments: [{ text: source, signal: null }], unplaced: [] };

  type Hit = { start: number; end: number; signal: SuspicionSignal };
  const hits: Hit[] = [];
  const unplaced: SuspicionSignal[] = [];
  const lower = source.toLowerCase();
  const usedRanges: Array<[number, number]> = [];

  for (const sig of signals) {
    if (!sig.text_match) {
      unplaced.push(sig);
      continue;
    }
    const phrase = sig.text_match.toLowerCase();
    let idx = lower.indexOf(phrase);
    // Skip indexes that overlap an already-placed hit.
    while (idx !== -1) {
      const end = idx + phrase.length;
      const overlap = usedRanges.some(([s, e]) => idx! < e && end > s);
      if (!overlap) break;
      idx = lower.indexOf(phrase, end);
    }
    if (idx === -1) {
      unplaced.push(sig);
      continue;
    }
    const end = idx + phrase.length;
    hits.push({ start: idx, end, signal: sig });
    usedRanges.push([idx, end]);
  }

  hits.sort((a, b) => a.start - b.start);
  const segments: AnnotatedSegment[] = [];
  let cursor = 0;
  for (const h of hits) {
    if (h.start > cursor) {
      segments.push({ text: source.slice(cursor, h.start), signal: null });
    }
    segments.push({ text: source.slice(h.start, h.end), signal: h.signal });
    cursor = h.end;
  }
  if (cursor < source.length) {
    segments.push({ text: source.slice(cursor), signal: null });
  }
  return { segments, unplaced };
}
