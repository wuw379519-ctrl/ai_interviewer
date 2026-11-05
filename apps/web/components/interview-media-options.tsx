"use client";
export function InterviewMediaOptions({ mode, cameraRequired, onModeChange, onCameraChange }: {
  mode: "text" | "voice"; cameraRequired: boolean; onModeChange: (mode: "text" | "voice") => void; onCameraChange: (required: boolean) => void;
}) {
  return <fieldset className="media-options"><legend>面试方式与设备要求</legend>
    <div className="mode-choices"><label><input type="radio" name="mode" checked={mode === "voice"} onChange={() => onModeChange("voice")} />语音面试（播报 + 转写核对）</label>
      <label><input type="radio" name="mode" checked={mode === "text"} onChange={() => onModeChange("text")} />文本面试</label></div>
    <label className="checkbox-label"><input type="checkbox" checked={cameraRequired} onChange={(event) => onCameraChange(event.target.checked)} />要求开启摄像头（仅候选人本地预览）</label>
    <p className="small muted">设备中断将暂停，不自动判定作弊。画面不上传、不录像。设备要求不便满足时，可由招聘者另行安排文本或免摄像头面试。</p>
  </fieldset>;
}
