import { test, expect, type APIRequestContext } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { competencySetSchema, createdInterviewSchema, interviewStateSchema, reportDocumentSchema, resourceIdentitySchema, retentionWorkspaceSchema, retentionCommandPreviewSchema, retentionCommandResultSchema } from "../packages/core/src/index";
const identity = resourceIdentitySchema;
async function fixture(request: APIRequestContext) {
  expect((await request.post("/api/auth/login", { data: {} })).ok()).toBe(true);
  const job = identity.parse(await (await request.post("/api/jobs", { data: { title: `M4合成验证${randomUUID().slice(0, 6)}`, jdText: "负责研发任务实现与测试，分析方案取舍并以量化结果验证收益。通过项目、课程或实习的本人实践说明分析、协作、学习与交付行为。" } })).json());
  const set = competencySetSchema.parse(await (await request.post(`/api/jobs/${job.id}/competencies:extract`, { data: {} })).json());
  expect((await request.patch(`/api/jobs/${job.id}/competencies`, { data: set })).ok()).toBe(true);
  const candidate = identity.parse(await (await request.post("/api/candidates", { data: { jobId: job.id, fullName: "M4合成删除候选人" } })).json());
  expect((await request.post(`/api/candidates/${candidate.id}/resume`, { data: { text: "合成简历：技能Python和SQL，项目中个人负责实验与回归，主导方案沟通并将耗时降低30%，复用到后续项目。" } })).ok()).toBe(true);
  const create = async () => createdInterviewSchema.parse(await (await request.post("/api/interviews", { data: { jobId: job.id, candidateId: candidate.id, durationMinutes: 15 } })).json());
  return { candidate, create };
}
test("独立管理员预览删除，清除已完成报告与活动面试，原链接失效", async ({ page, request, context }) => {
  test.setTimeout(240000);
  const { candidate, create } = await fixture(request), invite = await create(), id = invite.interviewId;
  const headers = { Authorization: `Bearer ${invite.inviteToken}` };
  const initial = interviewStateSchema.parse(await (await request.get(`/api/interviews/${id}/state`, { headers })).json());
  expect((await request.post(`/api/interviews/${id}/consent`, { headers, data: { accepted: true, consentVersion: initial.consentVersion } })).ok()).toBe(true);
  expect((await request.post(`/api/interviews/${id}/start`, { headers, data: {} })).ok()).toBe(true);
  for (let index = 0; index < invite.questionCount; index++) expect((await request.post(`/api/interviews/${id}/turns`, { headers, data: { action: "answer", content: "我主导实验模块，个人负责实现与回归。我与同学沟通解决分歧并达成一致，将耗时降低40%，把验证机制复用到多个项目。" } })).ok()).toBe(true);
  expect((await request.post(`/api/interviews/${id}/finish`, { headers, data: {} })).ok()).toBe(true);
  const report = await request.post(`/api/interviews/${id}/score`, { data: {} }); expect(report.ok()).toBe(true); reportDocumentSchema.parse(await report.json());
  const active = await create(), candidatePage = await context.newPage();
  await candidatePage.goto(`/i/${active.interviewId}#token=${active.inviteToken}`); await candidatePage.getByRole("checkbox").check(); await candidatePage.getByRole("button", { name: "同意并开始面试" }).click(); await expect(candidatePage.getByLabel("你的回答")).toBeVisible();
  expect((await request.delete(`/api/candidates/${candidate.id}`, { data: { confirmCandidateId: candidate.id, reason: "合成越权请求" } })).status()).toBe(403);
  await page.request.post("/api/auth/login", { data: {} });
  await page.goto("/admin"); await expect(page.getByRole("heading", { name: "管理员登录", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "进入演示管理台" }).click(); await expect(page.getByRole("heading", { name: "保留期策略", exact: true })).toBeVisible();
  await page.getByLabel("按完整候选人编号预览").fill(candidate.id); await page.getByRole("button", { name: "查询删除范围" }).click();
  await expect(page.getByRole("heading", { name: "确认清除", exact: false })).toBeVisible(); await expect(page.getByRole("button", { name: "永久清除候选人资料" })).toBeDisabled();
  await page.getByLabel("输入完整候选人编号").fill(candidate.id); await page.getByLabel("删除理由", { exact: true }).fill("仅为合成验收，响应本人删除请求");
  await page.getByRole("button", { name: "永久清除候选人资料" }).click(); await expect(page.getByRole("status")).toContainText("资料已清除");
  await expect(candidatePage.getByRole("alert").filter({ hasText: "已停止设备采集" })).toBeVisible(); await expect(candidatePage.getByLabel("你的回答")).toHaveCount(0);
  expect((await request.get(`/api/interviews/${id}/report`)).status()).toBe(404); expect((await request.get(`/api/interviews/${id}/state`, { headers })).status()).toBe(401);
  await page.getByLabel("操作筛选").selectOption("candidate.erased"); await page.getByRole("button", { name: "筛选审计", exact: true }).click(); await expect(page.locator("table").last()).toContainText("candidate.erased");
  await page.screenshot({ path: test.info().outputPath("governance-screen.png"), fullPage: true });
  await page.getByRole("button", { name: "退出管理员" }).click(); await expect(page.getByRole("heading", { name: "管理员登录", exact: true })).toBeVisible();
  expect((await page.request.get("/api/admin/audit")).status()).toBe(403); await candidatePage.close();
});
test("保留期更改只用于新场次，新版同意及清理预览执行可用", async ({ page, request }) => {
  test.setTimeout(180000);
  await page.request.post("/api/admin/login", { data: {} });
  const before = retentionWorkspaceSchema.parse(await (await page.request.get("/api/admin/retention")).json());
  try {
    await page.goto("/admin"); await expect(page.getByRole("heading", { name: "保留期策略", exact: true })).toBeVisible();
    await page.getByLabel("新资料保留天数").fill("30"); await page.getByLabel("策略修改理由").fill("合成测试缩短新资料保留期"); await page.getByRole("button", { name: "保存保留期策略", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("仅用于新资料");
    const { create } = await fixture(request), invite = await create(), candidate = await page.context().newPage();
    await candidate.goto(`/i/${invite.interviewId}#token=${invite.inviteToken}`); await expect(candidate.locator(".consent-copy")).toContainText("30天"); await expect(candidate.locator(".consent-copy")).not.toContainText("90天");
    await candidate.getByRole("checkbox").check(); await candidate.getByRole("button", { name: "同意并开始面试" }).click(); await expect(candidate.getByTestId("current-question")).toBeVisible();
    const run = promisify(execFile), commandEnv = { ...process.env, APP_BASE_URL: "http://127.0.0.1:3101", ADMIN_API_KEY: process.env.E2E_ADMIN_API_KEY };
    const previewCommand = await run(process.execPath, ["scripts/python.mjs", "-m", "interviewer.cli", "retention-preview"], { env: commandEnv, timeout: 45000 });
    expect(retentionCommandPreviewSchema.parse(JSON.parse(previewCommand.stdout) as unknown).executed).toBe(false);
    const runCommand = await run(process.execPath, ["scripts/python.mjs", "-m", "interviewer.cli", "retention-run", "--execute"], { env: commandEnv, timeout: 120000 });
    expect(retentionCommandResultSchema.parse(JSON.parse(runCommand.stdout) as unknown).executed).toBe(true);
    await page.getByRole("button", { name: "重新预览", exact: true }).click(); await expect(page.getByRole("button", { name: "重新预览", exact: true })).toBeEnabled();
    await page.getByLabel("清理说明", { exact: true }).fill("仅清理独立演示库中本批到期数据"); await expect(page.getByRole("button", { name: "执行本批到期清理" })).toBeDisabled();
    await page.getByRole("checkbox", { name: "我已核对本批编号", exact: false }).check(); await page.getByRole("button", { name: "执行本批到期清理", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("本批清理完成"); await expect(candidate.getByTestId("current-question")).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 }); expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await candidate.close();
  } finally {
    const current = retentionWorkspaceSchema.parse(await (await page.request.get("/api/admin/retention")).json());
    expect((await page.request.patch("/api/admin/retention", { data: { retentionDays: before.policy.retentionDays, expectedRevision: current.policy.revision, reason: "还原合成测试前的策略" } })).ok()).toBe(true);
  }
});
