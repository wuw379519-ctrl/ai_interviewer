import type { FeishuPublicConfig, FeishuResult, FeishuUserProfile } from "./types";

export async function beginFeishuAuth(status: FeishuPublicConfig): Promise<FeishuResult<{ code: string; user: FeishuUserProfile | null }>> {
  if (!status.configured || !status.appId || !status.oauthRedirectUri) {
    return { status: "not_configured", message: "飞书应用未配置。", code: "", user: null };
  }
  // TODO: redirect to Feishu authorize URL or tt.requestAuthCode inside Feishu.
  return { status: "not_implemented", message: "免登授权开始占位。", code: "", user: null };
}

export async function completeFeishuAuth(
  status: FeishuPublicConfig,
  _code: string,
): Promise<FeishuResult<{ code: string; user: FeishuUserProfile | null }>> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书应用未配置。", code: "", user: null };
  }
  // TODO: POST code to /api/feishu/oauth/callback via same-origin proxy.
  return { status: "not_implemented", message: "免登完成占位。", code: "", user: null };
}

export async function fetchFeishuUserProfile(
  status: FeishuPublicConfig,
): Promise<FeishuResult<{ user: FeishuUserProfile | null }>> {
  if (!status.configured || !status.appId) {
    return { status: "not_configured", message: "飞书应用未配置。", user: null };
  }
  // TODO: call backend session endpoint after login wiring.
  return { status: "not_implemented", message: "用户资料获取占位。", user: null };
}
