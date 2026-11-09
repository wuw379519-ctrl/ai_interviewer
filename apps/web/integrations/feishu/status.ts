import { z } from "zod";
import type { FeishuPublicConfig } from "./types";

export const feishuStatusSchema = z.object({
  configured: z.boolean(),
  appId: z.string(),
  oauthRedirectUri: z.string(),
});

/** Runtime Feishu public status from the Python backend (via same-origin proxy). */
export async function getFeishuStatus(signal?: AbortSignal): Promise<FeishuPublicConfig> {
  const response = await fetch("/api/feishu/status", { method: "GET", cache: "no-store", signal });
  const raw: unknown = await response.json();
  return feishuStatusSchema.parse(raw);
}
