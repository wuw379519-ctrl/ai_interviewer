"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { encodePcmWave } from "@aii/core";
import { api } from "@/lib/client-api";
import { questionAudio } from "@/lib/question-audio";
import { createLocalRecognition, recognitionConstructor, type LocalRecognition } from "@/lib/browser-speech";

export function useInterviewSpeech(options: { id: string; token: string; stream: MediaStream | null; server: boolean; edge?: boolean; questionSeq?: number; turnSeq?: number; draft: string; setDraft: (text: string) => void }) {
  const [listening, setListening] = useState(false), [transcribing, setTranscribing] = useState(false), [speaking, setSpeaking] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState(""), [hasVoice, setHasVoice] = useState(false);
  const recognition = useRef<LocalRecognition | null>(null), recorder = useRef<MediaRecorder | null>(null), canceled = useRef(false);
  const abort = useRef<AbortController | null>(null), voice = useRef<SpeechSynthesisVoice | null>(null), timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
  const watchdog = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playback = useRef<HTMLAudioElement | null>(null), playbackURL = useRef<string | null>(null), playbackAbort = useRef<AbortController | null>(null), playbackGeneration = useRef(0);
  const position = useRef(options); position.current = options;
  const { id, token, edge = false } = options;
  const stopPlayback = useCallback(() => {
    playbackGeneration.current++; playbackAbort.current?.abort(); playbackAbort.current = null;
    if (playback.current) { playback.current.pause(); playback.current.removeAttribute("src"); playback.current.load(); playback.current = null; }
    if (playbackURL.current) URL.revokeObjectURL(playbackURL.current); playbackURL.current = null;
    window.speechSynthesis?.cancel(); setSpeaking(false);
  }, []);
  const cancel = useCallback(() => {
    generation.current++;
    canceled.current = true; recognition.current?.abort(); recognition.current = null;
    if (recorder.current?.state === "recording") recorder.current.stop(); recorder.current = null;
    abort.current?.abort(); if (timer.current) clearTimeout(timer.current); if (watchdog.current) clearTimeout(watchdog.current);
    setListening(false); setTranscribing(false); setPreparing(false); stopPlayback();
  }, [stopPlayback]);
  useEffect(() => () => cancel(), [cancel]);
  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const load = () => { voice.current = window.speechSynthesis.getVoices().find((item) => item.localService && /^zh/i.test(item.lang)) ?? null; setHasVoice(Boolean(voice.current)); };
    load(); window.speechSynthesis.addEventListener("voiceschanged", load);
    return () => { window.speechSynthesis.removeEventListener("voiceschanged", load); cancel(); };
  }, [cancel]);
  const speak = useCallback((text: string) => {
    stopPlayback(); setError("");
    const ticket = playbackGeneration.current;
    if (edge) {
      const { questionSeq, turnSeq } = position.current;
      if (!questionSeq || !turnSeq) { setError("题目尚未就绪，请稍后重试播报。"); return; }
      const controller = new AbortController(); playbackAbort.current = controller; setSpeaking(true);
      void (async () => {
        try {
          const blob = await questionAudio(id, token, questionSeq, turnSeq, controller.signal);
          if (ticket !== playbackGeneration.current) return;
          const url = URL.createObjectURL(blob), audio = new Audio(url); playbackURL.current = url; playback.current = audio;
          audio.onended = () => { if (ticket === playbackGeneration.current) stopPlayback(); };
          audio.onerror = () => { if (ticket === playbackGeneration.current) { stopPlayback(); setError("播报无法播放，请阅读文字题目。"); } };
          await audio.play();
        } catch (error) {
          if (ticket === playbackGeneration.current) { stopPlayback(); setError(error instanceof Error ? error.message : "播报失败，请阅读文字题目。"); }
        }
      })();
      return;
    }
    if (!voice.current) { setError("没有检测到本地中文语音，题目文字仍可阅读。可在系统设置中安装中文语音包。"); return; }
    const utterance = new SpeechSynthesisUtterance(text); utterance.voice = voice.current; utterance.lang = "zh-CN"; utterance.rate = 0.95;
    utterance.onend = () => { if (ticket === playbackGeneration.current) setSpeaking(false); }; utterance.onerror = utterance.onend;
    setSpeaking(true); window.speechSynthesis.speak(utterance);
  }, [stopPlayback, id, token, edge]);
  async function start() {
    if (preparing || listening || transcribing) return;
    stopPlayback(); setError(""); canceled.current = false;
    const ticket = ++generation.current;
    const base = options.draft.trim();
    try {
      if (!options.stream?.getAudioTracks().some((track) => track.readyState === "live" && track.enabled && !track.muted)) throw new Error("请先开启并检测麦克风。");
      if (!options.server) {
        setPreparing(true);
        const local = await createLocalRecognition();
        if (canceled.current || ticket !== generation.current) return;
        recognition.current = local; let final = "";
        local.onresult = (event) => {
          if (canceled.current || ticket !== generation.current) return;
          if (watchdog.current) clearTimeout(watchdog.current);
          let interim = "";
          for (let index = event.resultIndex; index < event.results.length; index++) {
            const item = event.results[index]; if (!item) continue;
            if (item.isFinal) final += item[0].transcript; else interim += item[0].transcript;
          }
          options.setDraft([base, final + interim].filter(Boolean).join("\n").slice(0, 4000));
        };
        local.onerror = (event) => { if (!canceled.current && ticket === generation.current) { if (watchdog.current) clearTimeout(watchdog.current); setError(`本地识别未完成（${event.error}），可重试或改用文字。`); setListening(false); } };
        local.onend = () => { if (ticket === generation.current) { setListening(false); if (timer.current) clearTimeout(timer.current); if (watchdog.current) clearTimeout(watchdog.current); } }; local.start(); setListening(true);
        watchdog.current = setTimeout(() => { if (!canceled.current && ticket === generation.current) { local.abort(); setListening(false); setError("10秒内未收到转写，请确认已试说。可改用文字或联系招聘者，不会静默转云端。"); } }, 10000);
        timer.current = setTimeout(() => local.stop(), 120000);
        return;
      }
      if (!("MediaRecorder" in window)) throw new Error("浏览器不支持音频录制，可改用文字。");
      const audioOnly = new MediaStream(options.stream.getAudioTracks());
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4"].find((mime) => MediaRecorder.isTypeSupported(mime));
      const recording = new MediaRecorder(audioOnly, mimeType ? { mimeType, audioBitsPerSecond: 64000 } : undefined), chunks: Blob[] = [];
      recorder.current = recording;
      recording.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recording.onstop = () => {
        if (canceled.current || ticket !== generation.current) { chunks.length = 0; return; }
        setListening(false); if (timer.current) clearTimeout(timer.current);
        void (async () => {
          setTranscribing(true); const context = new AudioContext();
          try {
            const decoded = await context.decodeAudioData(await new Blob(chunks).arrayBuffer()); chunks.length = 0;
            if (decoded.duration > 120) throw new Error("单段音频超过120秒，请分段回答。");
            const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * 16000)), 16000), source = offline.createBufferSource();
            source.buffer = decoded; source.connect(offline.destination); source.start();
            const pcm = await offline.startRendering();
            if (canceled.current || ticket !== generation.current) return;
            const form = new FormData(); form.set("audio", new Blob([encodePcmWave(pcm.getChannelData(0))], { type: "audio/wav" }), "answer.wav");
            abort.current = new AbortController();
            const result = await api(`/api/interviews/${options.id}/transcribe`, z.object({ text: z.string().max(4000) }), {
              method: "POST", token: options.token, body: form, key: crypto.randomUUID(), signal: abort.current.signal });
            if (!canceled.current && ticket === generation.current) options.setDraft([base, result.text].filter(Boolean).join("\n").slice(0, 4000));
          } catch (error) { if (!canceled.current && ticket === generation.current) setError(error instanceof Error ? error.message : "转写失败，可改用文字。"); }
          finally { await context.close(); if (ticket === generation.current) setTranscribing(false); }
        })();
      };
      recording.start(1000); setListening(true); timer.current = setTimeout(() => recording.stop(), 119000);
    } catch (error) { if (ticket === generation.current) { setError(error instanceof Error ? error.message : "语音不可用"); setListening(false); } }
    finally { if (ticket === generation.current) setPreparing(false); }
  }
  function stop() { if (timer.current) clearTimeout(timer.current); recognition.current?.stop(); if (recorder.current?.state === "recording") recorder.current.stop(); }
  async function install() {
    setError("");
    try {
      const Constructor = recognitionConstructor();
      if (!Constructor?.install || !await Constructor.install({ langs: ["zh-CN"], processLocally: true })) throw new Error("此浏览器暂不能安装中文离线语音包，可使用企业转写服务或改用文字。");
      setError("离线语音包已就绪，可开始语音输入。");
    } catch (error) { setError(error instanceof Error ? error.message : "语音包安装未完成"); }
  }
  return { listening, transcribing, preparing, speaking, error, hasVoice: edge || hasVoice, start, stop, cancel, speak, stopPlayback, install };
}
