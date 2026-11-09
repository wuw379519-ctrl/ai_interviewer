"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { z } from "zod";
import { createdInterviewSchema } from "@aii/core";
import { api } from "@/lib/client-api";
import { Shell } from "./shell";
import { needsLogin, WorkspaceLogin } from "./workspace-login";

type Invitation = { url: string; count: number; expires: string };

export function FormalInterviewSetup({ demo }: { demo: boolean }) {
  const [authorized, setAuthorized] = useState<boolean>();
  const [invitation, setInvitation] = useState<Invitation>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const inviteInput = useRef<HTMLInputElement>(null);
  const verifySession = useCallback(async () => {
    await api("/api/jobs", z.object({}));
    setAuthorized(true);
  }, []);

  useEffect(() => {
    void verifySession().catch((error: unknown) => {
      if (needsLogin(error)) setAuthorized(false);
      else setError(error instanceof Error ? error.message : "无法连接工作台，请刷新重试");
    });
  }, [verifySession]);

  async function create(form: HTMLFormElement) {
    setError("");
    const data = new FormData(form);
    const value = (field: string) => String(data.get(field) ?? "").trim();
    const body = {
      title: value("title"), candidateName: value("candidateName"), jdText: value("jdText"),
      resumeText: value("resumeText"), durationMinutes: Number(value("durationMinutes")),
    };
    const fingerprint = JSON.stringify(body);
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const result = await api("/api/formal-interviews", createdInterviewSchema, { method: "POST", body, key: retry.current.key });
      setInvitation({ url: `${window.location.origin}/i/${result.interviewId}#token=${result.inviteToken}`,
        count: result.questionCount, expires: result.inviteExpiresAt });
      retry.current = null;
      form.reset();
    } catch (error) {
      setError(needsLogin(error) ? "招聘者会话已过期。请在新标签页登录工作台，再返回重试。"
        : error instanceof Error ? error.message : "创建失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!invitation) return;
    try {
      await navigator.clipboard.writeText(invitation.url);
      setCopied(true);
    } catch {
      inviteInput.current?.focus();
      inviteInput.current?.select();
    }
  }

  return <Shell section="正式面试">
    <main className="workspace formal-workspace">
      <header className="formal-hero">
        <p className="eyebrow">INTERVIEW STUDIO</p>
        <h1>创建正式面试</h1>
        <p>使用统一的研究生校招题单，再结合岗位要求和候选人的经历提问。</p>
        <div className="formal-tags"><span>文字问答</span><span>专属邀请</span><span>证据评价</span></div>
      </header>
      {error && <p role="alert" className="error-banner">{error}</p>}
      {authorized === undefined && !error && <p role="status">正在核对招聘者会话…</p>}
      {authorized === false && <WorkspaceLogin demo={demo} onReady={verifySession} />}
      {authorized && (invitation ? <section className="panel formal-login" aria-live="polite">
        <p className="eyebrow">INVITATION READY</p>
        <h2>邀请已就绪</h2>
        <p className="muted">共 {invitation.count} 道题。请私下发送给候选人，链接有效至 {new Date(invitation.expires).toLocaleString("zh-CN")}。</p>
        <label>候选人邀请链接<input ref={inviteInput} readOnly value={invitation.url} /></label>
        <div className="button-row">
          <button className="button primary" onClick={() => void copy()}>{copied ? "已复制" : "复制邀请链接"}</button>
          <a className="button secondary" href={invitation.url} target="_blank" rel="noreferrer">打开候选人页 ↗</a>
          <button className="text-button" onClick={() => { setInvitation(undefined); setCopied(false); }}>再创建一场</button>
        </div>
      </section> : <div className="formal-grid">
        <form className="panel formal-form" onSubmit={(event) => { event.preventDefault(); void create(event.currentTarget); }}>
          <fieldset disabled={busy}>
            <legend><span className="formal-index">01</span> 场次信息</legend>
            <div className="formal-fields">
              <label>岗位名称<input name="title" minLength={2} maxLength={120} placeholder="例如 数据平台工程师" required /></label>
              <label>候选人姓名<input name="candidateName" maxLength={80} placeholder="姓名或内部候选人代号" required /></label>
            </div>
            <label>面试时长<select name="durationMinutes" defaultValue="15"><option value="15">15 分钟</option><option value="30">30 分钟</option><option value="45">45 分钟</option></select></label>
          </fieldset>
          <fieldset disabled={busy}>
            <legend><span className="formal-index">02</span> 岗位与经历</legend>
            <label>岗位 JD<textarea name="jdText" rows={4} minLength={30} maxLength={20000} placeholder="粘贴岗位职责、任职要求和关键交付内容（至少 30 字）" required /></label>
            <label>候选人简历<textarea name="resumeText" rows={4} minLength={20} maxLength={30000} placeholder="粘贴相关项目、技能和个人经历（至少 20 字）" required /></label>
          </fieldset>
          <div className="formal-form-actions"><button className="button primary" disabled={busy}>{busy ? "正在创建…" : "生成候选人邀请 →"}</button></div>
        </form>
        <aside className="panel formal-guide">
          <p className="eyebrow">面试流程</p>
          <ol>
            <li><strong>系统使用固定题单</strong><p>包含自我介绍、项目经验、求职动机、期望收入、职业规划、自我评价和岗位工作安排。</p></li>
            <li><strong>核验两项硬性资格</strong><p>英语四级达到 425 分，研究生期间曾挂科门数为 0。这两题须作答，资格以人工核验为准。</p></li>
            <li><strong>结合岗位和经历</strong><p>随后补充岗位理解、简历实践和经验迁移三题。</p></li>
            <li><strong>查看评价</strong><p>候选人提交后，可在管理员记录里生成评价并核对原文证据。</p></li>
          </ol>
          <Link className="text-button" href="/recruiter/new">打开经典结构化向导 →</Link>
        </aside>
      </div>)}
    </main>
  </Shell>;
}
