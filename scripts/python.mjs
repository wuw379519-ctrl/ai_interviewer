import process from "node:process";
import path from "node:path";
import { existsSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import console from "node:console";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function supported(executable) {
  return spawnSync(executable, ["-c", "import sys;raise SystemExit(0 if sys.version_info >= (3,11) else 1)"],
    { windowsHide: true, stdio: "ignore" }).status === 0;
}
export function pythonExecutable() {
  if (process.env.PYTHON_EXECUTABLE) {
    if (!supported(process.env.PYTHON_EXECUTABLE)) throw Error("PYTHON_EXECUTABLE必须指向可运行的Python3.11+解释器。");
    return process.env.PYTHON_EXECUTABLE;
  }
  for (const directory of [".venv", ".venv-clean", ".venv311"]) {
    const local = path.join(root, directory, process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (existsSync(local)) {
      if (!supported(local)) throw Error(`仓库${directory}无法运行或低于Python3.11；请通过PYTHON_EXECUTABLE指定已有3.11环境，不要覆盖原环境。`);
      return local;
    }
  }
  for (const name of ["python3.11", "python3", "python"]) {
    if (supported(name)) return name;
  }
  throw Error("未找到Python3.11+。请准备.venv或.venv-clean，或配置PYTHON_EXECUTABLE。见README。");
}
export function spawnPython(args, options = {}) {
  return spawn(pythonExecutable(), args, { cwd: root, windowsHide: true, stdio: "inherit", ...options,
    env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", PYTHONPATH: path.join(root, "apps/api") + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : ""), ...options.env } });
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const child = spawnPython(process.argv.slice(2));
    child.on("error", () => { console.error("Python启动失败，请检查.venv、.venv-clean和README。"); process.exitCode = 1; });
    child.on("exit", (code) => { process.exitCode = code ?? 1; });
    for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
