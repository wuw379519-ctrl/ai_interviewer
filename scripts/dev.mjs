import process from "node:process";
import path from "node:path";
import console from "node:console";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { spawn, spawnSync } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { createServer } from "node:net";
import { root, spawnPython } from "./python.mjs";
import { httpsOrigin, publicAccess } from "./public-access.mjs";

const args = process.argv.slice(2);
const argument = (name, fallback) => { const index = args.indexOf(name); return index < 0 ? fallback : args[index + 1]; };
const accessFile = path.join(root, ".data", "public-access.json");
if (args.includes("--public-access")) {
  if (args.length !== 1) throw Error("--public-access 单独运行，仅显示两种网页访问码。");
  const access = publicAccess(accessFile, process.env);
  console.log(`招聘者访问码：${access.RECRUITER_PASSWORD}\n管理员访问码：${access.ADMIN_PASSWORD}`);
  process.exit(0);
}
const publicOrigin = args.includes("--public-url") ? httpsOrigin(argument("--public-url")) : undefined;
const webPort = argument("--web-port", publicOrigin ? "3100" : "3000"), apiPort = argument("--api-port", "8000");
if (![webPort, apiPort].every((port) => /^\d{2,5}$/.test(port) && Number(port) > 0 && Number(port) <= 65535) ||
    Number(webPort) === Number(apiPort)) throw Error("前端和 API 必须使用不同的有效端口");
const apiURL = `http://127.0.0.1:${apiPort}`;
const webURL = `http://127.0.0.1:${webPort}`;
const webDir = path.join(root, "apps", "web");
if (publicOrigin && !existsSync(path.join(webDir, process.env.NEXT_DIST_DIR ?? ".next", "BUILD_ID"))) {
  throw Error("公网模式需要生产构建，请先运行 pnpm build。");
}
const apiEnv = publicOrigin
  ? { ...publicAccess(accessFile, process.env), APP_ENV: "production", DEMO_MODE: "false", APP_BASE_URL: publicOrigin,
    STT_PROVIDER: "auto", STT_BASE_URL: "", STT_MODEL: "", TTS_PROVIDER: "local" }
  : { APP_ENV: "development", APP_BASE_URL: process.env.APP_BASE_URL ?? webURL };
for (const port of [webPort, apiPort]) {
  await new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", () => reject(Error(`端口${port}已占用，请停止该端口的旧服务后再启动。`)));
    probe.listen(Number(port), "127.0.0.1", () => probe.close(resolve));
  });
}
const api = spawnPython(["-m", "uvicorn", "interviewer.main:app", "--app-dir", "apps/api", "--host", "127.0.0.1", "--port", apiPort, "--no-access-log"],
  { env: apiEnv });
let web;
let stopped = false;
function stop() {
  if (stopped) return;
  stopped = true;
  for (const child of [api, web]) {
    if (!child?.pid || child.exitCode !== null) continue;
    if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
    else child.kill();
  }
}
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, stop);
api.on("error", () => { console.error("Python API无法启动，请先安装README中的依赖。"); stop(); process.exitCode = 1; });
api.on("exit", (code) => { if (!stopped) { console.error(`Python API已退出（${code ?? "signal"}）`); stop(); process.exitCode = 1; } });
let ready = false;
for (let attempt = 0; attempt < 60 && !stopped; attempt++) {
  try { if ((await globalThis.fetch(`${apiURL}/api/ready`, { signal: globalThis.AbortSignal.timeout(1500) })).ok) { ready = true; break; } } catch { /* startup */ }
  await delay(500);
}
if (!ready) { console.error("Python API尚未就绪，请检查数据库配置和部署探针。"); stop(); process.exitCode = 1; }
else {
  const requireWeb = createRequire(path.join(webDir, "package.json"));
  web = spawn(process.execPath, [requireWeb.resolve("next/dist/bin/next"), publicOrigin ? "start" : "dev", "--hostname", "127.0.0.1", "--port", webPort],
    { cwd: webDir, env: { ...process.env, PYTHON_API_URL: apiURL }, windowsHide: true, stdio: "inherit" });
  web.on("error", () => { console.error("前端无法启动"); stop(); process.exitCode = 1; });
  web.on("exit", (code) => { stop(); process.exitCode = code ?? 1; });
  if (publicOrigin) console.log(`已配置公网访问地址 ${publicOrigin}，请将 HTTPS 入口转发到 ${webURL}。`);
}
