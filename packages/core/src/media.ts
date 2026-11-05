import { z } from "zod";
import { DomainError } from "./errors";
import { CONSENT_TEXT, CONSENT_VERSION } from "./consent";

export const MEDIA_CONSENT_VERSION = "consent-2026-11-media-v1";
export const MEDIA_HEARTBEAT_TTL_MS = 20000;
export const mediaReportSchema = z.object({
  cameraActive: z.boolean(), microphoneActive: z.boolean(),
  reason: z.enum(["check", "heartbeat", "device_lost", "paused", "released"]),
  textFallback: z.boolean().optional(),
}).strict();
export type MediaReport = z.infer<typeof mediaReportSchema>;
export interface MediaPolicy { mode: "text" | "voice"; cameraRequired: boolean; textFallback: boolean }
export interface MediaStatus { cameraActive: boolean; microphoneActive: boolean; mediaLastSeenAt: Date | null }

export function consentForMedia(policy: Pick<MediaPolicy, "mode" | "cameraRequired"> & { recruitmentTrack?: "general" | "graduate_campus"; retentionDays?: number }): { version: string; text: string } {
  const days = z.number().int().min(1).max(90).parse(policy.retentionDays ?? 90);
  if (days !== 90) {
    const base = consentForMedia({ ...policy, retentionDays: 90 });
    return { version: `${base.version}-retention-${days}-v1`, text: base.text.replace(/90\s*天/g, `${days}天`) };
  }
  if (policy.recruitmentTrack === "graduate_campus") {
    const base = consentForMedia({ mode: policy.mode, cameraRequired: policy.cameraRequired });
    return { version: `${base.version}-graduate-v1`, text: `${base.text}本场为研究生校招，岗位硬指标为CET-4总分至少425分、研究生期间无曾经不及格记录（含补考或重修后通过的情况）。面试口述不等于证明已核验，由招聘者人工查看成绩报告及完整研究生成绩单；不要求提供证件号或账号密码。期望收入与岗位工作安排仅作事实记录，不进入能力评分；可以跳过或不说明个人原因。` };
  }
  if (policy.mode === "text" && !policy.cameraRequired) return { version: CONSENT_VERSION, text: CONSENT_TEXT };
  return { version: MEDIA_CONSENT_VERSION, text: [
    "本次面试由 AI 面试官进行，结果由人类招聘者复核，AI 不自动录用或淘汰。",
    policy.cameraRequired ? "本场要求开启摄像头；画面仅在你的设备本地预览，不上传、不录像、不保存截图。仅记录浏览器自报的设备开关、中断与恢复状态。设备中断将暂停面试；这些状态不能证明作弊，也不会用于自动扣分。" : "本场不要求摄像头。",
    policy.mode === "voice" ? "语音模式会使用麦克风。未配置企业转写服务时仅在设备端识别；已配置时使用页面明示的企业服务，将临时录制你主动开启的一段音频，传至该服务转写。本应用不将音频落盘或纳入留存；服务方处理政策由部署方说明。识别文字可先检查修改，提交后才保存为回答。不会静默使用浏览器云端识别。题目由本地语音合成播报，同时保留字幕。语音不可用时可以改用文字。" : "本场以文字回答，不使用麦克风。",
    "不做人脸识别、表情、情绪、视线或声纹分析。设备要求不便满足时，请联系招聘者安排替代方式。",
    "已提交文字转录和报告默认保留90天。可随时暂停或撤回，撤回后停止采集；可联系招聘者申请删除已有数据。请避免提供与岗位能力无关的受保护属性或联系方式。明确同意后才会请求设备权限。",
  ].join("") };
}

export function assertMediaReady(policy: MediaPolicy, status: MediaStatus, now: number): void {
  if (!policy.cameraRequired && (policy.mode === "text" || policy.textFallback)) return;
  const fresh = status.mediaLastSeenAt !== null && now - status.mediaLastSeenAt.getTime() <= MEDIA_HEARTBEAT_TTL_MS;
  if (!fresh || (policy.cameraRequired && !status.cameraActive) || (policy.mode === "voice" && !policy.textFallback && !status.microphoneActive)) {
    throw new DomainError("MEDIA_REQUIRED", "请先开启并检查本场要求的摄像头和麦克风；设备不可用时可联系招聘者安排替代方式");
  }
}
