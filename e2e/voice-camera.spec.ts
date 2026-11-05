import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { competencySetSchema, createdInterviewSchema, interviewStateSchema } from "../packages/core/src/index";

async function invitation(request: APIRequestContext) {
  await request.post("/api/auth/login", { data: {} });
  const job = await (await request.post("/api/jobs", { data: { title: `语音验证 ${randomUUID().slice(0, 6)}`, jdText: "负责 TypeScript React 项目交付，分析性能瓶颈与架构取舍，通过量化结果验证收益，与产品后端协作并保障质量。" } })).json() as { id: string };
  const set = competencySetSchema.parse(await (await request.post(`/api/jobs/${job.id}/competencies:extract`, { data: {} })).json());
  expect((await request.patch(`/api/jobs/${job.id}/competencies`, { data: set })).ok()).toBe(true);
  const candidate = await (await request.post("/api/candidates", { data: { jobId: job.id, fullName: "合成语音候选人" } })).json() as { id: string };
  return { ...createdInterviewSchema.parse(await (await request.post("/api/interviews", { data: { jobId: job.id, candidateId: candidate.id, durationMinutes: 15, mode: "voice", cameraRequired: true } })).json()), candidateId: candidate.id };
}

async function syntheticSpeech(page: Page) {
  await page.addInitScript(() => {
    const state = { mediaCalls: 0, localOnly: false, spoken: 0, canceled: 0 };
    Object.defineProperty(window, "__voiceTest", { value: state });
    // Deterministic media fixture: no physical camera, microphone or remote service.
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      state.mediaCalls++;
      const tracks: MediaStreamTrack[] = [];
      if (constraints?.video) {
        const canvas = document.createElement("canvas"); canvas.width = 640; canvas.height = 360;
        const paint = () => { const brush = canvas.getContext("2d"); if (brush) { brush.fillStyle = "#17382f"; brush.fillRect(0, 0, 640, 360); } };
        paint(); const video = canvas.captureStream(10); const timer = setInterval(paint, 100);
        video.getVideoTracks()[0]?.addEventListener("ended", () => clearInterval(timer));
        tracks.push(...video.getVideoTracks());
      }
      if (constraints?.audio) {
        const context = new AudioContext(), destination = context.createMediaStreamDestination();
        const oscillator = context.createOscillator(), gain = context.createGain(); gain.gain.value = 0;
        oscillator.connect(gain); gain.connect(destination); oscillator.start();
        (window as unknown as { __syntheticLevel: (value: number) => void }).__syntheticLevel = (value) => { gain.gain.value = value; void context.resume(); };
        tracks.push(...destination.stream.getAudioTracks());
      }
      return new MediaStream(tracks);
    };
    class Recognition {
      processLocally = false; lang = ""; continuous = false; interimResults = false;
      onresult: ((event: { resultIndex: number; results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null = null;
      onend: (() => void) | null = null;
      static async available() { return "available"; }
      start() { state.localOnly = this.processLocally; setTimeout(() => this.onresult?.({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: "我负责完成模块，个人主导核心实现。" } }] }), 50); }
      stop() { this.onend?.(); }
      abort() { this.onend?.(); }
    }
    Object.defineProperty(window, "SpeechRecognition", { value: Recognition, configurable: true });
    class Utterance { constructor(public text: string) {} }
    Object.defineProperty(window, "SpeechSynthesisUtterance", { value: Utterance, configurable: true });
    Object.defineProperty(window, "speechSynthesis", { value: {
      getVoices: () => [{ localService: true, lang: "zh-CN", name: "Synthetic local voice" }],
      addEventListener: () => undefined, removeEventListener: () => undefined,
      speak: () => { state.spoken++; }, cancel: () => { state.canceled++; },
    }, configurable: true });
  });
}

test("Edge播报故障明确提示，只请求题号且不静默切换其他语音服务", async ({ page, context, request }) => {
  await context.grantPermissions(["camera", "microphone"]); await syntheticSpeech(page);
  const invite = await invitation(request), calls: string[] = [];
  // UI-only Edge fixture: no real Edge client is loaded, no Microsoft request is made.
  await page.route(`**/api/interviews/${invite.interviewId}/state`, async (route) => {
    const response = await route.fetch();
    const state = interviewStateSchema.parse(await response.json());
    await route.fulfill({ json: { ...state, ttsServerEnabled: true } });
  });
  await page.route(`**/api/interviews/${invite.interviewId}/tts?**`, async (route) => {
    calls.push(route.request().url());
    expect(route.request().postData()).toBeNull();
    expect(route.request().method()).toBe("GET");
    await route.fulfill({ status: 503, json: { error: { code: "SPEECH_UNAVAILABLE", message: "合成Edge故障，请阅读文字题目", details: null } } });
  });
  await page.goto(`/i/${invite.interviewId}#token=${invite.inviteToken}`);
  expect(calls).toHaveLength(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "同意、检测设备并开始" }).click();
  await expect(page.getByTestId("current-question")).toBeVisible();
  await expect(page.getByText("合成Edge故障，请阅读文字题目")).toBeVisible();
  expect(calls).toHaveLength(1);
  const query = new URL(calls[0]!).searchParams;
  expect([...query.keys()].sort()).toEqual(["questionSeq", "turnSeq"]);
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { spoken: number } }).__voiceTest.spoken)).toBe(0);
  await expect(page.getByLabel("你的回答")).toBeEnabled();
  await page.getByRole("button", { name: "暂停一下" }).click();
  await expect(page.getByText("暂停期间不计时", { exact: false })).toBeVisible();
});

test("本地声音打断只停止播报，不开启识别或提交回答", async ({ page, context, request }) => {
  await context.grantPermissions(["camera", "microphone"]); await syntheticSpeech(page);
  const invite = await invitation(request), headers = { Authorization: `Bearer ${invite.inviteToken}` };
  await page.goto(`/i/${invite.interviewId}#token=${invite.inviteToken}`);
  await expect(page.getByLabel("启用本地声音打断播报")).toHaveCount(0);
  await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "同意、检测设备并开始" }).click();
  await expect(page.getByTestId("current-question")).toBeVisible();
  await expect(page.getByLabel("启用本地声音打断播报")).not.toBeChecked();
  await page.getByLabel("启用本地声音打断播报").check();
  await expect(page.getByRole("button", { name: "打断播报", exact: true })).toBeVisible();
  await page.waitForTimeout(1400);
  await expect(page.getByRole("button", { name: "打断播报", exact: true })).toBeVisible();
  await page.evaluate(() => (window as unknown as { __syntheticLevel: (value: number) => void }).__syntheticLevel(0.2));
  await expect(page.getByText("已检测到持续声音并停止播报", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "朗读题目", exact: true })).toBeVisible();
  await expect(page.getByLabel("你的回答")).toHaveValue("");
  await expect(page.getByRole("button", { name: "开始语音输入", exact: true })).toBeVisible();
  const saved = interviewStateSchema.parse(await (await request.get(`/api/interviews/${invite.interviewId}/state`, { headers })).json());
  expect(saved.turns.filter((turn) => turn.role === "candidate")).toHaveLength(0);
  await page.getByRole("button", { name: "暂停一下" }).click();
  await expect(page.getByText("暂停期间不计时", { exact: false })).toBeVisible();
});

test("独立联调页同意前不采集，撤销本地测试立即结束全部轨道", async ({ page, context }) => {
  await context.grantPermissions(["camera", "microphone"]); await syntheticSpeech(page); await page.clock.install();
  await page.goto("/diagnostics/voice");
  const mediaCalls = () => page.evaluate(() => (window as unknown as { __voiceTest: { mediaCalls: number } }).__voiceTest.mediaCalls);
  await expect(page.getByRole("button", { name: "开启真实摄像头与麦克风测试" })).toBeDisabled(); expect(await mediaCalls()).toBe(0);
  await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "开启真实摄像头与麦克风测试" }).click();
  await expect(page.getByTestId("real-camera-state")).toContainText("实时轨道已开启");
  await page.evaluate(() => { (window as unknown as { __trialTracks: MediaStreamTrack[] }).__trialTracks = (document.querySelector("video")?.srcObject as MediaStream).getTracks(); });
  await page.clock.fastForward(120001);
  await expect(page.getByTestId("real-camera-state")).toContainText("已关闭");
  expect(await page.evaluate(() => (window as unknown as { __trialTracks: MediaStreamTrack[] }).__trialTracks.every((track) => track.readyState === "ended"))).toBe(true);
  await page.getByRole("button", { name: "开启真实摄像头与麦克风测试" }).click();
  await expect(page.getByTestId("real-camera-state")).toContainText("实时轨道已开启");
  await page.evaluate(() => { (window as unknown as { __trialTracks: MediaStreamTrack[] }).__trialTracks = (document.querySelector("video")?.srcObject as MediaStream).getTracks(); });
  await page.getByRole("checkbox").uncheck();
  await expect(page.getByTestId("real-camera-state")).toContainText("已关闭");
  expect(await page.evaluate(() => (window as unknown as { __trialTracks: MediaStreamTrack[] }).__trialTracks.every((track) => track.readyState === "ended"))).toBe(true);
  await expect(page.getByTestId("real-microphone-state")).toContainText("已关闭");
});

test("浏览器识别无响应有明确超时提示，不无限等待或生成假转写", async ({ page, context }) => {
  await context.grantPermissions(["camera", "microphone"]); await syntheticSpeech(page); await page.clock.install();
  await page.goto("/diagnostics/voice"); await page.getByRole("checkbox").check();
  await page.evaluate(() => {
    const Constructor = (window as unknown as { SpeechRecognition: { available: () => Promise<string> } }).SpeechRecognition;
    Constructor.available = () => new Promise<string>(() => {});
  });
  await page.getByRole("button", { name: "检查中文本地识别能力" }).click();
  await expect(page.getByTestId("local-recognition-capability")).toContainText("正在检查");
  await page.clock.fastForward(5001);
  await expect(page.getByTestId("local-recognition-capability")).toContainText("查询超时（5秒）");
  await expect(page.getByRole("button", { name: "检查中文本地识别能力" })).toBeEnabled();
  await page.evaluate(() => {
    const Constructor = (window as unknown as { SpeechRecognition: { available: () => Promise<string>; prototype: { start: () => void } } }).SpeechRecognition;
    Constructor.available = async () => "available"; Constructor.prototype.start = () => {};
  });
  await page.getByRole("button", { name: "开启真实摄像头与麦克风测试" }).click();
  await expect(page.getByTestId("real-microphone-state")).toContainText("实时轨道已开启");
  await page.getByRole("button", { name: "开始本地试说" }).click();
  await expect(page.getByRole("button", { name: "结束试说" })).toBeEnabled();
  await page.clock.fastForward(10001);
  await expect(page.getByRole("alert").filter({ hasText: "10秒内未收到中文转写" })).toBeVisible();
  await expect(page.getByText("试说预览（只在本页）：尚无转写")).toBeVisible();
  await page.getByRole("button", { name: "停止所有测试设备" }).click();
});

test("语音转写须核对后提交，摄像头中断暂停，刷新恢复原题", async ({ page, context, request }) => {
  await context.grantPermissions(["camera", "microphone"]);
  await syntheticSpeech(page);
  const invite = await invitation(request), id = invite.interviewId;
  const headers = { Authorization: `Bearer ${invite.inviteToken}` };
  const saved = async () => interviewStateSchema.parse(await (await request.get(`/api/interviews/${id}/state`, { headers })).json());
  await page.goto(`/i/${id}#token=${invite.inviteToken}`);
  await expect(page.getByRole("button", { name: "同意、检测设备并开始" })).toBeDisabled();
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { mediaCalls: number } }).__voiceTest.mediaCalls)).toBe(0);
  expect((await request.post(`/api/interviews/${id}/media`, { headers, data: { cameraActive: true, microphoneActive: true, reason: "check" } })).status()).toBe(409);
  expect((await request.post(`/api/interviews/${id}/transcribe`, { headers, data: {} })).status()).toBe(409);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "同意、检测设备并开始" }).click();
  await expect(page.getByTestId("current-question")).toBeVisible();
  await expect(page.getByText("摄像头：已开启", { exact: false })).toBeVisible();
  await expect.poll(async () => page.evaluate(() => (window as unknown as { __voiceTest: { spoken: number } }).__voiceTest.spoken)).toBeGreaterThan(0);
  await page.getByRole("button", { name: "开始语音输入", exact: true }).click();
  await expect(page.getByLabel("你的回答")).toHaveValue("我负责完成模块，个人主导核心实现。");
  expect((await saved()).turns.filter((turn) => turn.role === "candidate")).toHaveLength(0);
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { localOnly: boolean } }).__voiceTest.localOnly)).toBe(true);
  await page.getByRole("button", { name: "结束语音输入", exact: true }).click();
  await page.getByLabel("你的回答").fill("我负责完成模块，个人主导核心实现，效果还不错。");
  await page.getByRole("button", { name: "发送回答" }).click();
  await expect(page.getByText("深入聊一聊 · 追问 1/2")).toBeVisible();
  const followup = await page.getByTestId("current-question").innerText();
  await page.evaluate(() => { const stream = document.querySelector("video")?.srcObject as MediaStream | null; stream?.getVideoTracks().forEach((track) => track.stop()); });
  await expect(page.getByRole("button", { name: "继续面试" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.querySelector("video")?.srcObject === null)).toBe(true);
  expect((await saved()).pausedAt).not.toBeNull();
  await page.reload();
  await expect(page.getByTestId("current-question")).toHaveText(followup);
  await page.getByRole("button", { name: "继续面试" }).click();
  await expect(page.getByLabel("你的回答")).toBeEnabled();
  await expect(page.getByTestId("current-question")).toHaveText(followup);
  expect((await request.post(`/api/interviews/${id}/media`, { headers, data: { cameraActive: true, microphoneActive: true, reason: "heartbeat", frame: "prohibited-video" } })).status()).toBe(400);
  await page.getByRole("button", { name: "关闭设备并暂停" }).click();
  await expect(page.getByRole("button", { name: "继续面试" })).toBeVisible();
  expect(await page.evaluate(() => document.querySelector("video")?.srcObject)).toBeNull();
});

test("拒绝摄像头不能开始，文字回退仍保留摄像头门禁", async ({ page, request }) => {
  await page.addInitScript(() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException("Synthetic denial", "NotAllowedError"); }; });
  const invite = await invitation(request), id = invite.interviewId, headers = { Authorization: `Bearer ${invite.inviteToken}` };
  await page.goto(`/i/${id}#token=${invite.inviteToken}`);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "同意、检测设备并开始" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "设备权限被拒绝" })).toBeVisible();
  await expect(page.getByTestId("current-question")).toHaveCount(0);
  await page.getByRole("button", { name: "改用文字（保留摄像头要求）" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "设备权限被拒绝" })).toBeVisible();
  expect((await request.post(`/api/interviews/${id}/media`, { headers, data: { cameraActive: false, microphoneActive: false, reason: "check", textFallback: true } })).ok()).toBe(true);
  expect((await request.post(`/api/interviews/${id}/start`, { headers, data: {} })).status()).toBe(409);
  const state = interviewStateSchema.parse(await (await request.get(`/api/interviews/${id}/state`, { headers })).json());
  expect(state.status).toBe("consented"); expect(state.turns).toEqual([]);
});

test("管理员清除活动面试后，候选人自动停止本地摄像头与麦克风", async ({ page, request, context }) => {
  await context.grantPermissions(["camera", "microphone"]); await syntheticSpeech(page);
  const invite = await invitation(request);
  await page.goto(`/i/${invite.interviewId}#token=${invite.inviteToken}`);
  await page.getByRole("checkbox").check(); await page.getByRole("button", { name: "同意、检测设备并开始" }).click();
  await expect(page.getByTestId("current-question")).toBeVisible();
  const count = await page.evaluate(() => {
    const tracks = (document.querySelector("video")?.srcObject as MediaStream | null)?.getTracks() ?? [];
    (window as unknown as { __erasureTracks: MediaStreamTrack[] }).__erasureTracks = tracks; return tracks.length;
  }); expect(count).toBeGreaterThan(0);
  expect((await request.post("/api/admin/login", { data: {} })).ok()).toBe(true);
  expect((await request.delete(`/api/candidates/${invite.candidateId}`, { data: { confirmCandidateId: invite.candidateId, reason: "合成测试验证删除后停止设备" } })).ok()).toBe(true);
  await expect(page.getByRole("alert").filter({ hasText: "已停止设备采集" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __erasureTracks: MediaStreamTrack[] }).__erasureTracks.every((track) => track.readyState === "ended"))).toBe(true);
  await expect(page.getByLabel("你的回答")).toHaveCount(0);
});
