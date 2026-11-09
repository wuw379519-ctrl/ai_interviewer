import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { FeishuCallbackPanel, resolveFeishuCallbackPhase } from "./feishu-callback";

describe("feishu callback page", () => {
  it("treats missing code as cancelled authorization", () => {
    expect(resolveFeishuCallbackPhase({})).toEqual({ kind: "cancelled" });
    expect(resolveFeishuCallbackPhase({ error: "access_denied" })).toEqual({ kind: "cancelled" });
  });

  it("renders the cancelled placeholder when GET /login/feishu has no code", () => {
    const html = renderToStaticMarkup(createElement(FeishuCallbackPanel, { params: {} }));
    expect(html).toContain("已取消授权");
    expect(html).toContain("返回登录");
    expect(html).toContain('href="/login"');
  });
});
