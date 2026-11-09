import { randomBytes } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { URL } from "node:url";

const names = ["RECRUITER_PASSWORD", "ADMIN_PASSWORD", "AUTH_SECRET"];

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
  const { RECRUITER_PASSWORD: recruiter, ADMIN_PASSWORD: admin, AUTH_SECRET: secret } = credentials ?? {};
  const validCode = (value) => typeof value === "string" && /^[!-~]{16,200}$/.test(value);
  if (!validCode(recruiter) || !validCode(admin) || typeof secret !== "string" || secret.trim().length < 32 ||
      new Set([recruiter, admin, secret]).size !== 3) {
    throw Error("公网模式需要两组不同的 16–200 位可打印 ASCII 访问码，以及独立的至少 32 字符 AUTH_SECRET。");
  }
  return { RECRUITER_PASSWORD: recruiter, ADMIN_PASSWORD: admin, AUTH_SECRET: secret };
}

export function publicAccess(file, env) {
  if (names.some((name) => env[name] !== undefined)) return validate(env);
  function read() {
    let raw;
    try { raw = readFileSync(file, "utf8"); } catch (error) {
      if (error.code === "ENOENT") return undefined;
      throw Error("无法读取 .data/public-access.json，请检查文件权限。");
    }
    let credentials;
    try { credentials = JSON.parse(raw); } catch {
      throw Error(".data/public-access.json 不是有效的 JSON，请检查此私有文件。");
    }
    return validate(credentials);
  }
  const saved = read();
  if (saved) return saved;

  const generated = {
    RECRUITER_PASSWORD: randomBytes(24).toString("base64url"),
    ADMIN_PASSWORD: randomBytes(24).toString("base64url"),
    AUTH_SECRET: randomBytes(32).toString("hex"),
  };
  mkdirSync(path.dirname(file), { recursive: true });
  try {
    writeFileSync(file, JSON.stringify(generated, null, 2) + "\n", { mode: 0o600, flag: "wx" });
  } catch (error) {
    if (error.code === "EEXIST") {
      const existing = read();
      if (existing) return existing;
    }
    throw Error("无法保存 .data/public-access.json，请检查文件权限。");
  }
  return generated;
}
