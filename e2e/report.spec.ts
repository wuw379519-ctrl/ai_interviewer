import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { competencySetSchema, createdInterviewSchema, reportDocumentSchema, CONSENT_VERSION, type ReportDocument } from "../packages/core/src/index";

const answer = "姓名：合成报告候选人，性别：女，年龄：32，邮箱 report@example.com，电话13800138000。\n我主导模块交付，个人负责核心实现与回归验证。我与产品沟通解决分歧并达成一致，将耗时降低40%，把验证机制复用到多个项目。";
async function completed(request: APIRequestContext, six = false) {
  await request.post("/api/auth/login", { data: {} });
  const job = await (await request.post("/api/jobs", { data: { title: `报告回归工程师 ${randomUUID().slice(0, 6)}`, jdText: "负责 TypeScript 项目交付与性能优化，分析复杂需求和方案取舍，与产品后端合作并建立回归验证机制。" } })).json() as { id: string };
  const set = competencySetSchema.parse(await (await request.post(`/api/jobs/${job.id}/competencies:extract`, { data: {} })).json());
  if (six) {
    set.competencies.push({ ...set.competencies[0]!, name: "风险控制" }, { ...set.competencies[0]!, name: "知识沉淀" });
    set.competencies.forEach((row, index) => { row.weight = index === 0 ? 0.1665 : 0.1667; });
  }
  expect((await request.patch(`/api/jobs/${job.id}/competencies`, { data: set })).ok()).toBe(true);
  const candidate = await (await request.post("/api/candidates", { data: { jobId: job.id, fullName: "合成报告候选人", email: "report@example.com" } })).json() as { id: string };
  const invite = createdInterviewSchema.parse(await (await request.post("/api/interviews", { data: { jobId: job.id, candidateId: candidate.id, durationMinutes: six ? 45 : 15 } })).json());
  const headers = { Authorization: `Bearer ${invite.inviteToken}` }, id = invite.interviewId;
  expect((await request.post(`/api/interviews/${id}/consent`, { headers, data: { accepted: true, consentVersion: CONSENT_VERSION } })).ok()).toBe(true);
  expect((await request.post(`/api/interviews/${id}/start`, { headers, data: {} })).ok()).toBe(true);
  for (let index = 0; index < invite.questionCount; index++) expect((await request.post(`/api/interviews/${id}/turns`, { headers, data: { action: "answer", content: answer } })).ok()).toBe(true);
  expect((await request.post(`/api/interviews/${id}/finish`, { headers, data: {} })).ok()).toBe(true);
  return invite;
}
async function printReport(page: Page, name: string) {
  await page.emulateMedia({ media: "print" });
  const sheets = page.getByTestId("report-sheet"); await expect(sheets).toHaveCount(2);
  const heights = await sheets.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  for (let index = 0; index < 2; index++) await sheets.nth(index).screenshot({ path: test.info().outputPath(`${name}-page-${index + 1}.png`) });
  for (const height of heights) expect(height, `A4 sheet heights: ${heights.join(", ")}`).toBeLessThanOrEqual(1047);
  const pdf = await page.pdf({ path: test.info().outputPath(name), format: "A4", preferCSSPageSize: true, printBackground: true });
  expect(pdf.toString("latin1").match(/\/Type\s*\/Page\b/g)?.length).toBe(2);
  await page.emulateMedia({ media: "screen" });
}

test("完整面试后生成报告、打印两页、改分留痕与人工完成复核", async ({ request, page, browser }) => {
  test.setTimeout(180000);
  const invite = await completed(request), id = invite.interviewId;
  const anonymous = await browser.newContext({ baseURL: "http://127.0.0.1:3101" });
  expect((await anonymous.request.get(`/api/interviews/${id}/report`)).status()).toBe(401);
  expect((await anonymous.request.post(`/api/interviews/${id}/score`, { data: {}, headers: { Authorization: `Bearer ${invite.inviteToken}` } })).status()).toBe(401);
  await anonymous.close();
  await page.request.post("/api/auth/login", { data: {} });
  await page.goto(`/recruiter/interviews/${id}/report`);
  await page.getByRole("button", { name: "生成证据报告", exact: true }).click();
  await expect(page.getByRole("heading", { name: "结构化面试报告", exact: true })).toBeVisible();
  await expect(page.getByText("原文证据与下一轮验证", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: "胜任力雷达图", exact: false })).toBeVisible();
  await page.evaluate(() => { window.print = () => undefined; });
  const auditPrint = page.waitForResponse((response) => response.url().endsWith("/print") && response.request().method() === "POST");
  await page.getByRole("button", { name: "打印 / 另存为 PDF", exact: true }).click();
  expect((await auditPrint).ok()).toBe(true);
  const report = reportDocumentSchema.parse(await (await request.get(`/api/interviews/${id}/report`)).json());
  expect(report.questions).toHaveLength(8); expect(report.dimensions).toHaveLength(4); expect(report.evidence.length).toBeGreaterThan(0);
  for (const pii of ["合成报告候选人", "report@example.com", "13800138000"]) expect(await page.locator("main").innerText()).not.toContain(pii);
  await printReport(page, "report-a4.pdf");
  await page.screenshot({ path: test.info().outputPath("report-screen.png"), fullPage: true });
  const dimension = report.dimensions[0]!;
  await page.getByRole("button", { name: `复核${dimension.competencyName}`, exact: true }).click();
  await page.getByLabel("新的维度分").selectOption("3"); await page.getByLabel("改分理由", { exact: true }).fill("复核原文后认为达到独立交付标准，调整为三级。");
  const revisionResponse = page.waitForResponse((response) => response.url().endsWith(`/api/scores/${dimension.scoreId}`) && response.request().method() === "PATCH", { timeout: 60000 });
  await page.getByRole("button", { name: "保存改分并留痕" }).click();
  const revision = await revisionResponse; expect(revision.ok()).toBe(true);
  const revised = reportDocumentSchema.parse(await revision.json()); expect(revised.dimensions.find((row) => row.scoreId === dimension.scoreId)?.score).toBe("3");
  await expect(page.getByText("5/5 → 3/5", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新运行评分" })).toHaveCount(0);
  await page.reload(); await expect(page.getByText("5/5 → 3/5", { exact: false })).toBeVisible();
  await page.getByLabel("复核说明", { exact: true }).fill("已核对各维度原文、评分依据和下一轮追问建议。");
  await page.getByRole("button", { name: "确认人工复核完成" }).click(); await expect(page.getByText("已人工复核 · v2")).toBeVisible();
  await printReport(page, "reviewed-report-a4.pdf");
  expect((await request.post(`/api/interviews/${id}/score`, { data: { rerun: true } })).status()).toBe(409);
});

test("6维度18题的合成上界报告仍为两页A4，证据不足不绘成0分", async ({ request, page }) => {
  test.setTimeout(180000);
  const invite = await completed(request, true), id = invite.interviewId;
  const result = await request.post(`/api/interviews/${id}/score`, { data: {} }); expect(result.ok()).toBe(true);
  const actual = reportDocumentSchema.parse(await result.json());
  // Isolated layout fixture extends the validated real report to the schema's 18-question upper bound.
  const fixture: ReportDocument = { ...actual, fixture: true, questions: Array.from({ length: 18 }, (_, index) => ({ ...actual.questions[index % actual.questions.length]!, seq: index + 1, questionId: `layout-${index + 1}` })) };
  fixture.jobTitle = "复杂业务平台的工程交付与质量验证岗位".repeat(6).slice(0, 120);
  fixture.dimensions = fixture.dimensions.map((row, index) => ({ ...row, competencyName: `维度${index + 1}复杂业务分析与跨团队工程质量交付能力`.repeat(3).slice(0, 60) }));
  fixture.evidence = fixture.evidence.map((row) => ({ ...row, quote: "我负责复杂项目的核心实现与回归验证，在交付中协调产品和技术方案的分歧，并通过对照实验与长期监测验证收益，将耗时降低百分之四十，再把机制复用到后续项目。".repeat(3).slice(0, 160) }));
  fixture.nextQuestions = fixture.dimensions.map((row) => `请补充一个体现「${row.competencyName}」的岗位案例，说明你的个人行动、关键取舍与可核验结果。`);
  fixture.dimensions[5] = { ...fixture.dimensions[5]!, score: "insufficient_evidence", evidenceIds: [] };
  fixture.overallScore = null; fixture.coverage = 0.8333; fixture.recommendation = "mixed";
  await page.route(`**/api/interviews/${id}/report`, (route) => route.fulfill({ json: fixture }));
  await page.request.post("/api/auth/login", { data: {} }); await page.goto(`/recruiter/interviews/${id}/report`);
  await expect(page.getByRole("heading", { name: "结构化面试报告", exact: true })).toBeVisible();
  await expect(page.locator(".report-question-scores tbody tr")).toHaveCount(18); await expect(page.locator(".report-radar circle")).toHaveCount(5);
  await printReport(page, "six-dimensions-18-questions.pdf");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
