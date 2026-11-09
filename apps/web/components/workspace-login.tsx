"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { z } from "zod";
import { api, ClientApiError } from "@/lib/client-api";
import { FeishuLoginButton } from "./feishu-login-button";
import { Brand } from "./shell";

const loginSchema = z.object({ ok: z.literal(true), role: z.enum(["admin", "recruiter"]) });

export function needsLogin(error: unknown) {
  return error instanceof ClientApiError && ["UNAUTHORIZED", "FORBIDDEN"].includes(error.code);
}

export function WorkspaceLogin({ admin = false, demo, onReady }: {
  admin?: boolean;
  demo: boolean;
  onReady: (role: z.infer<typeof loginSchema>["role"]) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function login(body: { username?: string; password?: string }) {
    setBusy(true);
    setError("");
    try {
      const session = await api(admin ? "/api/admin/login" : "/api/auth/login", loginSchema, {
        method: "POST", body,
      });
      await onReady(session.role);
    } catch (error) {
      setError(error instanceof Error ? error.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel formal-login">
    <p className="eyebrow">WORKSPACE ACCESS</p>
    <h2>{admin ? "管理员登录" : "工作台登录"}</h2>
    <p className="muted">{admin ? "请输入管理员账号和密码，登录后可查阅面试记录。" : "使用你的账号和密码进入见微面试工作台。"}</p>
    <form onSubmit={(event) => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      void login(demo ? {} : { username: String(fields.get("username") ?? "").trim(),
        password: String(fields.get("password") ?? "") });
    }}>
      {!demo && <>
        <label>账号<input name="username" type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={64} required /></label>
        <label>密码<input name="password" type="password" autoComplete="current-password" maxLength={200} required /></label>
      </>}
      <button className="button primary" disabled={busy}>
        {busy ? "正在登录…" : demo ? admin ? "进入演示管理台" : "进入演示工作台" : "登录"}
      </button>
    </form>
    {!admin && !demo && <div className="button-row" style={{ marginTop: "1rem" }}><FeishuLoginButton /></div>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}

export function AccountLoginPage({ demo }: { demo: boolean }) {
  const router = useRouter();
  return <main className="account-login-page">
    <div className="account-login-layout">
      <header className="account-login-intro">
        <Brand />
        <h1>登录见微</h1>
        <p>发起面试、查看回答和评价，统一在工作台完成。</p>
      </header>
      <WorkspaceLogin demo={demo} onReady={(role) => router.replace(role === "admin" ? "/admin/interviews" : "/recruiter/formal")} />
    </div>
  </main>;
}
