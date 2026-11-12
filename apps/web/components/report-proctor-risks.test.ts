import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReportProctorRisks } from "./report-proctor-risks";

describe("ReportProctorRisks", () => {
  it("renders empty state when no risk items", () => {
    const html = renderToStaticMarkup(createElement(ReportProctorRisks, { items: [] }));
    expect(html).toContain('data-testid="report-proctor-risks"');
    expect(html).toContain("本场未触发规则化信号");
    expect(html).toContain("不参与评分");
  });

  it("distinguishes hint vs review and never implies auto decision", () => {
    const html = renderToStaticMarkup(createElement(ReportProctorRisks, {
      items: [
        {
          code: "excessive_tab_switch",
          severity: "review",
          message: "切屏过多，建议人工核对",
          signalCount: 3,
          affectsScore: false,
          forHumanReview: true,
        },
        {
          code: "high_silence_ratio",
          severity: "hint",
          message: "静音比例偏高",
          signalCount: 1,
          affectsScore: false,
          forHumanReview: false,
        },
      ],
    }));
    expect(html).toContain('data-testid="proctor-risk-excessive_tab_switch"');
    expect(html).toContain("建议人工关注");
    expect(html).toContain("仅提示");
    expect(html).toContain("不打分");
    expect(html).toContain("不据此录用或淘汰");
  });
});
