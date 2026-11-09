"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { z } from "zod";
import { Brand } from "./shell";

const callbackSchema = z.object({ ok: z.literal(true), role: z.enum(["admin", "recruiter"]) });

export type FeishuCallbackParams = {
  code?: string;
  state?: string;
  error?: string;
};

export type FeishuCallbackPhase =
  | { kind: "cancelled" }
  | { kind: "exchanging" }
  | { kind: "success"; role: "admin" | "recruiter" }
  | { kind: "failed"; message: string };

export function resolveFeishuCallbackPhase(params: FeishuCallbackParams): FeishuCallbackPhase {
  if (!params.code || params.error === "access_denied") return { kind: "cancelled" };
  if (!params.state) return { kind: "failed", message: "缺少登录状态，请重新发起飞书登录。" };
  return { kind: "exchanging" };
}

function failureMessage(status: number, code: string | undefined): string {
  if (status === 403 || code === "FEISHU_ROLE_NOT_ALLOWED") return "飞书账号不在工作台白名单。";
  if (status === 502 || code === "FEISHU_UPSTREAM_FAILED") return "飞书上游暂时不可用，请稍后重试。";
  if (code === "FEISHU_STATE_INVALID") return "登录状态无效或已过期，请重新发起飞书登录。";
  if (code === "FEISHU_NOT_CONFIGURED") return "飞书应用尚未配置。";
  if (status === 400) return "飞书登录请求无效。";
  return "飞书登录失败，请返回后重试。";
}

export function FeishuCallbackPanel({ params }: { params: FeishuCallbackParams }) {
  const initial = resolveFeishuCallbackPhase(params);
  const [phase, setPhase] = useState<FeishuCallbackPhase>(initial);

  useEffect(() => {
    if (initial.kind !== "exchanging" || !params.code || !params.state) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch("/api/feishu/oauth/callback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: params.code, state: params.state }),
        });
        const raw: unknown = await response.json().catch(() => ({}));
        if (cancelled) return;
        if (response.ok) {
          const body = callbackSchema.parse(raw);
          setPhase({ kind: "success", role: body.role });
          window.location.replace(body.role === "admin" ? "/admin/interviews" : "/recruiter/formal");
          return;
        }
        const error = z.object({ error: z.object({ code: z.string().optional(), message: z.string().optional() }).optional() }).safeParse(raw);
        setPhase({
          kind: "failed",
          message: failureMessage(response.status, error.data?.error?.code) || error.data?.error?.message || "飞书登录失败。",
        });
      } catch {
        if (!cancelled) setPhase({ kind: "failed", message: "无法完成飞书登录，请检查网络后重试。" });
      }
    })();
    return () => { cancelled = true; };
  }, [initial.kind, params.code, params.state]);

  return <main className="account-login-page">
    <div className="account-login-layout">
      <header className="account-login-intro">
        <Brand />
        <h1>飞书登录</h1>
        <p>正在完成工作台免登。账号密码登录入口仍然保留。</p>
      </header>
      <section className="panel formal-login" data-testid="feishu-callback-panel">
        {phase.kind === "cancelled" && <>
          <p className="eyebrow">FEISHU OAUTH</p>
          <h2>已取消授权</h2>
          <p className="muted">未获得飞书授权码，或你在飞书侧取消了登录。</p>
          <Link className="button secondary" href="/login">返回登录</Link>
        </>}
        {phase.kind === "exchanging" && <>
          <p className="eyebrow">FEISHU OAUTH</p>
          <h2>正在登录…</h2>
          <p className="muted" role="status">正在换取工作台会话，请稍候。</p>
        </>}
        {phase.kind === "success" && <>
          <p className="eyebrow">FEISHU OAUTH</p>
          <h2>登录成功，正在跳转</h2>
          <p className="muted" role="status">即将进入{phase.role === "admin" ? "管理员" : "招聘者"}工作台。</p>
        </>}
        {phase.kind === "failed" && <>
          <p className="eyebrow">FEISHU OAUTH</p>
          <h2>登录未完成</h2>
          <p role="alert" className="error">{phase.message}</p>
          <Link className="button secondary" href="/login">返回登录</Link>
        </>}
      </section>
    </div>
  </main>;
}
