import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  FEISHU_OAUTH_START_HREF,
  FeishuLoginButton,
  FeishuLoginLink,
  shouldShowFeishuLogin,
} from "./feishu-login-button";

describe("FeishuLoginButton", () => {
  it("hides the button when Feishu status is not configured", () => {
    expect(shouldShowFeishuLogin({
      configured: false, appId: "", oauthRedirectUri: "", loginEnabled: false,
    })).toBe(false);
    expect(renderToStaticMarkup(createElement(FeishuLoginButton))).toBe("");
  });

  it("points the configured button at /api/feishu/oauth/start", () => {
    expect(shouldShowFeishuLogin({
      configured: true,
      appId: "cli_fixture",
      oauthRedirectUri: "https://example.invalid/login/feishu",
      loginEnabled: true,
    })).toBe(true);
    const html = renderToStaticMarkup(createElement(FeishuLoginLink));
    expect(html).toContain(`href="${FEISHU_OAUTH_START_HREF}"`);
    expect(html).toContain("使用飞书登录");
    expect(FEISHU_OAUTH_START_HREF).toBe("/api/feishu/oauth/start");
  });

  it("stays hidden when configured but loginEnabled is false", () => {
    expect(shouldShowFeishuLogin({
      configured: true,
      appId: "cli_fixture",
      oauthRedirectUri: "https://example.invalid/login/feishu",
      loginEnabled: false,
    })).toBe(false);
  });
});
