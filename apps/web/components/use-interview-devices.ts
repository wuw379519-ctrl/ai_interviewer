"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export function deviceStatus(stream: MediaStream | null) {
  const active = (kind: string) => Boolean(stream?.getTracks().some((track) => track.kind === kind && track.readyState === "live" && track.enabled && !track.muted));
  return { cameraActive: active("video"), microphoneActive: active("audio") };
}
export function useInterviewDevices() {
  const streamRef = useRef<MediaStream | null>(null), generation = useRef(0);
  const [stream, setStream] = useState<MediaStream | null>(null), [status, setStatus] = useState({ cameraActive: false, microphoneActive: false });
  const [error, setError] = useState("");
  const release = useCallback(() => {
    generation.current++;
    streamRef.current?.getTracks().forEach((track) => track.stop()); streamRef.current = null;
    setStream(null); setStatus({ cameraActive: false, microphoneActive: false });
  }, []);
  const acquire = useCallback(async (camera: boolean, microphone: boolean) => {
    release(); setError("");
    if (!camera && !microphone) return { cameraActive: false, microphoneActive: false };
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error("设备权限需要 HTTPS 或 localhost，请使用受支持的浏览器打开面试链接。");
    const ticket = generation.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const permission = navigator.mediaDevices.getUserMedia({ video: camera ? { width: { ideal: 640 }, height: { ideal: 360 }, facingMode: "user" } : false,
        audio: microphone ? { echoCancellation: true, noiseSuppression: true, channelCount: 1 } : false }).then((media) => {
        if (ticket !== generation.current) { media.getTracks().forEach((track) => track.stop()); throw new Error("设备检测已取消"); }
        return media;
      });
      const media = await Promise.race([permission, new Promise<never>((_, reject) => { timer = setTimeout(() => { generation.current++; reject(new Error("设备授权等待超时，请在浏览器中选择允许后重新检测。")); }, 20000); })]);
      streamRef.current = media; setStream(media); const active = deviceStatus(media); setStatus(active); return active;
    } catch (error) {
      const message = error instanceof DOMException && error.name === "NotAllowedError" ? "设备权限被拒绝，请在浏览器地址栏允许摄像头/麦克风，或联系招聘者安排替代方式。" :
        error instanceof DOMException && error.name === "NotFoundError" ? "没有检测到所需设备，请连接摄像头/麦克风后重试。" : error instanceof Error ? error.message : "设备不可用，请检查是否被其他程序占用。";
      setError(message); throw new Error(message);
    } finally { if (timer) clearTimeout(timer); }
  }, [release]);
  useEffect(() => { const timer = setInterval(() => setStatus(deviceStatus(streamRef.current)), 1000); return () => clearInterval(timer); }, []);
  useEffect(() => () => { generation.current++; streamRef.current?.getTracks().forEach((track) => track.stop()); }, []);
  return { stream, status, error, acquire, release };
}
