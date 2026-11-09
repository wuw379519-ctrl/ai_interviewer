import type { FeishuPublicConfig, FeishuResult } from "./types";

export function isInsideFeishuClient(): boolean {
  if (typeof navigator === "undefined") return false;
  // TODO: replace heuristic with Feishu-documented detection when wiring JSAPI.
  return /Lark|Feishu/i.test(navigator.userAgent);
}

export async function initFeishuJsapi(status: FeishuPublicConfig): Promise<FeishuResult> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书应用未配置。" };
  }
  // TODO: load Feishu JSSDK, then call tt.config / tt.requestAccess with appId.
  void status.appId;
  return { status: "not_implemented", message: "飞书 JSAPI 尚未实现。" };
}

export async function requestFeishuAccess(
  status: FeishuPublicConfig,
  _scopes: readonly string[] = [],
): Promise<FeishuResult> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书应用未配置。" };
  }
  // TODO: invoke tt.requestAccess({ scopeList: [...] }) when SDK is wired.
  return { status: "not_implemented", message: "requestAccess 尚未实现。" };
}
