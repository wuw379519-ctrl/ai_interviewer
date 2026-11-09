"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import Link from "next/link";
import { auditPageSchema, cleanupPreviewSchema, cleanupResultSchema, erasurePreviewSchema, erasureResultSchema, governanceCandidatesSchema, retentionPolicySchema } from "@aii/core";
import { api, ClientApiError } from "@/lib/client-api";
import { Shell } from "./shell";
import { OperationsPanel } from "./operations-panel";
import { WorkspaceLogin } from "./workspace-login";

const workspaceSchema = z.object({ policy: retentionPolicySchema, preview: cleanupPreviewSchema });
export function GovernancePanel({ demo }: { demo: boolean }) {
  const [workspace, setWorkspace] = useState<z.infer<typeof workspaceSchema>>(), [people, setPeople] = useState<z.infer<typeof governanceCandidatesSchema>>(), [logs, setLogs] = useState<z.infer<typeof auditPageSchema>>();
  const [authorized, setAuthorized] = useState(false), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const [days, setDays] = useState(90), [policyReason, setPolicyReason] = useState(""), [cleanupReason, setCleanupReason] = useState(""), [confirmed, setConfirmed] = useState(false);
  const [lookup, setLookup] = useState("");
  const [action, setAction] = useState(""), [selected, setSelected] = useState<z.infer<typeof erasurePreviewSchema>>(), [confirmation, setConfirmation] = useState(""), [eraseReason, setEraseReason] = useState("");
  const confirmationInput = useRef<HTMLInputElement>(null), pending = useRef(new Map<string, { body: string; key: string }>());
  const keyFor = (path: string, body: unknown) => { const fingerprint = JSON.stringify(body), old = pending.current.get(path); if (old?.body === fingerprint) return old.key; const key = crypto.randomUUID(); pending.current.set(path, { body: fingerprint, key }); return key; };
  const load = useCallback(async () => {
    const [next, candidates, audit] = await Promise.all([api("/api/admin/retention", workspaceSchema), api("/api/admin/candidates", governanceCandidatesSchema), api("/api/admin/audit", auditPageSchema)]);
    setWorkspace(next); setDays(next.policy.retentionDays); setPeople(candidates); setLogs(audit); setAuthorized(true); setConfirmed(false); setAction("");
  }, []);
  useEffect(() => { void load().catch((error: unknown) => { if (!(error instanceof ClientApiError && ["UNAUTHORIZED", "FORBIDDEN"].includes(error.code))) setError(error instanceof Error ? error.message : "加载失败"); }).finally(() => setLoading(false)); }, [load]);
  useEffect(() => { if (selected) confirmationInput.current?.focus(); }, [selected]);
  async function work(fn: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await fn(); } catch (error) { setError(error instanceof Error ? error.message : "操作失败，可以重试"); }
    finally { setBusy(false); }
  }
  async function savePolicy() {
    if (!workspace) return;
    await work(async () => {
      const body = { retentionDays: days, expectedRevision: workspace.policy.revision, reason: policyReason };
      await api("/api/admin/retention", retentionPolicySchema, { method: "PATCH", body, key: keyFor("policy", body) }); pending.current.delete("policy"); setPolicyReason(""); await load(); setMessage("保留期已更新，仅用于新资料和新面试；已有期限与同意记录保持原值。");
    });
  }
  async function erase() {
    if (!selected || confirmation !== selected.candidateId) return;
    await work(async () => {
      const path = `/api/candidates/${selected.candidateId}`, body = { confirmCandidateId: confirmation, reason: eraseReason };
      const result = await api(path, erasureResultSchema, { method: "DELETE", body, key: keyFor(path, body) }); pending.current.delete(path); setSelected(undefined); setConfirmation(""); setEraseReason(""); await load(); setMessage(`资料已清除，删除了${result.interviewsErased}场面试的关联内容；匿名软删除标记与最小审计记录保留。`);
    });
  }
  async function cleanup() {
    if (!workspace || !confirmed) return;
    await work(async () => {
      const body = { previewToken: workspace.preview.previewToken, reason: cleanupReason };
      const result = await api("/api/admin/retention/run", cleanupResultSchema, { method: "POST", body, key: keyFor("cleanup", body) }); pending.current.delete("cleanup"); setCleanupReason(""); await load(); setMessage(`本批清理完成：候选人${result.candidatesErased}，面试${result.interviewsErased}，过期缓存${result.cachesRemoved}，审计最小化${result.auditEntriesMinimized}。`);
    });
  }
  async function loadAudit(more = false) {
    await work(async () => { const query = new URLSearchParams(); if (action) query.set("action", action); if (more && logs?.nextCursor) query.set("before", logs.nextCursor);
      const page = await api(`/api/admin/audit?${query}`, auditPageSchema); setLogs((old) => more && old ? { ...page, items: [...old.items, ...page.items] } : page); });
  }
  return <Shell section="数据治理"><main className="workspace governance-workspace"><div className="page-intro"><div><p className="eyebrow">DATA GOVERNANCE</p><h1>让数据有期限，让操作可追溯。</h1><p className="muted">管理员独立登录。删除清除业务内容，操作审计保留最小记录。</p><Link href="/admin/interviews" className="text-button">查看全部面试记录 →</Link></div>{authorized && <button className="button secondary" disabled={busy} onClick={() => void work(async () => { await api("/api/admin/logout", z.object({ ok: z.boolean() }), { method: "POST", body: {} }); setAuthorized(false); setWorkspace(undefined); setPeople(undefined); setLogs(undefined); setSelected(undefined); setEraseReason(""); setPolicyReason(""); setCleanupReason(""); })}>退出管理员</button>}</div>
    {error && <p role="alert" className="error-banner">{error}</p>}{message && <p role="status" className="notice">{message}</p>}
    {loading ? <p role="status">正在核对管理员权限…</p> : !authorized ? <WorkspaceLogin admin demo={demo} onReady={load} /> : workspace && <>
      <OperationsPanel />
      <section className="panel form-panel"><div className="section-heading"><div><h2>保留期策略</h2><p>默认90天，可缩短至1–90天。只应用于新资料；新面试不会延长候选人原有资料期限。同意说明展示本场期限。</p></div><span className="pill">v{workspace.policy.revision}</span></div><form onSubmit={(event) => { event.preventDefault(); void savePolicy(); }}><label>新资料保留天数<input type="number" min={1} max={90} step={1} required value={days} onChange={(event) => setDays(Number(event.target.value))} /></label><label>策略修改理由<textarea minLength={4} maxLength={300} rows={2} required value={policyReason} onChange={(event) => setPolicyReason(event.target.value)} /></label><button className="button primary" disabled={busy}>保存保留期策略</button></form></section>
      <section className="panel form-panel"><div className="section-heading"><div><h2>到期清理预览</h2><p>本次截止：{new Date(workspace.preview.cutoffAt).toLocaleString("zh-CN")}。每批最多25名候选人、25场独立到期面试、200个缓存及100条审计上下文。</p></div><button className="button secondary" disabled={busy} onClick={() => void work(load)}>重新预览</button></div>
        <p data-testid="cleanup-counts">候选人 {workspace.preview.counts.candidates} · 面试 {workspace.preview.counts.interviews} · 过期缓存 {workspace.preview.counts.caches} · 审计最小化 {workspace.preview.counts.auditEntries}</p>
        <details><summary>查看本批资料编号</summary><p>候选人：{workspace.preview.candidateIds.join("、") || "无"}</p><p>独立到期面试：{workspace.preview.interviewIds.join("、") || "无"}</p></details>
        <p className="small muted">预览凭证5分钟有效；执行时只处理本次预览，资料或策略变化会要求重新预览。过期内容会先拒绝访问，物理清理由此处或部署定时任务执行。{workspace.preview.hasMore ? "还有后续批次，请完成本批后重新预览。" : "本预览已覆盖当前批次。"}</p>
        <form onSubmit={(event) => { event.preventDefault(); void cleanup(); }}><label>清理说明<textarea required minLength={4} maxLength={300} rows={2} value={cleanupReason} onChange={(event) => setCleanupReason(event.target.value)} /></label><label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我已核对本批编号，确认永久清除到期内容</label><button className="button primary" disabled={busy || !confirmed}>执行本批到期清理</button></form>
      </section>
      <section className="panel form-panel"><h2>候选人删除请求</h2><p>默认只显示匿名编号。先预览关联范围，再输入完整编号确认；不会删除其他候选人的资料。</p><form onSubmit={(event) => { event.preventDefault(); void work(async () => { setSelected(await api(`/api/candidates/${lookup}`, erasurePreviewSchema)); setConfirmation(""); setEraseReason(""); }); }}><label>按完整候选人编号预览<input required value={lookup} onChange={(event) => setLookup(event.target.value.trim())} /></label><button className="button secondary" disabled={busy}>查询删除范围</button></form><div className="table-wrap"><table><thead><tr><th>匿名编号</th><th>岗位</th><th>最晚保留至</th><th>操作</th></tr></thead><tbody>{people?.items.map((row) => <tr key={row.id}><td><strong>{row.label}</strong><div className="small muted">{row.id}</div></td><td>{row.jobTitle}</td><td>{new Date(row.retainedUntil).toLocaleDateString("zh-CN")}</td><td>{row.deleted ? "已清除" : <button className="text-button" disabled={busy} onClick={() => void work(async () => { setSelected(await api(`/api/candidates/${row.id}`, erasurePreviewSchema)); setConfirmation(""); setEraseReason(""); })} aria-label={`预览删除${row.id}`}>预览删除范围</button>}</td></tr>)}</tbody></table></div>{people?.nextCursor && <button className="button secondary" disabled={busy} onClick={() => void work(async () => { const page = await api(`/api/admin/candidates?before=${people.nextCursor}`, governanceCandidatesSchema); setPeople({ ...page, items: [...people.items, ...page.items] }); })}>更多候选人</button>}
        {selected?.deleted && <p className="notice">该候选人的资料此前已清除。</p>}{selected && !selected.deleted && <div className="notice"><form onSubmit={(event) => { event.preventDefault(); void erase(); }}><h3>确认清除 · {selected.label}</h3><p>预览时关联：面试{selected.counts.interviews}、简历{selected.counts.resumes}、转录{selected.counts.turns}、报告{selected.counts.reports}、评分{selected.counts.scores}、响应缓存{selected.counts.caches}。执行时处理该候选人的全部关联资料，无法恢复。已下载副本与组织备份须按组织流程另行处理。</p><label>输入完整候选人编号<input ref={confirmationInput} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" /></label><label>删除理由<textarea minLength={4} maxLength={300} rows={2} required value={eraseReason} onChange={(event) => setEraseReason(event.target.value)} /></label><p className="small muted">说明不应包含姓名、联系方式或回答原文。历史自由文本上下文会清除；本次处理说明不留存原文，仅保存原因类别与不可逆摘要，以及操作人、时间和必要数值改分轨迹。</p><div className="button-row"><button className="button primary" disabled={busy || confirmation !== selected.candidateId}>永久清除候选人资料</button><button className="button secondary" type="button" disabled={busy} onClick={() => setSelected(undefined)}>取消删除</button></div></form></div>}
      </section>
      <section className="panel form-panel"><div className="section-heading"><div><h2>操作审计</h2><p>联系方式已脱敏；已删除或超过90天的自由文本上下文不再展示。</p></div></div><form onSubmit={(event) => { event.preventDefault(); void loadAudit(); }}><label>操作筛选<select value={action} onChange={(event) => setAction(event.target.value)}><option value="">全部操作</option>{["candidate.erased", "retention.executed", "retention.policy_updated", "score.revised", "graduate.verified", "report.viewed", "interview.record_viewed", "consent.recorded", "audit.viewed"].map((value) => <option key={value}>{value}</option>)}</select></label><button className="button secondary" disabled={busy}>筛选审计</button></form><div className="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>实体与上下文</th></tr></thead><tbody>{logs?.items.map((row) => <tr key={row.id}><td>{new Date(row.at).toLocaleString("zh-CN")}</td><td>{row.actorType} / {row.actorId}</td><td>{row.action}</td><td><span className="small muted">{row.entityId}</span><details><summary>查看脱敏上下文</summary><pre>{JSON.stringify(row.metadata, null, 2)}</pre></details></td></tr>)}</tbody></table></div>{logs?.nextCursor && <button className="button secondary" disabled={busy} onClick={() => void loadAudit(true)}>更早的审计记录</button>}</section>
    </>}
  </main></Shell>;
}
