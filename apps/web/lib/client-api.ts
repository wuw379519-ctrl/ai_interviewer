import { z } from "zod";
import { apiErrorSchema, turnResultSchema } from "@aii/core";
export class ClientApiError extends Error {
  constructor(public readonly code: string, message: string) { super(message); this.name = "ClientApiError"; }
}

export async function api<T>(path: string, schema: z.ZodType<T, z.ZodTypeDef, unknown>, options: { method?: string; body?: unknown; token?: string; key?: string; signal?: AbortSignal } = {}): Promise<T> {
  const form = options.body instanceof FormData;
  const response = await fetch(path, { method: options.method ?? "GET", cache: "no-store", signal: options.signal,
    headers: { ...(form ? {} : { "Content-Type": "application/json" }), ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      ...(options.key ? { "Idempotency-Key": options.key } : {}) },
    ...(options.body === undefined ? {} : { body: form ? options.body as FormData : JSON.stringify(options.body) }),
  });
  const raw: unknown = await response.json();
  if (!response.ok) { const error = apiErrorSchema.safeParse(raw).data?.error; throw new ClientApiError(error?.code ?? "UNKNOWN", error?.message ?? "请求未成功，请重试"); }
  return schema.parse(raw);
}

export async function streamTurn(id: string, token: string, key: string, body: { action: string; content?: string }, onText: (text: string) => void) {
  const response = await fetch(`/api/interviews/${id}/turns`, { method: "POST", headers: {
    "Content-Type": "application/json", Authorization: `Bearer ${token}`, "Idempotency-Key": key,
  }, body: JSON.stringify(body) });
  if (!response.ok) {
    const raw: unknown = await response.json();
    throw new Error(apiErrorSchema.safeParse(raw).data?.error.message ?? "提交失败");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("流连接未建立");
  const decoder = new TextDecoder();
  let buffer = "", text = "", done: z.infer<typeof turnResultSchema> | undefined;
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value, { stream: !chunk.done });
      const events = buffer.replace(/\r\n/g, "\n").split("\n\n");
      buffer = events.pop() ?? "";
      for (const event of events) {
        const kind = event.split("\n").find((line) => line.startsWith("event: "))?.slice(7);
        const data = event.split("\n").filter((line) => line.startsWith("data: ")).map((line) => line.slice(6)).join("\n");
        if (!data) continue;
        const raw: unknown = JSON.parse(data);
        if (kind === "delta") { text += z.object({ text: z.string() }).parse(raw).text; onText(text); }
        if (kind === "done") done = turnResultSchema.parse(raw);
      }
      if (chunk.done) break;
    }
  } finally { reader.releaseLock(); }
  if (!done) throw new Error("连接中断，回答可能已保存。请重试确认，系统会自动去重。");
  return done;
}
