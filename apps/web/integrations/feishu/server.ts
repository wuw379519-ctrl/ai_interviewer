import "server-only";

import type { FeishuServerSecrets } from "./types";

function env(name: string): string {
  const value = process.env[name];
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Server-only secrets. Must never be imported from Client Components.
 * Prefer the Python Settings / `/api/feishu/*` routes for runtime truth;
 * these helpers exist for future Next server routes only.
 */
export function getFeishuServerSecrets(): FeishuServerSecrets {
  return {
    appSecret: env("FEISHU_APP_SECRET"),
    verificationToken: env("FEISHU_VERIFICATION_TOKEN"),
    encryptKey: env("FEISHU_ENCRYPT_KEY"),
    botWebhook: env("FEISHU_BOT_WEBHOOK"),
  };
}

export function isFeishuServerConfigured(secrets = getFeishuServerSecrets()): boolean {
  return Boolean(env("FEISHU_APP_ID") && secrets.appSecret && env("FEISHU_API_BASE_URL"));
}
