import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { closeSync, existsSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { createServer } from "node:net";
import { chromium } from "@playwright/test";
import { z } from "zod";
import { competencySetSchema, createdInterviewSchema, interviewStateSchema, reportDocumentSchema, resourceIdentitySchema, turnResultSchema } from "@aii/core";
import { operationsSchema } from "../lib/operations-schema";

/** Synthetic data only. Never loads root .env, seeds, or opens a database directly. */
async function main() {
  const root = process.cwd(), web = path.join(root, "apps/web"), requireWeb = createRequire(path.join(web, "package.json"));
  const next = requireWeb.resolve("next/dist/bin/next"), baseURL = "http://localhost:3300";
  const directory = path.join(root, ".data", `production-${randomUUID()}`); mkdirSync(directory, { recursive: true });
  const credentials = { authSecret: randomBytes(32).toString("hex"), recruiterPassword: randomBytes(24).toString("base64url"), adminPassword: randomBytes(24).toString("base64url"), adminKey: randomBytes(32).toString("hex") };
  const settings = { NODE_ENV: "production" as const, NEXT_DIST_DIR: process.env.NEXT_DIST_DIR ?? ".next-build", LLM_PROVIDER: "fake", DEMO_MODE: "false", APP_ENV: "production", PYTHON_API_URL: "http://127.0.0.1:8300", DB_DRIVER: "sqlite", DATABASE_URL: "", SQLITE_PATH: path.join(directory, "interviews.sqlite3"), AUTH_SECRET: credentials.authSecret, RECRUITER_PASSWORD: credentials.recruiterPassword, ADMIN_PASSWORD: credentials.adminPassword, ADMIN_API_KEY: credentials.adminKey, RECRUITER_API_KEY: "", APP_BASE_URL: baseURL, STT_BASE_URL: "", STT_MODEL: "", STT_API_KEY: "" };
  const env: NodeJS.ProcessEnv = { ...process.env, ...settings, STT_PROVIDER: "auto", TTS_PROVIDER: "local", TTS_ALLOW_EXTERNAL: "false" };
  writeFileSync(path.join(directory, "private-config.json"), JSON.stringify({ baseURL, env: settings }, null, 2), { mode: 0o600 });
  const log = openSync(path.join(directory, "server.log"), "a");
  let server: ChildProcess | undefined, api: ChildProcess | undefined;
  async function stop() {
    for (const child of [server, api]) {
      if (!child?.pid || child.exitCode !== null) continue;
      const exited = once(child, "exit");
      if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
      else child.kill();
      await exited;
    }
    server = undefined; api = undefined;
  }
  async function start() {
    api = spawn(process.env.PYTHON_EXECUTABLE ?? path.join(root, existsSync(path.join(root, ".venv311")) ? ".venv311" : ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"), ["-m", "uvicorn", "interviewer.main:app", "--app-dir", "apps/api", "--host", "127.0.0.1", "--port", "8300", "--no-access-log"], { cwd: root, env: { ...env, PYTHONPATH: path.join(root, "apps/api"), PYTHONUTF8: "1" }, windowsHide: true, stdio: ["ignore", log, log] });
    api.on("error", () => {});
    let apiReady = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      if (api.exitCode !== null) throw Error("Python API启动失败，请检查本次server.log");
      try { if ((await fetch(`${settings.PYTHON_API_URL}/api/ready`, { signal: AbortSignal.timeout(1500) })).ok) { apiReady = true; break; } } catch { /* startup */ }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    assert(apiReady, "Python API未就绪");
    const child = spawn(process.execPath, [next, "start", "-p", "3300", "-H", "127.0.0.1"], { cwd: web, env, windowsHide: true, detached: true, stdio: ["ignore", log, log] });
    server = child; child.on("error", () => {});
    for (let attempt = 0; attempt < 60; attempt++) {
      if (child.exitCode !== null) throw Error("隔离生产服务启动失败，请检查本次server.log；未改动3000端口。");
      try { const ready = await fetch(`${baseURL}/api/ready`, { signal: AbortSignal.timeout(3000) }); if (ready.ok) return; } catch { /* startup */ }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw Error("隔离生产服务未就绪");
  }
  let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined, keep = false;
  try {
    if (!process.argv.includes("--skip-build")) {
      console.log("Building production assets in .next-build…");
      const build = spawn(process.execPath, [next, "build"], { cwd: web, env, windowsHide: true, stdio: "inherit" });
      assert.equal((await once(build, "exit"))[0], 0, "生产构建失败");
    }
    // Check both listeners, including non-HTTP occupants, before any API writes.
    for (const port of [3300, 8300]) {
      await new Promise<void>((resolve, reject) => {
        const probe = createServer();
        probe.once("error", () => reject(Error(`${port}端口已占用，请先停止该端口的验收服务`)));
        probe.listen(port, "127.0.0.1", () => probe.close((error) => error ? reject(error) : resolve()));
      });
    }
    await start();
    browser = await chromium.launch(); const context = await browser.newContext({ baseURL }); const page = await context.newPage(), request = context.request;
    const ready = z.object({ ok: z.literal(true), database: z.literal("ready"), mode: z.literal("production"), speech: z.literal("device_local") });
    ready.parse(await (await request.get("/api/ready")).json());
    const healthSchema = z.object({ instanceId: z.string().uuid() });
    const initialProcess = healthSchema.parse(await (await request.get("/api/health")).json()).instanceId;
    assert.equal((await request.get("/api/jobs")).status(), 401);
    assert.equal((await request.post("/api/auth/login", { data: {} })).status(), 401);
    await page.goto("/"); await page.getByLabel("账号").fill("recruiter"); await page.getByLabel("密码").fill(credentials.recruiterPassword); await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.getByRole("heading", { name: "最近的面试" }).waitFor();
    const session = (await context.cookies()).find((cookie) => cookie.name === "aii_recruiter");
    assert(session?.secure && session.httpOnly && session.sameSite === "Strict", "生产浏览器应保存并使用Secure HttpOnly角色cookie");
    assert.equal((await request.get("/api/admin/retention")).status(), 403);
    async function post<T>(url: string, data: unknown, schema: z.ZodType<T>, headers: Record<string, string> = {}) {
      const response = await request.post(url, { data, headers: { "Idempotency-Key": randomUUID(), ...headers } });
      assert(response.ok(), `${url}: HTTP${response.status()}`); return schema.parse(await response.json());
    }
    const job = await post("/api/jobs", { title: "生产验收虚构研究生岗位", recruitmentTrack: "graduate_campus", jdText: "面向研究生校招，负责TypeScript实验系统开发、数据分析与量化实验验证，通过研究实践解决问题，具备学习能力和团队协作能力。" }, resourceIdentitySchema);
    const dimensions = await post(`/api/jobs/${job.id}/competencies:extract`, {}, competencySetSchema);
    assert((await request.patch(`/api/jobs/${job.id}/competencies`, { data: dimensions, headers: { "Idempotency-Key": randomUUID() } })).ok());
    async function candidate() { return post("/api/candidates", { jobId: job.id, fullName: "生产验收虚构候选人" }, resourceIdentitySchema); }
    const person = await candidate();
    assert((await request.post(`/api/candidates/${person.id}/resume`, { data: { text: "虚构研究项目：个人负责TypeScript实验分析模块，与同学沟通解决分歧，将处理时间降低40%，复用到多个研究任务。" }, headers: { "Idempotency-Key": randomUUID() } })).ok());
    const created = await post("/api/interviews", { jobId: job.id, candidateId: person.id, durationMinutes: 15, mode: "text", cameraRequired: false }, createdInterviewSchema);
    assert.equal(created.questionCount, 13); const id = created.interviewId, headers = { Authorization: `Bearer ${created.inviteToken}` };
    const state = async () => interviewStateSchema.parse(await (await request.get(`/api/interviews/${id}/state`, { headers })).json());
    assert.equal((await request.get(`/api/interviews/${id}/state`)).status(), 401);
    assert.equal((await request.post(`/api/interviews/${id}/turns`, { headers, data: { action: "answer", content: "虚构未同意测试，不应保存" } })).status(), 409);
    const invited = await state(); assert.equal(invited.turns.length, 0);
    await post(`/api/interviews/${id}/consent`, { accepted: true, consentVersion: invited.consentVersion }, z.unknown(), headers);
    await post(`/api/interviews/${id}/start`, {}, z.unknown(), headers);
    const original = (await state()).currentQuestion;
    await post(`/api/interviews/${id}/pause`, { paused: true }, z.unknown(), headers);
    await page.goto(`/i/${id}#token=${created.inviteToken}`); await page.reload();
    assert.deepEqual((await state()).currentQuestion, original);
    await post(`/api/interviews/${id}/pause`, { paused: false }, z.unknown(), headers);
    for (let seq = 1; seq <= 13; seq++) {
      const current = await state(); assert.equal(current.questionSeq, seq);
      const response = await request.post(`/api/interviews/${id}/turns`, { headers: { ...headers, "Idempotency-Key": randomUUID() }, data: { action: "answer", content: current.currentQuestion?.assessmentMode === "scored" ? "我主导研究模块，个人负责核心实现和回归实验。我与同学沟通解决分歧并达成一致，将耗时降低40%，把验证机制复用到多个项目。" : "虚构测试事实，真实资格需由招聘者查看证明后人工核验。" } });
      assert(response.ok()); assert.match(response.headers()["content-type"] ?? "", /text\/event-stream/);
      const done = (await response.text()).split("\n\n").find((event) => event.startsWith("event: done\n")); assert(done);
      turnResultSchema.parse(JSON.parse(done.slice("event: done\ndata: ".length)) as unknown);
    }
    assert.equal((await state()).status, "wrapping_up");
    await post(`/api/interviews/${id}/finish`, {}, z.unknown(), headers);
    assert.equal((await state()).status, "scoring");
    const report = await post(`/api/interviews/${id}/score`, {}, reportDocumentSchema);
    assert.equal(report.dimensions.length, 4); assert.equal(report.questions.length, 8);
    assert(report.dimensions.every((dimension) => dimension.score !== "insufficient_evidence" && dimension.evidenceIds.length > 0));
    assert(report.evidence.every((item) => item.quote.length > 0)); assert(report.metadata.totalTokens > 0);
    await page.goto(`/recruiter/interviews/${id}/report`); await page.getByTestId("qualification-status").waitFor();
    const metricsResponse = await request.get("/api/admin/operations", { headers: { Authorization: `Bearer ${credentials.adminKey}` } });
    assert(metricsResponse.ok()); const metrics = operationsSchema.parse(await metricsResponse.json());
    assert(metrics.items.some((row) => row.operation === "score" && row.requests === 1 && row.failures === 0));
    await stop(); await start();
    assert.notEqual(healthSchema.parse(await (await request.get("/api/health")).json()).instanceId, initialProcess, "必须实际重启Python进程，禁止复用遗留监听服务");
    assert.equal((await state()).status, "report_ready");
    assert.equal(reportDocumentSchema.parse(await (await request.get(`/api/interviews/${id}/report`)).json()).revision, report.revision);
    assert((await request.get("/api/jobs")).ok(), "招聘会话在相同密钥重启后仍有效");
    const removed = await request.delete(`/api/candidates/${person.id}`, { headers: { Authorization: `Bearer ${credentials.adminKey}`, "Idempotency-Key": randomUUID() }, data: { confirmCandidateId: person.id, reason: "删除本次隔离生产验收合成资料" } });
    assert(removed.ok(), `删除验收资料HTTP${removed.status()}`); assert.equal((await request.get(`/api/interviews/${id}/state`, { headers })).status(), 401);
    const voicePerson = await candidate(), voiceInvite = await post("/api/interviews", { jobId: job.id, candidateId: voicePerson.id, durationMinutes: 15, mode: "voice", cameraRequired: true }, createdInterviewSchema);
    const voiceUrl = `${baseURL}/i/${voiceInvite.interviewId}#token=${voiceInvite.inviteToken}`;
    writeFileSync(path.join(directory, "private-invitation.txt"), voiceUrl, { mode: 0o600 });
    await page.goto("/diagnostics/voice"); await page.getByRole("heading", { name: "真实设备与中文语音联调" }).waitFor();
    assert(await page.getByRole("button", { name: "开启真实摄像头与麦克风测试" }).isDisabled());
    await page.goto("/login");
    await page.getByLabel("账号").fill("admin");
    await page.getByLabel("密码").fill(credentials.adminPassword);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.waitForURL("**/admin/interviews");
    await page.getByRole("heading", { name: "全部场次" }).waitFor();
    const adminCookies = await context.cookies();
    assert(adminCookies.some((cookie) => cookie.name === "aii_admin" && cookie.secure && cookie.httpOnly));
    assert(!adminCookies.some((cookie) => cookie.name === "aii_recruiter"));
    assert((await request.get("/api/jobs")).ok(), "同一管理员会话应能进入招聘工作台");
    await page.getByRole("button", { name: "退出管理员" }).click();
    await page.getByRole("heading", { name: "管理员登录" }).waitFor();
    assert.equal((await request.get("/api/jobs")).status(), 401);
    const result = { checkedAt: new Date().toISOString(), deployment: "local-production", provider: "fake", database: "isolated-sqlite", authCookie: "secure-httpOnly-strict-browser-verified", questions: 13, scoredQuestions: 8, dimensions: 4, evidence: "all-dimensions-cited", tokens: report.metadata.totalTokens, restart: "report-invitation-and-session-restored", deletion: "synthetic-candidate-erased", physicalDevices: "pending-human-trial", port: 3300, pid: server?.pid };
    writeFileSync(path.join(directory, "result.json"), JSON.stringify(result, null, 2));
    writeFileSync(path.join(root, ".data", "production-latest.json"), JSON.stringify({ directory }, null, 2));
    console.log(JSON.stringify({ ...result, directory, diagnostics: `${baseURL}/diagnostics/voice` }, null, 2));
    keep = !process.argv.includes("--stop"); if (keep) { server?.unref(); api?.unref(); }
  } finally { await browser?.close(); if (!keep) await stop(); closeSync(log); }
}
main().catch((error: unknown) => { console.error(error instanceof Error ? error.message : "生产验收失败"); process.exitCode = 1; });
