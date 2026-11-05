import { NextResponse } from "next/server";

/** Same-origin transport only. Authentication, consent, storage and scoring live in FastAPI. */
export async function forwardPython(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const headers = new Headers(request.headers);
  for (const key of ["host", "connection", "content-length", "transfer-encoding"]) headers.delete(key);
  try {
    const base = new URL(process.env.PYTHON_API_URL ?? "http://127.0.0.1:8000");
    if (!["http:", "https:"].includes(base.protocol) || base.username || base.password || !incoming.pathname.startsWith("/api/")) {
      return NextResponse.json({ error: { code: "BACKEND_UNAVAILABLE", message: "后端服务配置无效", details: null } }, { status: 503 });
    }
    const target = new URL(incoming.pathname + incoming.search, base);
    const options: RequestInit & { duplex?: "half" } = { method: request.method, headers, cache: "no-store", redirect: "manual", signal: request.signal };
    if (!["GET", "HEAD"].includes(request.method) && request.body) { options.body = request.body; options.duplex = "half"; }
    const upstream = await fetch(target, options);
    const output = new Headers(upstream.headers);
    for (const key of ["connection", "transfer-encoding", "content-encoding", "content-length"]) output.delete(key);
    output.set("Cache-Control", "no-store");
    return new Response(upstream.body, { status: upstream.status, headers: output });
  } catch {
    return NextResponse.json({ error: { code: "BACKEND_UNAVAILABLE", message: "Python后端暂不可用，请稍后重试", details: null } }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
