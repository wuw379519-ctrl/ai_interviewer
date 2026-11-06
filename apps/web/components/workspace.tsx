"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { z } from "zod";
import { api } from "@/lib/client-api";
import { Shell } from "./shell";

const dashboardSchema = z.object({ policy: z.object({ retentionDays: z.number() }).optional(), jobs: z.array(z.object({ id: z.string(), title: z.string(), status: z.string() })),
  interviews: z.array(z.object({ id: z.string(), title: z.string(), candidateName: z.string(), status: z.string(), durationMinutes: z.number() })) });
const statusLabels: Record<string, string> = { invited: "待候选人进入", consented: "已知情同意", interviewing: "面试进行中", wrapping_up: "收尾中", scoring: "待生成报告", report_ready: "报告已生成", reviewed: "已复核", created: "已创建", cancelled: "已撤回" };

export function Workspace({ demo }: { demo: boolean }) {
  const [data, setData] = useState<z.infer<typeof dashboardSchema>>();
  const [login, setLogin] = useState(false), [accessCode, setAccessCode] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const load = () => api("/api/jobs", dashboardSchema).then((result) => { setData(result); setLogin(false); }).catch(() => setLogin(true));
  useEffect(() => { void load(); }, []);
  async function enter() {
    setBusy(true); setError("");
    try { await api("/api/auth/login", z.object({ ok: z.boolean() }), { method: "POST", body: { accessCode } }); await load(); }
    catch (error) { setError(error instanceof Error ? error.message : "登录失败"); } finally { setBusy(false); }
  }
  return <Shell><main className="workspace"><header className="formal-hero workspace-hero"><p className="eyebrow">RECRUITING WORKSPACE</p><h1>招聘面试工作台</h1><p>用固定题和岗位经历展开一场正式面试，让后续评价有原话可查。</p><div className="button-row"><Link className="button primary" href="/recruiter/formal">发起正式面试 →</Link><Link className="button secondary" href="/recruiter/new">创建面试 · 经典向导</Link></div></header>
    {demo && <div className="notice"><span className="notice-icon">◈</span><div><strong>演示工作空间</strong><p>无需 API Key。当前使用确定性样例生成，请使用虚构资料；完成面试后可生成证据评分报告，由人类复核。</p></div><span className="pill">FIXTURE</span></div>}
    {login ? <section className="panel login-panel"><p className="eyebrow">欢迎使用见微</p><h2>{demo ? "进入演示，体验完整文本面试" : "登录招聘工作台"}</h2><p className="muted">岗位标准由你确认，候选人通过独立邀请链接参与面试。</p><form onSubmit={(event) => { event.preventDefault(); void enter(); }}>{!demo && <label>招聘者访问码<input type="password" autoComplete="current-password" value={accessCode} onChange={(event) => setAccessCode(event.target.value)} required /></label>}<button className="button primary" disabled={busy}>{busy ? "正在进入…" : demo ? "进入演示工作台 →" : "登录"}</button></form>{error && <p role="alert" className="error">{error}</p>}</section> : <>
      <div className="metric-grid"><div className="metric"><span>岗位标准</span><strong>{data?.jobs.length ?? "—"}<small>个岗位</small></strong><p>先确认胜任力，再发起面试</p></div><div className="metric"><span>面试记录</span><strong>{data?.interviews.length ?? "—"}<small>场面试</small></strong><p>进度保存至服务端</p></div><div className="metric"><span>新资料保留期</span><strong>{data?.policy?.retentionDays ?? 90}<small>天</small></strong><p>明确用途，候选人可撤回</p></div></div>
      <section className="panel"><div className="section-heading"><div><h2>最近的面试</h2><p className="muted">统一核心问题，用同一把尺子衡量。</p></div><span className="small muted">最多显示最近 20 场</span></div><div className="table-wrap"><table><thead><tr><th>候选人</th><th>应聘岗位</th><th>时长</th><th>当前进度</th><th>报告</th></tr></thead><tbody>{data?.interviews.map((row) => <tr key={row.id}><td><span className="avatar">{row.candidateName.slice(0, 1)}</span>{row.candidateName}</td><td>{row.title}</td><td>{row.durationMinutes} 分钟</td><td><span className={`status ${row.status === "interviewing" ? "live" : ""}`}>{statusLabels[row.status] ?? row.status}</span></td><td>{["scoring", "report_ready", "reviewed"].includes(row.status) ? <Link className="text-button" href={`/recruiter/interviews/${row.id}/report`}>{row.status === "scoring" ? "生成报告" : "查看报告"} →</Link> : <span className="small muted">面试完成后生成</span>}</td></tr>)}</tbody></table>{data?.interviews.length === 0 && <div className="empty-state">还没有面试。创建第一场，建立共同的评估标准。</div>}</div></section>
      <div className="principles"><div><span>01</span><h3>标准先行</h3><p>确认维度、权重与行为锚点后生效。</p></div><div><span>02</span><h3>尊重候选人</h3><p>知情同意、随时暂停，恢复时回到同一题。</p></div><div><span>03</span><h3>证据支持判断</h3><p>评分引用原话，最终决策交由人类。</p></div></div>
    </>}<footer className="workspace-footer">见微 Interview <span>让能力被看见，让判断可追溯。</span></footer></main></Shell>;
}
