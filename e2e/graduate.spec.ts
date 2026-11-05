import { test, expect } from "@playwright/test";
import { interviewStateSchema, reportDocumentSchema } from "../packages/core/src/index";

test("研究生校招向导、9必问、资格人工核验与两页报告", async ({ page, request }) => {
  test.setTimeout(240000);
  expect((await page.request.post("/api/auth/login", { data: {} })).ok()).toBe(true);
  await page.goto("/recruiter/new");
  await expect(page.getByLabel("招聘场景")).toHaveValue("graduate_campus");
  await page.getByRole("button", { name: "载入演示资料" }).click();
  await page.getByRole("button", { name: "抽取胜任力" }).click();
  await expect(page.getByText("原表9 · 工作安排（替代家庭情况，自愿回答）", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "确认标准，下一步" }).click();
  await page.getByRole("button", { name: "解析简历，下一步" }).click();
  await page.getByRole("radio", { name: "文本面试", exact: true }).check();
  await page.getByRole("checkbox", { name: "要求开启摄像头" }).uncheck();
  await page.getByRole("button", { name: "生成计划并创建邀请" }).click();
  const link = await page.getByLabel("专属邀请链接").inputValue(), url = new URL(link);
  const id = url.pathname.split("/").at(-1)!, token = new URLSearchParams(url.hash.slice(1)).get("token")!;
  const headers = { Authorization: `Bearer ${token}` };
  await page.goto(link);
  await expect(page.locator(".consent-copy")).toContainText("425");
  await expect(page.getByLabel("你的回答")).toHaveCount(0);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "同意并开始面试" }).click();
  await expect(page.getByTestId("current-question")).toBeVisible();
  for (let seq = 1; seq <= 13; seq++) {
    const state = interviewStateSchema.parse(await (await request.get(`/api/interviews/${id}/state`, { headers })).json());
    expect(state.questionSeq).toBe(seq); expect(state.followupsAsked).toBe(0);
    const previous = await page.getByTestId("current-question").innerText();
    if (seq === 4) { await page.reload(); await expect(page.getByTestId("current-question")).toHaveText(previous); }
    const next = page.waitForResponse((response) => response.url().endsWith("/turns") && response.request().method() === "POST");
    if (state.currentQuestion?.topicKey === "work_arrangements") await page.getByRole("button", { name: "跳过本题" }).click();
    else {
      await page.getByLabel("你的回答").fill(state.currentQuestion?.assessmentMode === "scored" ? "我主导研究模块，个人负责核心实现和回归实验。我与同学沟通解决分歧并达成一致，将耗时降低40%，把验证机制复用到多个项目。" : state.currentQuestion?.topicKey === "compensation" ? "期望税前月薪15000元，12薪年薪180000元，最低薪资不披露。" : "相关事实待出示证明，我愿意由招聘者人工核验。");
      await page.getByRole("button", { name: "发送回答" }).click();
    }
    expect((await next).ok()).toBe(true);
    if (seq < 13) await expect(page.getByTestId("current-question")).not.toHaveText(previous);
  }
  await expect(page.getByRole("heading", { name: "感谢分享，这次对话已保存。" })).toBeVisible();
  await page.goto(`/recruiter/interviews/${id}/report`);
  await page.getByRole("button", { name: "生成证据报告", exact: true }).click();
  await expect(page.getByTestId("qualification-status")).toContainText("待人工核验");
  await expect(page.getByRole("button", { name: "确认人工复核完成" })).toBeDisabled();
  await page.getByText("固定必问触达 9/9", { exact: false }).click();
  await expect(page.getByText("期望税前月薪15000元", { exact: false })).toBeVisible();
  await expect(page.getByText("工作安排（替代家庭情况，自愿回答） · 候选人跳过", { exact: false })).toBeVisible();
  await page.getByLabel("CET-4核验分数").fill("425"); await page.getByLabel("研究生期间曾挂科门数").fill("0");
  await page.getByLabel("四级成绩报告核验来源").fill("已查看合成四级成绩报告");
  await page.getByLabel("完整研究生成绩单核验来源").fill("已查看合成完整成绩单含补考重修记录");
  await page.getByLabel("核验说明", { exact: true }).fill("合成演示，招聘者核对两项原始证明");
  await page.getByRole("button", { name: "保存资格核验并留痕" }).click();
  await expect(page.getByTestId("qualification-status")).toContainText("已核验满足");
  const report = reportDocumentSchema.parse(await (await page.request.get(`/api/interviews/${id}/report`)).json());
  expect(report.campus).toMatchObject({ status: "met", mandatoryAsked: 9, mandatoryAnswered: 8 }); expect(report.questions).toHaveLength(8);
  expect(report.recommendation).toBe("strong_yes"); expect(report.metadata.totalTokens).toBeGreaterThan(0);
  await page.emulateMedia({ media: "print" });
  const sheets = page.getByTestId("report-sheet"); await expect(sheets).toHaveCount(2);
  const heights = await sheets.evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  expect(heights.every((height) => height <= 1047)).toBe(true);
  for (let index = 0; index < 2; index++) await sheets.nth(index).screenshot({ path: test.info().outputPath(`graduate-page-${index + 1}.png`) });
  const pdf = await page.pdf({ path: test.info().outputPath("graduate-report.pdf"), format: "A4", preferCSSPageSize: true, printBackground: true });
  expect(pdf.toString("latin1").match(/\/Type\s*\/Page\b/g)).toHaveLength(2);
  await page.emulateMedia({ media: "screen" });
  await page.getByLabel("CET-4核验分数").fill("424"); await page.getByLabel("核验说明", { exact: true }).fill("更正原件成绩为424分，不满足本岗位标准");
  await page.getByRole("button", { name: "保存资格核验并留痕" }).click();
  await expect(page.getByTestId("qualification-status")).toContainText("已核验不满足");
  await expect(page.locator(".report-recommendation h2")).toContainText("mixed");
  await page.reload(); await expect(page.getByLabel("CET-4核验分数")).toHaveValue("424");
  await page.getByLabel("复核说明", { exact: true }).fill("已确认硬指标不满足，交由招聘者人工处理，不自动淘汰");
  await page.getByRole("button", { name: "确认人工复核完成" }).click();
  await expect(page.getByText("已人工复核 · v3")).toBeVisible();
});
