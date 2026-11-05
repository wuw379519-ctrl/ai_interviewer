"use client";
import { useEffect, useRef } from "react";
import type { InterviewView } from "@aii/core";

export function InterviewMediaPanel({ view, stream, cameraActive, microphoneActive, error, disabled, onCheck, onRelease, onFallback, onInstall }: {
  view: InterviewView; stream: MediaStream | null; cameraActive: boolean; microphoneActive: boolean; error: string; disabled: boolean;
  onCheck: () => void; onRelease: () => void; onFallback: () => void; onInstall: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => { if (video.current) video.current.srcObject = stream; }, [stream]);
  return <section className="panel media-panel" aria-label="音视频设备检查">
    <div className="camera-preview">
      <video ref={video} autoPlay playsInline muted aria-label="摄像头本地预览" />
      {!cameraActive && <span className="camera-placeholder">{view.cameraRequired ? "请开启摄像头" : "本场不要求摄像头"}</span>}
      <span className="camera-caption">本地预览 · 不上传画面</span>
    </div>
    <div className="media-details"><h2>面试设备</h2>
      <p className={cameraActive ? "device-ok" : view.cameraRequired ? "device-warning" : "muted"}>摄像头：{cameraActive ? "已开启" : "未开启"}{view.cameraRequired ? "（本场必需）" : "（不要求）"}</p>
      {view.mode === "voice" && <p className={microphoneActive ? "device-ok" : "muted"}>麦克风：{microphoneActive ? "已开启" : "未开启"}{view.textFallback ? " · 已选择文字回退" : ""}</p>}
      <p className="small muted">{view.mode === "voice" ? view.speechServerEnabled ? `音频转写：${view.speechProcessorLabel}。仅在主动录制后发送音频，不保存音频。` : "音频转写：仅设备端识别，不会静默使用浏览器云端服务。" : "本场仅文字回答。"}</p>
      <p className="small muted">设备状态来自浏览器自报，不构成作弊认定。设备中断会暂停，不自动扣分。</p>
      {error && <p className="error" role="status">{error}</p>}
      <div className="media-actions"><button type="button" className="button secondary" disabled={disabled} onClick={onCheck}>开启 / 重新检测设备</button>
        {(cameraActive || microphoneActive) && <button type="button" className="text-button" disabled={disabled} onClick={onRelease}>关闭设备并暂停</button>}
        {view.mode === "voice" && !view.textFallback && <button type="button" className="text-button" disabled={disabled} onClick={onFallback}>改用文字（保留摄像头要求）</button>}
        {view.mode === "voice" && !view.speechServerEnabled && !view.textFallback && <button type="button" className="text-button" disabled={disabled} onClick={onInstall}>安装中文离线语音包</button>}
      </div>
    </div>
  </section>;
}
