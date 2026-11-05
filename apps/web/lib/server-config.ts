import { z } from "zod";
/** Cosmetic entry mode comes from Python; this is not authorization. */
export async function demoMode(): Promise<boolean> {
  try {
    const base = process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000";
    const response = await fetch(new URL("/api/health", base), { cache: "no-store", signal: AbortSignal.timeout(5000) });
    const raw: unknown = await response.json();
    return response.ok && z.object({ demoMode: z.boolean() }).parse(raw).demoMode;
  } catch { return false; }
}
