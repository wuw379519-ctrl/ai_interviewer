import { afterEach, describe, expect, it, vi } from "vitest";
import { questionAudio } from "./question-audio";

afterEach(() => vi.unstubAllGlobals());
describe("server question audio", () => {
  it("sends position and token without transmitting client text", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(new Uint8Array([1, 2]), { headers: { "Content-Type": "audio/mpeg" } }));
    vi.stubGlobal("fetch", fetcher);
    const signal = new AbortController().signal;
    expect((await questionAudio("fixture", "synthetic-token", 2, 7, signal)).size).toBe(2);
    expect(fetcher).toHaveBeenCalledWith("/api/interviews/fixture/tts?questionSeq=2&turnSeq=7", {
      headers: { Authorization: "Bearer synthetic-token" }, cache: "no-store", signal,
    });
  });
  it("preserves an explicit server failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: { code: "SPEECH_UNAVAILABLE", message: "合成故障提示", details: null } }, { status: 503 })));
    await expect(questionAudio("fixture", "token", 1, 1, new AbortController().signal)).rejects.toThrow("合成故障提示");
  });
  it.each([new Response("html", { headers: { "Content-Type": "text/html" } }), new Response(null, { headers: { "Content-Type": "audio/mpeg" } })])("rejects non-audio or empty success responses", async (response) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(questionAudio("fixture", "token", 1, 1, new AbortController().signal)).rejects.toThrow();
  });
});
