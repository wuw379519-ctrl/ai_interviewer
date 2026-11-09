/** Shared Feishu frontend types (skeleton — no live SDK binding yet). */

export type FeishuStatusValue = "not_configured" | "not_implemented" | "ready";

export type FeishuPublicConfig = {
  configured: boolean;
  appId: string;
  oauthRedirectUri: string;
};

export type FeishuServerSecrets = {
  appSecret: string;
  verificationToken: string;
  encryptKey: string;
  botWebhook: string;
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
