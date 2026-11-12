"use client";

import { useEffect, useRef } from "react";
import { REALTIME_PROTOCOL_VERSION } from "@aii/core";
import { InterviewWsClient } from "@/lib/realtime/ws-client";
import {
  attachVisibilityProctor,
  measureAnswerLatency,
  type ProctorClientSignal,
} from "./visibility";

function wsUrl(interviewId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/interview/${interviewId}`;
}

/**
 * Open a lightweight WS for proctor_signal while the candidate is interviewing.
 * Captures visibility/blur and answer_latency; server derives audio metrics itself.
 */
export function useProctorSignals(options: {
  interviewId: string;
  token: string;
  active: boolean;
  questionSeq: number | undefined;
}): void {
  const clientRef = useRef<InterviewWsClient | null>(null);
  const questionShownAt = useRef<number>(Date.now());
  const latencySentForSeq = useRef<number | null>(null);

  useEffect(() => {
    if (!options.active || !options.token) {
      clientRef.current?.close();
      clientRef.current = null;
      return;
    }
    const client = new InterviewWsClient({
      url: wsUrl(options.interviewId),
      token: options.token,
      resumeFromSeq: 0,
    });
    clientRef.current = client;
    client.connect();

    const emit = (signal: ProctorClientSignal) => {
      client.send({
        v: REALTIME_PROTOCOL_VERSION,
        type: "proctor_signal",
        signalType: signal.signalType,
        payload: signal.payload,
        t: Date.now(),
      });
    };
    const disposeVisibility = attachVisibilityProctor(emit);

    return () => {
      disposeVisibility();
      client.close();
      if (clientRef.current === client) clientRef.current = null;
    };
  }, [options.active, options.interviewId, options.token]);

  useEffect(() => {
    if (!options.active || options.questionSeq === undefined) return;
    questionShownAt.current = Date.now();
    latencySentForSeq.current = null;
  }, [options.active, options.questionSeq]);

  useEffect(() => {
    if (!options.active) return;
    const onFirstInput = () => {
      if (latencySentForSeq.current === options.questionSeq) return;
      latencySentForSeq.current = options.questionSeq ?? null;
      const latencyMs = measureAnswerLatency(questionShownAt.current);
      clientRef.current?.send({
        v: REALTIME_PROTOCOL_VERSION,
        type: "proctor_signal",
        signalType: "answer_latency",
        payload: { latencyMs, questionSeq: options.questionSeq },
        t: Date.now(),
      });
    };
    window.addEventListener("keydown", onFirstInput, { once: true });
    window.addEventListener("pointerdown", onFirstInput, { once: true });
    return () => {
      window.removeEventListener("keydown", onFirstInput);
      window.removeEventListener("pointerdown", onFirstInput);
    };
  }, [options.active, options.questionSeq]);
}
