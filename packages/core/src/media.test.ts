import { describe, expect, it } from "vitest";
import { assertMediaReady, consentForMedia, MEDIA_CONSENT_VERSION, MEDIA_HEARTBEAT_TTL_MS, mediaReportSchema } from "./media";
import { encodePcmWave } from "./audio";
describe("语音与摄像头策略", () => {
  const now = Date.now(), policy = { mode: "voice" as const, cameraRequired: true, textFallback: false };
  const live = { cameraActive: true, microphoneActive: true, mediaLastSeenAt: new Date(now) };
  it("同意明确说明本地预览、转写和不自动判定", () => {
    const consent = consentForMedia(policy);
    expect(consent.version).toBe(MEDIA_CONSENT_VERSION);
    for (const text of ["本地预览", "不上传", "不录像", "不能证明作弊", "明确同意后", "语音", "90天"]) expect(consent.text).toContain(text);
    expect(consentForMedia({ mode: "text", cameraRequired: false }).text).toContain("不访问麦克风或摄像头");
  });
  it.each([
    { ...live, cameraActive: false }, { ...live, microphoneActive: false },
    { ...live, mediaLastSeenAt: null }, { ...live, mediaLastSeenAt: new Date(now - MEDIA_HEARTBEAT_TTL_MS - 1) },
  ])("缺少设备或心跳过期不能开始/提交", (status) => {
    expect(() => assertMediaReady(policy, status, now)).toThrow();
  });
  it("文字回退不豁免摄像头要求", () => {
    const fallback = { ...policy, textFallback: true };
    expect(() => assertMediaReady(fallback, { ...live, microphoneActive: false }, now)).not.toThrow();
    expect(() => assertMediaReady(fallback, { ...live, cameraActive: false }, now)).toThrow();
  });
  it("元数据接口不接受视频帧、照片或人脸字段", () => {
    const report = { cameraActive: true, microphoneActive: true, reason: "check" };
    expect(mediaReportSchema.safeParse(report).success).toBe(true);
    for (const key of ["frame", "image", "video", "face", "emotion"]) expect(mediaReportSchema.safeParse({ ...report, [key]: "unwanted" }).success).toBe(false);
  });
  it("WAV 为16kHz单声道，限制幅度和长度", () => {
    const wav = encodePcmWave(new Float32Array([-2, 2, NaN, 0.5])), view = new DataView(wav);
    expect(view.getUint16(22, true)).toBe(1); expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getInt16(44, true)).toBe(-32768); expect(view.getInt16(46, true)).toBe(32767); expect(view.getInt16(48, true)).toBe(0);
    expect(() => encodePcmWave(new Float32Array(16000 * 120 + 1))).toThrow();
  });
});
