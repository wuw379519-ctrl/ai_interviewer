import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("正式文字面试从固定题到管理员证据评价", async ({ page, browser }) => {
  test.setTimeout(120000);
  const name = `合成正式候选人 ${randomUUID().slice(0, 6)}`;
  const answer = "我主导数据同步项目，个人负责重试与监控设计，协调团队分歧达成一致。上线后失败率降低40%，验证机制在另一个项目复用。";
  const questions = ["请用约1分钟介绍你的研究方向、相关技能，以及一项与你应聘岗位相关的个人工作。",
    "CET-4总分", "你的个人贡献", "研究生期间是否曾有课程不及格记录", "为什么选择本岗位",
    "期望月薪、期望年薪及可接受最低薪资", "未来1至3年", "一项优势和一项待提升能力", "到岗时间、工作地点或出差安排",
    "离线数据管道", "库存同步服务", "离线数据管道"] as const;

  await page.goto("/");
  await page.getByRole("link", { name: "发起正式面试" }).click();
  await page.getByRole("button", { name: "进入演示工作台" }).click();
  await page.getByLabel("岗位名称").fill("数据平台工程师");
  await page.getByLabel("候选人姓名").fill(name);
  await page.getByLabel("岗位 JD").fill("负责维护离线数据管道和数据质量告警，并与业务团队制定可验证的可靠性指标。");
  await page.getByLabel("候选人简历").fill("简历项目：重构库存同步服务，降低超时比例，并为同步任务补充监控与回滚机制。");
  await expect(page.getByLabel("固定题（每行一题）")).toHaveCount(0);
  await page.getByRole("button", { name: "生成候选人邀请" }).click();
  await expect(page.getByRole("heading", { name: "邀请已就绪" })).toBeVisible();
  const invitation = await page.getByLabel("候选人邀请链接").inputValue();

  const candidate = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await candidate.goto(invitation);
  await expect(candidate.getByRole("button", { name: "同意并开始面试" })).toBeDisabled();
  await expect(candidate.getByLabel("你的回答")).toHaveCount(0);
  await candidate.getByRole("checkbox", { name: "我已阅读并明确同意以上说明" }).check();
  await candidate.getByRole("button", { name: "同意并开始面试" }).click();
  await expect(candidate.getByTestId("current-question")).toHaveText(questions[0]);
  await expect(candidate.getByRole("button", { name: "开始语音输入" })).toHaveCount(0);
  expect(await candidate.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  await page.getByRole("link", { name: "面试记录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();
  await page.getByRole("button", { name: "进入演示管理台" }).click();
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toContainText("进行中");
  await row.getByRole("link", { name: "查看记录" }).click();
  await expect(page.getByRole("heading", { name: /合成正式候选人/ })).toBeVisible();
  await expect(page.getByText(questions[0], { exact: true })).toBeVisible();

  for (const [index, question] of questions.entries()) {
    await expect(candidate.getByTestId("current-question")).toContainText(question);
    if (index === 1) {
      await candidate.reload();
      await expect(candidate.getByTestId("current-question")).toContainText(question);
    }
    if (index === 1 || index === 3) {
      await expect(candidate.getByRole("button", { name: "跳过本题" })).toBeDisabled();
    }
    await candidate.getByLabel("你的回答").fill(index === 1 ? "四级424分，等待核验。" : index === 3 ? "研究生期间无挂科，等待核验。" : answer);
    await candidate.getByRole("button", { name: "发送回答" }).click();
  }
  await expect(candidate.getByRole("heading", { name: "感谢分享，这次对话已保存。" })).toBeVisible();
  await page.getByRole("button", { name: "刷新详情" }).click();
  await page.getByRole("button", { name: "生成面试评价" }).click();
  await expect(page.getByText("证据覆盖", { exact: true })).toBeVisible();
  await expect(page.getByText("100%", { exact: true })).toBeVisible();
  await expect(page.getByText(/候选人原话 · 第/).first()).toBeVisible();
  await expect(page.getByTestId("qualification-status")).toContainText("待人工核验");
  await page.getByLabel("CET-4核验分数（未知留空）").fill("424");
  await page.getByLabel("研究生期间曾挂科门数（未知留空）").fill("0");
  await page.getByLabel("四级成绩报告核验来源").fill("已查看合成四级成绩报告");
  await page.getByLabel("完整研究生成绩单核验来源").fill("已查看合成完整研究生成绩单");
  await page.getByLabel("核验说明").fill("已核对本次合成资格材料");
  await page.getByRole("button", { name: "保存资格核验并留痕" }).click();
  await expect(page.getByTestId("qualification-status")).toContainText("已核验不满足");
  await expect(page.getByText("人工核验确认未满足岗位硬性资格。", { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("qualification-status")).toContainText("已核验不满足");
  await expect(page.getByText("证据覆盖", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "面试对话" })).toBeVisible();
  await candidate.close();
});
