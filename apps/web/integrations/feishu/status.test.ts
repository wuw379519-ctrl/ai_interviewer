import { afterEach, describe, expect, it, vi } from "vitest";
import { beginFeishuAuth, completeFeishuAuth, fetchFeishuUserProfile } from "./auth";
import { exchangeAuthCode, fetchJsapiSignature, notifyFeishuBot } from "./api";
import { initFeishuJsapi, requestFeishuAccess } from "./jsapi";
import { getFeishuStatus } from "./status";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const emptyStatus = { configured: false, appId: "", oauthRedirectUri: "", loginEnabled: false };
const readyStatus = {
  configured: true,
  appId: "cli_fixture_app",
  oauthRedirectUri: "https://example.invalid/feishu/callback",
  loginEnabled: true,
};

describe("feishu frontend status contract", () => {
  it("unconfigured status is not_configured and only status hits the network", async () => {
    const fetchSpy = vi.fn(async () => Response.json(emptyStatus));
    vi.stubGlobal("fetch", fetchSpy);

    const status = await getFeishuStatus();
    expect(status).toEqual(emptyStatus);
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const results = await Promise.all([
      initFeishuJsapi(status),
      requestFeishuAccess(status),
      beginFeishuAuth(status),
      completeFeishuAuth(status, "unused-code"),
      fetchJsapiSignature(status, "https://example.invalid/"),
      exchangeAuthCode(status, "unused-code"),
    ]);
    expect(results.map((row) => row.status)).toEqual([
      "not_configured",
      "not_configured",
      "not_configured",
      "not_configured",
      "not_configured",
      "not_configured",
    ]);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("configured stub still leaves JSAPI as not_implemented", async () => {
    const fetchSpy = vi.fn(async () => Response.json(readyStatus));
    vi.stubGlobal("fetch", fetchSpy);

    const status = await getFeishuStatus();
    expect(status.configured).toBe(true);
    expect(status.loginEnabled).toBe(true);
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const result = await initFeishuJsapi(status);
    expect(result.status).toBe("not_implemented");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("profile and bot helpers stay offline after a single status fetch", async () => {
    const fetchSpy = vi.fn(async () => Response.json(emptyStatus));
    vi.stubGlobal("fetch", fetchSpy);
    const status = await getFeishuStatus();
    expect((await fetchFeishuUserProfile(status)).status).toBe("not_configured");
    expect((await notifyFeishuBot(status, "interview-id-only")).status).toBe("not_configured");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("configured stub leaves auth completion not_implemented without extra fetch", async () => {
    const fetchSpy = vi.fn(async () => Response.json(readyStatus));
    vi.stubGlobal("fetch", fetchSpy);
    const status = await getFeishuStatus();
    expect((await completeFeishuAuth(status, "code")).status).toBe("not_implemented");
    expect((await exchangeAuthCode(status, "code")).status).toBe("not_implemented");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("throws a readable error when status HTTP fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 503 })));
    await expect(getFeishuStatus()).rejects.toThrow("飞书状态接口返回 503");
  });

  it("rejects status payloads missing loginEnabled", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      Response.json({ configured: true, appId: "cli", oauthRedirectUri: "https://example.invalid/" }),
    ));
    await expect(getFeishuStatus()).rejects.toThrow();
  });

  it("configured beginFeishuAuth stays not_implemented", async () => {
    const fetchSpy = vi.fn(async () => Response.json(readyStatus));
    vi.stubGlobal("fetch", fetchSpy);
    const status = await getFeishuStatus();
    expect((await beginFeishuAuth(status)).status).toBe("not_implemented");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
