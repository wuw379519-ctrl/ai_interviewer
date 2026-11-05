"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { createLocalRecognition, localRecognitionAvailability, recognitionConstructor, type LocalRecognition } from "@/lib/browser-speech";

export function DeviceTrial() {
  const [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [secure, setSecure] = useState(false), [local, setLocal] = useState("尚未检查，请主动点击能力检查"), [voices, setVoices] = useState(0);
  const [camera, setCamera] = useState(false), [microphone, setMicrophone] = useState(false), [level, setLevel] = useState(0), [peak, setPeak] = useState(0);
  const [listening, setListening] = useState(false), [preview, setPreview] = useState("");
  const [checking, setChecking] = useState(false), [preparing, setPreparing] = useState(false);
  const stream = useRef<MediaStream | null>(null), video = useRef<HTMLVideoElement>(null), context = useRef<AudioContext | null>(null), frame = useRef(0);
  const recognition = useRef<LocalRecognition | null>(null), voice = useRef<SpeechSynthesisVoice | null>(null), timer = useRef<ReturnType<typeof setTimeout> | null>(null), generation = useRef(0);
  const watchdog = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stop = useCallback(() => {
    generation.current++; recognition.current?.abort(); recognition.current = null; setListening(false); setChecking(false); setPreparing(false);
    if (watchdog.current) clearTimeout(watchdog.current);
    window.speechSynthesis?.cancel(); if (timer.current) clearTimeout(timer.current);
    cancelAnimationFrame(frame.current); stream.current?.getTracks().forEach((track) => track.stop()); stream.current = null;
    if (video.current) video.current.srcObject = null; void context.current?.close(); context.current = null;
    setCamera(false); setMicrophone(false); setLevel(0);
  }, []);
  useEffect(() => {
    setSecure(window.isSecureContext);
    const load = () => { const available = window.speechSynthesis?.getVoices().filter((item) => item.localService && /^zh/i.test(item.lang)) ?? []; voice.current = available[0] ?? null; setVoices(available.length); };
    load(); window.speechSynthesis?.addEventListener("voiceschanged", load);
    const hidden = () => { if (document.hidden) stop(); }; document.addEventListener("visibilitychange", hidden);
    return () => { window.speechSynthesis?.removeEventListener("voiceschanged", load); document.removeEventListener("visibilitychange", hidden); stop(); };
  }, [stop]);
  async function checkLocal() {
    if (!consent || checking) return;
    setChecking(true); setLocal("正在检查，最多等待5秒…"); const ticket = generation.current;
    try {
      const Constructor = recognitionConstructor(); if (!Constructor) throw Error("浏览器不支持设备端识别，请使用文字或配置企业转写。");
      const probe = new Constructor(); if (!("processLocally" in probe)) throw Error("不能保证设备端识别，已阻止云端回退。");
      const status = await localRecognitionAvailability(Constructor); if (ticket === generation.current) setLocal(status);
    } catch (error) { if (ticket === generation.current) setLocal(error instanceof Error ? error.message : "能力查询失败"); }
    finally { if (ticket === generation.current) setChecking(false); }
  }
  async function devices() {
    if (!consent) return; stop(); setBusy(true); setError(""); setPeak(0); const ticket = generation.current;
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw Error("需要localhost或HTTPS安全上下文。");
      const media = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      if (ticket !== generation.current) { media.getTracks().forEach((track) => track.stop()); return; }
      stream.current = media; if (video.current) video.current.srcObject = media;
      timer.current = setTimeout(stop, 120000);
      setCamera(media.getVideoTracks().some((track) => track.readyState === "live")); setMicrophone(media.getAudioTracks().some((track) => track.readyState === "live"));
      for (const track of media.getTracks()) track.onended = stop;
      const audio = new AudioContext(); context.current = audio; const source = audio.createMediaStreamSource(new MediaStream(media.getAudioTracks())), analyser = audio.createAnalyser();
      analyser.fftSize = 256; source.connect(analyser); await audio.resume(); const samples = new Uint8Array(analyser.fftSize);
      const update = () => { if (ticket !== generation.current) return; analyser.getByteTimeDomainData(samples); const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length); const percent = Math.min(100, Math.round(rms * 400)); setLevel(percent); setPeak((old) => Math.max(old, percent)); frame.current = requestAnimationFrame(update); };
      update();
    } catch (error) { stop(); setError(error instanceof Error ? error.message : "设备检测失败"); }
    finally { setBusy(false); }
  }
  async function recognize() {
    if (!consent || !microphone || preparing || listening) return; setPreparing(true); setError(""); setPreview(""); const ticket = generation.current;
    try {
      const speech = await createLocalRecognition(); if (ticket !== generation.current) return; recognition.current = speech;
      const clearWatchdog = () => { if (watchdog.current) clearTimeout(watchdog.current); };
      speech.onresult = (event) => { if (ticket !== generation.current) return; clearWatchdog(); setPreview(Array.from({ length: event.results.length }, (_, index) => event.results[index]?.[0].transcript ?? "").join("").slice(0, 4000)); };
      speech.onerror = (event) => { if (ticket === generation.current) { clearWatchdog(); setError(`本地识别：${event.error}`); setListening(false); } }; speech.onend = () => { if (ticket === generation.current) { clearWatchdog(); setListening(false); } }; speech.start(); setListening(true);
      watchdog.current = setTimeout(() => { if (ticket === generation.current) { speech.abort(); setListening(false); setError("10秒内未收到中文转写。本地识别暂不可用，请使用文字或配置企业转写服务。"); } }, 10000);
    } catch (error) { if (ticket === generation.current) setError(error instanceof Error ? error.message : "本地识别未完成"); }
    finally { if (ticket === generation.current) setPreparing(false); }
  }
  function speak() { if (!voice.current) return; const utterance = new SpeechSynthesisUtterance("这是一段语音设备联调测试，请确认能听到中文播报。"); utterance.voice = voice.current; utterance.lang = "zh-CN"; window.speechSynthesis.cancel(); window.speechSynthesis.speak(utterance); }
  return <main className="workspace" style={{ maxWidth: 960 }}><Link href="/" className="back-link">← 返回工作台</Link><p className="eyebrow">REAL DEVICE CHECK</p><h1>真实设备与中文语音联调</h1><p>这是独立本地测试。没有录音上传、没有视频上传、没有保存设备名称或试说文字。摄像头只在本机预览，输入电平只用于判断麦克风是否收到声音。离开、隐藏页面或120秒后停止设备。</p>
    <section className="panel form-panel"><h2>浏览器能力</h2><p>安全上下文：{secure ? "是" : "否"}</p><p>中文本地识别：<strong data-testid="local-recognition-capability">{local}</strong></p><p>本地中文播报声音：{voices}个</p><p className="small muted">available表示语音包可用；downloadable/downloading/unavailable表示尚不能完成本地中文识别。不自动切换浏览器云端服务。</p>
    <label className="checkbox-label"><input type="checkbox" checked={consent} onChange={(event) => { setConsent(event.target.checked); if (!event.target.checked) stop(); }} />我同意本次仅本地、不留存的设备测试</label><div className="button-row"><button className="button secondary" disabled={!consent || checking} onClick={() => void checkLocal()}>{checking ? "正在检查中文识别…" : "检查中文本地识别能力"}</button><button className="button primary" disabled={!consent || busy} onClick={() => void devices()}>开启真实摄像头与麦克风测试</button></div></section>
    <section className="panel form-panel"><h2>实际设备结果</h2><p data-testid="real-camera-state">摄像头：{camera ? "实时轨道已开启" : "已关闭"}</p><p data-testid="real-microphone-state">麦克风：{microphone ? "实时轨道已开启" : "已关闭"}</p><meter min={0} max={100} value={level} aria-label="麦克风本地输入电平" /><p>当前输入电平：{level}% · 本次峰值：<span data-testid="microphone-peak">{peak}%</span></p><video ref={video} autoPlay playsInline muted aria-label="摄像头仅本地预览" style={{ width: "100%", maxHeight: 300, background: "#17382f" }} />
    <div className="button-row"><button className="button secondary" disabled={!consent || !voices} onClick={speak}>播放本地中文测试语音</button><button className="button primary" disabled={!microphone || listening || preparing} onClick={() => void recognize()}>{preparing ? "正在检查识别能力…" : "开始本地试说"}</button><button className="button secondary" disabled={!listening} onClick={() => recognition.current?.stop()}>结束试说</button><button className="button secondary" onClick={stop}>停止所有测试设备</button></div>
    <p>试说内容：这是一段语音联调测试，我负责实验分析，处理时间降低了百分之三十。</p><p aria-live="polite">试说预览（只在本页）：{preview || "尚无转写"}</p>{error && <p className="error-banner" role="alert">{error}</p>}
    <p className="small muted">轨道开启和电平不代表识别已通过；需实际试说并核对文字。没有摄像头/麦克风或缺语音包时，请保持失败状态并联系部署者配置转写服务。</p></section>
  </main>;
}
