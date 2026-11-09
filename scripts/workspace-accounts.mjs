import { randomBytes } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { URL } from "node:url";

const secretNames = ["RECRUITER_PASSWORD", "ADMIN_PASSWORD", "AUTH_SECRET"];
const defaultUsernames = { ADMIN_USERNAME: "admin", RECRUITER_USERNAME: "recruiter" };

export function httpsOrigin(value) {
  const absoluteOrigin = /^https:\/\/[^/?#@\\\s]+\/?$/i;
  let url;
  try { url = new URL(value); } catch { /* Report a configuration error without echoing input. */ }
  if (!absoluteOrigin.test(value) || !url || url.protocol !== "https:" || url.username || url.password) {
    throw Error("--public-url 需要完整的 HTTPS origin，只填写协议、主机名和可选端口。");
  }
  return url.origin;
}

function validate(credentials) {
  const { RECRUITER_USERNAME, ADMIN_USERNAME, RECRUITER_PASSWORD: recruiter, ADMIN_PASSWORD: admin, AUTH_SECRET: secret } = credentials ?? {};
  const validUsername = (value) => typeof value === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}$/.test(value);
  const validPassword = (value) => typeof value === "string" && value.trim().length >= 16 && value.length <= 200;
  if (!validUsername(RECRUITER_USERNAME) || !validUsername(ADMIN_USERNAME) || RECRUITER_USERNAME === ADMIN_USERNAME) {
    throw Error("请配置两个不同的工作台账号名，长度 2–64 位，使用英文字母、数字、点、下划线或连字符。");
  }
  if (!validPassword(recruiter) || !validPassword(admin) || typeof secret !== "string" || secret.trim().length < 32 ||
      new Set([recruiter, admin, secret]).size !== 3) {
    throw Error("请配置两组不同的 16–200 位账号密码，以及独立的至少 32 字符 AUTH_SECRET。");
  }
  return { RECRUITER_USERNAME, ADMIN_USERNAME, RECRUITER_PASSWORD: recruiter, ADMIN_PASSWORD: admin, AUTH_SECRET: secret };
}

function readPrivateConfig(file) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return undefined;
    throw Error(`无法读取私有配置 ${path.basename(file)}，请检查权限及 JSON 格式。`);
  }
}

export function workspaceAccounts(file, previousFile, env) {
  if (secretNames.some((name) => env[name] !== undefined)) return validate({ ...defaultUsernames, ...env });
  const saved = readPrivateConfig(file);
  if (saved !== undefined) return validate(saved);

  const previousSecret = readPrivateConfig(previousFile)?.AUTH_SECRET;
  const generated = validate({
    ADMIN_USERNAME: env.ADMIN_USERNAME ?? defaultUsernames.ADMIN_USERNAME,
    RECRUITER_USERNAME: env.RECRUITER_USERNAME ?? defaultUsernames.RECRUITER_USERNAME,
    RECRUITER_PASSWORD: randomBytes(24).toString("base64url"),
    ADMIN_PASSWORD: randomBytes(24).toString("base64url"),
    AUTH_SECRET: typeof previousSecret === "string" && previousSecret.trim().length >= 32
      ? previousSecret : randomBytes(32).toString("hex"),
  });
  mkdirSync(path.dirname(file), { recursive: true });
  try {
    writeFileSync(file, JSON.stringify(generated, null, 2) + "\n", { mode: 0o600, flag: "wx" });
  } catch (error) {
    if (error.code === "EEXIST") {
      const existing = readPrivateConfig(file);
      if (existing !== undefined) return validate(existing);
    }
    throw Error("无法保存 .data/workspace-accounts.json，请检查文件权限。");
  }
  return generated;
}
