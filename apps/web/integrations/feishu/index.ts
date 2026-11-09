/**
 * Feishu frontend access points (skeleton).
 * Secrets live in `./server` (server-only) and are not re-exported here.
 */

export type { FeishuPublicConfig } from "./config";
export { getFeishuStatus, feishuStatusSchema } from "./status";
export {
  beginFeishuAuth,
  completeFeishuAuth,
  fetchFeishuUserProfile,
} from "./auth";
export {
  exchangeAuthCode,
  fetchJsapiSignature,
  notifyFeishuBot,
} from "./api";
export {
  initFeishuJsapi,
  isInsideFeishuClient,
  requestFeishuAccess,
} from "./jsapi";
export type {
  FeishuResult,
  FeishuStatusValue,
  FeishuUserProfile,
} from "./types";
