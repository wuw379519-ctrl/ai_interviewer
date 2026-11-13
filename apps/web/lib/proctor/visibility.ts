/**
 * Page visibility / focus / camera signals for Task 7 / 9b proctoring.
 * Emits only non-PII telemetry.
 */

export type ProctorClientSignal =
  | { signalType: "tab_hidden"; payload: { hidden: boolean } }
  | { signalType: "window_blur"; payload: { reason: "blur" } }
  | { signalType: "answer_latency"; payload: { latencyMs: number; questionSeq?: number } }
  | { signalType: "camera_lost"; payload: { reason: string } };

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

/** Watch MediaStream video tracks; emit camera_lost when a track ends. */
export function attachCameraLostProctor(
  stream: MediaStream | null | undefined,
  emit: ProctorEmit,
): () => void {
  if (!stream) return () => undefined;
  const onEnded = () => {
    emit({ signalType: "camera_lost", payload: { reason: "track_ended" } });
  };
  const tracks = stream.getVideoTracks();
  for (const track of tracks) track.addEventListener("ended", onEnded);
  return () => {
    for (const track of tracks) track.removeEventListener("ended", onEnded);
  };
}

/** Elapsed ms from question shown to first candidate input. */
export function measureAnswerLatency(questionShownAt: number, now: number = Date.now()): number {
  return Math.max(0, now - questionShownAt);
}
