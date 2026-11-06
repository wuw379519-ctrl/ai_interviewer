"use client";

import { useState } from "react";
import { z } from "zod";
import { api, ClientApiError } from "@/lib/client-api";

export function needsLogin(error: unknown) {
  return error instanceof ClientApiError && ["UNAUTHORIZED", "FORBIDDEN"].includes(error.code);
}

export function WorkspaceLogin({ admin = false, demo, onReady }: {
  admin?: boolean;
  demo: boolean;
  onReady: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const role = admin ? "管理员" : "招聘者";

  async function login(accessCode: string) {
    setBusy(true);
    setError("");
    try {
      await api(admin ? "/api/admin/login" : "/api/auth/login", z.object({ ok: z.boolean() }), {
        method: "POST", body: { accessCode },
      });
      await onReady();
    } catch (error) {
      setError(error instanceof Error ? error.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel formal-login">
    <p className="eyebrow">WORKSPACE ACCESS</p>
    <h2>{role}登录</h2>
    <p className="muted">{admin ? "使用独立的管理员会话查阅面试记录。" : "登录后即可配置问题并生成候选人专属邀请。"}</p>
    <form onSubmit={(event) => {
      event.preventDefault();
      void login(String(new FormData(event.currentTarget).get("accessCode") ?? ""));
    }}>
      {!demo && <label>{role}访问码<input name="accessCode" type="password" autoComplete="current-password" required /></label>}
      <button className="button primary" disabled={busy}>
        {busy ? "正在登录…" : demo ? admin ? "进入演示管理台" : "进入演示工作台" : `登录${role}`}
      </button>
    </form>
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
