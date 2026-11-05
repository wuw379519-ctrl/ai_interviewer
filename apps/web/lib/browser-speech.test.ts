import { afterEach, expect, it, vi } from "vitest";
import { createLocalRecognition } from "./browser-speech";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
it("没有设备端 API 时拒绝，不能静默调用云端识别", async () => {
  vi.stubGlobal("window", {});
  await expect(createLocalRecognition()).rejects.toThrow("没有设备端语音识别");
  vi.stubGlobal("window", { webkitSpeechRecognition: class {} });
  await expect(createLocalRecognition()).rejects.toThrow("已阻止云端回退");
});
it("明确指定中文与 processLocally，识别尚不启动", async () => {
  const available = vi.fn().mockResolvedValue("available"), start = vi.fn();
  class Local { processLocally = false; lang = ""; static available = available; start = start; }
  vi.stubGlobal("window", { SpeechRecognition: Local });
  const recognition = await createLocalRecognition();
  expect(recognition.processLocally).toBe(true); expect(recognition.lang).toBe("zh-CN");
  expect(available).toHaveBeenCalledWith({ langs: ["zh-CN"], processLocally: true });
  expect(start).not.toHaveBeenCalled();
});
it("离线语音包缺失时阻止启动", async () => {
  class Local { processLocally = false; static async available() { return "downloadable"; } }
  vi.stubGlobal("window", { SpeechRecognition: Local });
  await expect(createLocalRecognition()).rejects.toThrow("中文设备端语音包不可用");
});
it("浏览器能力查询永久不返回时5秒失败，不静默转云端", async () => {
  vi.useFakeTimers();
  class Local { processLocally = false; static available = () => new Promise<string>(() => {}); }
  vi.stubGlobal("window", { SpeechRecognition: Local });
  const checked = expect(createLocalRecognition()).rejects.toThrow("查询超时（5秒）");
  await vi.advanceTimersByTimeAsync(5000); await checked; expect(vi.getTimerCount()).toBe(0);
});
it("拒绝浏览器非预期能力状态并清除超时定时器", async () => {
  vi.useFakeTimers();
  class Local { processLocally = false; static async available() { return "unexpected-status"; } }
  vi.stubGlobal("window", { SpeechRecognition: Local });
  await expect(createLocalRecognition()).rejects.toThrow(); expect(vi.getTimerCount()).toBe(0);
});
