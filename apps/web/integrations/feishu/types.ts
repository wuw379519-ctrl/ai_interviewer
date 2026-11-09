/** Shared Feishu frontend types (skeleton — no live SDK binding yet). */

export type FeishuStatusValue = "not_configured" | "not_implemented";

export type FeishuPublicConfig = {
  configured: boolean;
  appId: string;
  oauthRedirectUri: string;
  loginEnabled: boolean;
};

export type FeishuUserProfile = {
  openId: string;
  unionId: string;
  name: string;
  avatarUrl?: string;
};

export type FeishuResult<T extends object = object> = {
  status: FeishuStatusValue;
  message: string;
} & T;
