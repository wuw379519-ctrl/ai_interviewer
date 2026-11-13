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

export type MediaDegradeReason = "permission_denied" | "track_ended" | "insecure_context" | null;

function wsUrl(interviewId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/interview/${interviewId}`;
}

/** Pure helper — used by tests and the capture loop. */
export function shouldRequestMedia(enabled: boolean, hasExternalStream: boolean): boolean {
  return enabled && !hasExternalStream;
}

export function mediaDegradeMessage(reason: MediaDegradeReason): string {
  if (reason === "permission_denied") return "摄像头权限被拒绝，已降级为无视频预览；语音/文字仍可继续。";
  if (reason === "track_ended") return "摄像头已断开（可能被拔出），已停止发送视频帧；请重新开启设备。";
  if (reason === "insecure_context") return "摄像头需要 HTTPS 或 localhost 安全上下文。";
  return "";
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
  const activeStreamRef = useRef<MediaStream | null>(stream);
  const [status, setStatus] = useState<WsClientStatus>("idle");
  const [avatarReady, setAvatarReady] = useState(false);
  const [degradeReason, setDegradeReason] = useState<MediaDegradeReason>(null);
  const [framesSent, setFramesSent] = useState(0);
  const [activeStream, setActiveStream] = useState<MediaStream | null>(stream);
  const [cameraStallNotice, setCameraStallNotice] = useState("");

  useEffect(() => {
    activeStreamRef.current = stream;
    setActiveStream(stream);
  }, [stream]);

  useEffect(() => {
    activeStreamRef.current = activeStream;
  }, [activeStream]);

  const emitCameraLost = (reason: string) => {
    clientRef.current?.send({
      v: REALTIME_PROTOCOL_VERSION,
      type: "proctor_signal",
      signalType: "camera_lost",
      payload: { reason },
      t: Date.now(),
    });
  };

  const attachTrackEnded = (media: MediaStream) => {
    for (const track of media.getVideoTracks()) {
      track.addEventListener("ended", () => {
        setDegradeReason("track_ended");
        setActiveStream(null);
        emitCameraLost("track_ended");
      });
    }
  };

  const acquireOwned = async (): Promise<MediaStream | null> => {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setDegradeReason("insecure_context");
      return null;
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 360 }, facingMode: "user" },
        audio: true,
      });
      ownedStreamRef.current = media;
      attachTrackEnded(media);
      setDegradeReason(null);
      setActiveStream(media);
      return media;
    } catch {
      setDegradeReason("permission_denied");
      emitCameraLost("permission_denied");
      return null;
    }
  };

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const acquire = async () => {
      if (stream) {
        attachTrackEnded(stream);
        setActiveStream(stream);
        setDegradeReason(null);
        return;
      }
      if (!shouldRequestMedia(true, false)) return;
      const media = await acquireOwned();
      if (cancelled && media) {
        media.getTracks().forEach((track) => track.stop());
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
    let previous: WsClientStatus = "idle";
    const client = new InterviewWsClient({
      url: wsUrl(interviewId),
      token,
      onStatus: (next) => {
        setStatus(next);
        // Reconnect: re-init camera if the prior stream died.
        if (next === "open" && previous === "reconnecting" && !activeStreamRef.current && !stream) {
          void acquireOwned();
        }
        previous = next;
      },
      onMessage: (message: RealtimeServerMessage) => {
        if (message.type === "avatar_ready") setAvatarReady(true);
        if (message.type === "state_changed" && message.detail?.via === "camera_stall") {
          setCameraStallNotice("服务端超过 10 秒未收到视频帧，已记录摄像头断流提示。");
        }
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
  }, [enabled, interviewId, token, stream]);

  useEffect(() => {
    if (!enabled || !activeStream || degradeReason) return;
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
  }, [enabled, activeStream, fps, degradeReason]);

  const degradeText = mediaDegradeMessage(degradeReason);

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
          {!activeStream && (
            <span className="camera-placeholder" data-testid="camera-degraded">
              {degradeText || "等待摄像头权限…"}
            </span>
          )}
          <span className="camera-caption">本机预览 · 约 {fps}fps JPEG 帧经 WS 发送供防作弊扩展</span>
        </div>
      </div>
      <p className="small muted" role="status" data-testid="video-room-status">
        通道：{status} · 已发送帧 {framesSent}
        {degradeText ? ` · ${degradeText}` : ""}
        {cameraStallNotice ? ` · ${cameraStallNotice}` : ""}
      </p>
      {degradeReason && (
        <button
          type="button"
          className="button secondary"
          data-testid="retry-camera"
          onClick={() => {
            void acquireOwned();
          }}
        >
          重新开启摄像头
        </button>
      )}
    </section>
  );
}
