/**
 * Page visibility / focus signals for Task 7 proctoring.
 * Emits only tab_hidden / window_blur — no PII.
 */

export type ProctorClientSignal =
  | { signalType: "tab_hidden"; payload: { hidden: boolean } }
  | { signalType: "window_blur"; payload: { reason: "blur" } }
  | { signalType: "answer_latency"; payload: { latencyMs: number; questionSeq?: number } };

export type ProctorEmit = (signal: ProctorClientSignal) => void;

/** Attach document visibility + window blur listeners; returns disposer. */
export function attachVisibilityProctor(emit: ProctorEmit): () => void {
  const onVisibility = () => {
    if (document.visibilityState === "hidden") {
      emit({ signalType: "tab_hidden", payload: { hidden: true } });
    }
  };
  const onBlur = () => {
    emit({ signalType: "window_blur", payload: { reason: "blur" } });
  };
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("blur", onBlur);
  return () => {
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("blur", onBlur);
  };
}

/** Elapsed ms from question shown to first candidate input. */
export function measureAnswerLatency(questionShownAt: number, now: number = Date.now()): number {
  return Math.max(0, now - questionShownAt);
}
