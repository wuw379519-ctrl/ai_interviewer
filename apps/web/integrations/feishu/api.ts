import type { FeishuPublicConfig, FeishuResult } from "./types";

/** Frontend ↔ backend Feishu bridge. Never call open.feishu.cn from the browser. */

export async function fetchJsapiSignature(
  status: FeishuPublicConfig,
  _url: string,
): Promise<FeishuResult<{ signature: string }>> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书未配置，无法请求 JSAPI 签名。", signature: "" };
  }
  // TODO: GET/POST a future same-origin route that uses server-side secrets.
  return { status: "not_implemented", message: "JSAPI 签名接口占位。", signature: "" };
}

export async function exchangeAuthCode(
  status: FeishuPublicConfig,
  _code: string,
): Promise<FeishuResult<{ sessionHint: string }>> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书未配置，无法换取登录会话。", sessionHint: "" };
  }
  // TODO: POST /api/feishu/oauth/callback once the login page is wired.
  return { status: "not_implemented", message: "免登 code 换取会话接口占位。", sessionHint: "" };
}

export async function notifyFeishuBot(
  status: FeishuPublicConfig,
  _text: string,
): Promise<FeishuResult<{ delivered: boolean }>> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书未配置，跳过机器人通知。", delivered: false };
  }
  // TODO: POST a server route; webhook stays server-side. Payload may only include interview id/status/link.
  return { status: "not_implemented", message: "机器人通知接口占位。", delivered: false };
}
