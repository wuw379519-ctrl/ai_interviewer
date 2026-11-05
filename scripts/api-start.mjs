import process from "node:process";
import { spawnPython } from "./python.mjs";
const production = process.argv.includes("--production");
const child = spawnPython(["-m", "uvicorn", "interviewer.main:app", "--app-dir", "apps/api", "--host", process.env.API_HOST ?? "127.0.0.1", "--port", process.env.API_PORT ?? "8000", "--no-access-log"],
  { env: { APP_ENV: production ? "production" : "development" } });
child.on("exit", (code) => { process.exitCode = code ?? 1; });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
