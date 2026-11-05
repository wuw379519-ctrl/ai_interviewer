import { afterEach, expect, it, vi } from "vitest";
import { forwardPython } from "./python-proxy";
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
it("仅向固定Python服务转发，保留鉴权和cookie，流式透传SSE", async () => {
  vi.stubEnv("PYTHON_API_URL", "http://127.0.0.1:8101");
  const upstream = vi.fn(async (url: URL, init: RequestInit) => {
    expect(url.origin).toBe("http://127.0.0.1:8101"); expect(url.pathname).toBe("/api/interviews/fixture/turns");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer fixture");
    return new Response("event: done\ndata: {}\n\n", { headers: { "Content-Type": "text/event-stream", "Set-Cookie": "aii_recruiter=fixture; HttpOnly; SameSite=Strict" } });
  });
  vi.stubGlobal("fetch", upstream);
  const result = await forwardPython(new Request("http://frontend.test/api/interviews/fixture/turns", { method: "POST", headers: { Authorization: "Bearer fixture" }, body: "{}" }));
  expect(await result.text()).toContain("event: done"); expect(result.headers.get("set-cookie")).toContain("HttpOnly"); expect(upstream).toHaveBeenCalledOnce();
});
it("后端离线时返回统一503，不暴露网络异常和密钥", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(Error("secret-connection-error")));
  const result = await forwardPython(new Request("http://frontend.test/api/ready"));
  expect(result.status).toBe(503); expect(await result.text()).not.toContain("secret-connection-error");
});
