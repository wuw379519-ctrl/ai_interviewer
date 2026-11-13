"use client";

import { useEffect, useRef, useState } from "react";
import { REALTIME_PROTOCOL_VERSION, type RealtimeServerMessage } from "@aii/core";
import { InterviewWsClient, type WsClientStatus } from "@/lib/realtime/ws-client";

export type VideoInterviewRoomProps = {
  interviewId: string;
  token: string;
  /** Existing device stream from useInterviewDevices; if null, component requests getUserMedia. */
  stream?: MediaStream | null;
  enabled?: boolean;
  /** Target capture rate (default 5 fps). */
  fps?: number;
};

function wsUrl(interviewId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/interview/${interviewId}`;
}

/** Pure helper — used by tests and the capture loop. */
export function shouldRequestMedia(enabled: boolean, hasExternalStream: boolean): boolean {
  return enabled && !hasExternalStream;
}

/** Draw the current video frame to JPEG base64 (no data: prefix). */
export function captureVideoFrameBase64(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  quality = 0.7,
): string | null {
  if (!video.videoWidth || !video.videoHeight) return null;
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  const dataUrl = canvas.toDataURL("image/jpeg", quality);
  const marker = "base64,";
  const index = dataUrl.indexOf(marker);
  if (index < 0) return null;
  return dataUrl.slice(index + marker.length);
}

export function VideoInterviewRoom({
  interviewId,
  token,
  stream = null,
  enabled = true,
  fps = 5,
}: VideoInterviewRoomProps) {
  const selfVideoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const clientRef = useRef<InterviewWsClient | null>(null);
  const seqRef = useRef(0);
  const ownedStreamRef = useRef<MediaStream | null>(null);
  const [status, setStatus] = useState<WsClientStatus>("idle");
  const [avatarReady, setAvatarReady] = useState(false);
  const [permissionError, setPermissionError] = useState("");
  const [framesSent, setFramesSent] = useState(0);
  const [activeStream, setActiveStream] = useState<MediaStream | null>(stream);

  useEffect(() => {
    setActiveStream(stream);
  }, [stream]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const acquire = async () => {
      if (stream) {
        setActiveStream(stream);
        return;
      }
      if (!shouldRequestMedia(true, false)) return;
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setPermissionError("摄像头需要 HTTPS 或 localhost 安全上下文。");
        return;
      }
      try {
        const media = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 360 }, facingMode: "user" },
          audio: true,
        });
        if (cancelled) {
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        ownedStreamRef.current = media;
        setActiveStream(media);
        setPermissionError("");
      } catch (error: unknown) {
        setPermissionError(error instanceof Error ? error.message : "无法获取摄像头/麦克风权限");
      }
    };
    void acquire();
    return () => {
      cancelled = true;
      ownedStreamRef.current?.getTracks().forEach((track) => track.stop());
      ownedStreamRef.current = null;
    };
  }, [enabled, stream, interviewId]);

  useEffect(() => {
    const video = selfVideoRef.current;
    if (video) video.srcObject = activeStream;
  }, [activeStream]);

  useEffect(() => {
    if (!enabled || !token) return;
    const client = new InterviewWsClient({
      url: wsUrl(interviewId),
      token,
      onStatus: setStatus,
      onMessage: (message: RealtimeServerMessage) => {
        if (message.type === "avatar_ready") setAvatarReady(true);
        if (message.type === "tts_chunk" && message.audioBase64) {
          try {
            const binary = atob(message.audioBase64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
            const blob = new Blob([bytes], { type: "audio/wav" });
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            void audio.play().finally(() => URL.revokeObjectURL(url));
          } catch {
            /* ignore decode/play errors */
          }
        }
      },
    });
    clientRef.current = client;
    client.connect();
    return () => {
      client.close("video-room-unmount");
      clientRef.current = null;
    };
  }, [enabled, interviewId, token]);

  useEffect(() => {
    if (!enabled || !activeStream) return;
    const intervalMs = Math.max(200, Math.round(1000 / Math.max(1, fps)));
    const timer = window.setInterval(() => {
      const video = selfVideoRef.current;
      const canvas = canvasRef.current;
      const client = clientRef.current;
      if (!video || !canvas || !client) return;
      const frame = captureVideoFrameBase64(video, canvas);
      if (!frame) return;
      const seq = seqRef.current;
      seqRef.current += 1;
      client.send({
        v: REALTIME_PROTOCOL_VERSION,
        type: "video_chunk",
        seq,
        frameBase64: frame,
        format: "jpeg",
        width: video.videoWidth || undefined,
        height: video.videoHeight || undefined,
        t: Date.now(),
      });
      setFramesSent((count) => count + 1);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [enabled, activeStream, fps]);

  return (
    <section className="panel video-interview-room" aria-label="视频语音面试">
      <div className="video-interview-layout">
        <div className="video-avatar-stage" data-testid="avatar-stage">
          <div className="video-avatar-placeholder" aria-live="polite">
            {avatarReady ? "AI 面试官已就绪（音频 / 形象占位）" : "正在连接 AI 面试官…"}
          </div>
          <p className="small muted">主展示区预留数字人/动画；当前以 TTS 音频回推为主。</p>
        </div>
        <div className="video-self-preview">
          <video ref={selfVideoRef} autoPlay playsInline muted aria-label="候选人本地预览" data-testid="self-preview" />
          <canvas ref={canvasRef} className="video-capture-canvas" aria-hidden="true" />
          {!activeStream && <span className="camera-placeholder">等待摄像头权限…</span>}
          <span className="camera-caption">本机预览 · 约 {fps}fps JPEG 帧经 WS 发送供防作弊扩展</span>
        </div>
      </div>
      <p className="small muted" role="status" data-testid="video-room-status">
        通道：{status} · 已发送帧 {framesSent}
        {permissionError ? ` · ${permissionError}` : ""}
      </p>
    </section>
  );
}
