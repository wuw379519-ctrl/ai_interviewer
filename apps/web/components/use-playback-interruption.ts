"use client";
import { useEffect, useState } from "react";
import { PlaybackInterruptionGate, rootMeanSquare } from "@aii/core";

export function usePlaybackInterruption(stream: MediaStream | null, speaking: boolean, interrupt: () => void) {
  const [enabled, setEnabled] = useState(false), [notice, setNotice] = useState("");
  useEffect(() => {
    if (!enabled || !speaking || !stream?.getAudioTracks().some((track) => track.readyState === "live" && track.enabled && !track.muted)) return;
    let closed = false, frame = 0, audio: AudioContext;
    try { audio = new AudioContext(); } catch { setNotice("声音打断暂不可用，仍可点击打断播报。"); return; }
    const gate = new PlaybackInterruptionGate(performance.now());
    let source: MediaStreamAudioSourceNode;
    try { source = audio.createMediaStreamSource(new MediaStream(stream.getAudioTracks())); }
    catch { void audio.close(); setNotice("麦克风暂不可用，仍可点击打断播报。"); return; }
    const analyser = audio.createAnalyser();
    analyser.fftSize = 1024; source.connect(analyser); const samples = new Float32Array(analyser.fftSize);
    const update = () => {
      if (closed) return;
      analyser.getFloatTimeDomainData(samples);
      if (gate.update(rootMeanSquare(samples), performance.now())) { interrupt(); setNotice("已检测到持续声音并停止播报。点击开始语音输入后才进行转写；请核对后提交。"); return; }
      frame = requestAnimationFrame(update);
    };
    void audio.resume().then(() => { if (!closed) { setNotice(""); update(); } }).catch(() => { if (!closed) setNotice("声音打断暂不可用，仍可点击打断播报。"); });
    return () => { closed = true; cancelAnimationFrame(frame); source.disconnect(); analyser.disconnect(); void audio.close(); };
  }, [stream, speaking, enabled, interrupt]);
  return { enabled, setEnabled, notice };
}
