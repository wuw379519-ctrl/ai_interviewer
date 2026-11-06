import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("正式文字面试从固定题到管理员证据评价", async ({ page, browser }) => {
  test.setTimeout(120000);
  const name = `合成正式候选人 ${randomUUID().slice(0, 6)}`;
  const answer = "我主导数据同步项目，个人负责重试与监控设计，协调团队分歧达成一致。上线后失败率降低40%，验证机制在另一个项目复用。";
  const questions = ["请介绍一次你主导交付的经历？", "你怎样协调项目分歧？", "离线数据管道", "库存同步服务", "离线数据管道"] as const;

  await page.goto("/");
  await page.getByRole("link", { name: "发起正式面试" }).click();
  await page.getByRole("button", { name: "进入演示工作台" }).click();
  await page.getByLabel("岗位名称").fill("数据平台工程师");
  await page.getByLabel("候选人姓名").fill(name);
  await page.getByLabel("岗位 JD").fill("负责维护离线数据管道和数据质量告警，并与业务团队制定可验证的可靠性指标。");
  await page.getByLabel("候选人简历").fill("简历项目：重构库存同步服务，降低超时比例，并为同步任务补充监控与回滚机制。");
  await page.getByLabel("固定题（每行一题）").fill(questions.slice(0, 2).join("\n"));
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
      await expect(candidate.getByTestId("current-question")).toHaveText(question);
    }
    await candidate.getByLabel("你的回答").fill(answer);
    await candidate.getByRole("button", { name: "发送回答" }).click();
  }
  await expect(candidate.getByRole("heading", { name: "感谢分享，这次对话已保存。" })).toBeVisible();
  await page.getByRole("button", { name: "刷新详情" }).click();
  await page.getByRole("button", { name: "生成面试评价" }).click();
  await expect(page.getByText("证据覆盖", { exact: true })).toBeVisible();
  await expect(page.getByText("100%", { exact: true })).toBeVisible();
  await expect(page.getByText("候选人原话", { exact: false }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText("证据覆盖", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "面试对话" })).toBeVisible();
  await candidate.close();
});
