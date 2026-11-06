"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { z } from "zod";
import { interviewStatusSchema, reportDocumentSchema, type ReportDocument } from "@aii/core";
import { api, ClientApiError } from "@/lib/client-api";
import { Shell } from "./shell";
import { needsLogin, WorkspaceLogin } from "./workspace-login";

const base = "/api/admin/interviews";
const recordSchema = z.object({
  id: z.string().uuid(), jobTitle: z.string(), candidateName: z.string(), status: interviewStatusSchema,
  mode: z.enum(["text", "voice"]), createdAt: z.string().datetime(), startedAt: z.string().datetime().nullable(),
  finishedAt: z.string().datetime().nullable(), retainedUntil: z.string().datetime(),
});
const listSchema = z.object({ items: z.array(recordSchema), nextCursor: z.string().uuid().nullable() });
const detailSchema = z.object({
  interview: recordSchema,
  turns: z.array(z.object({ seq: z.number().int(), role: z.string(), content: z.string() })),
  report: reportDocumentSchema.nullable(),
});
const labels: Record<z.infer<typeof interviewStatusSchema>, string> = {
  created: "已创建", invited: "待进入", consented: "已同意", warmup: "准备中", interviewing: "进行中",
  wrapping_up: "收尾中", scoring: "待评价", report_ready: "已评价", reviewed: "已复核", cancelled: "已撤回",
};
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
const scoreLabel = (score: string) => score === "insufficient_evidence" ? "证据不足" : `${score} / 5`;

function Evaluation({ report }: { report: ReportDocument }) {
  return <section className="panel record-section">
    <div className="section-heading">
      <div><p className="eyebrow">ASSESSMENT</p><h2>面试评价</h2></div>
      <span className="pill">{report.fixture ? "演示评价" : `第 ${report.revision} 版`}</span>
    </div>
    <div className="evaluation-head">
      <div><span>综合分</span><strong>{report.overallScore === null ? "证据不足" : `${report.overallScore} / 5`}</strong></div>
      <div><span>证据覆盖</span><strong>{Math.round(report.coverage * 100)}%</strong></div>
    </div>
    <p>{report.overallSummary}</p>
    <div className="evaluation-grid">
      {report.dimensions.map((dimension) => <article key={dimension.competencyId}>
        <div><h3>{dimension.competencyName}</h3><span className="pill">{scoreLabel(dimension.score)}</span></div>
        <p className="small muted">{dimension.rationale}</p>
        {report.evidence.filter((evidence) => dimension.evidenceIds.includes(evidence.id)).map((evidence) =>
          <blockquote key={evidence.id}>{evidence.quote}<footer>候选人原话 · 第 {evidence.turnSeq} 条记录</footer></blockquote>)}
      </article>)}
    </div>
    <details className="record-breakdown"><summary>查看逐题评价（{report.questions.length} 题）</summary>
      <ol>{report.questions.map((question) => <li key={question.questionId}><strong>第 {question.seq} 题 · {scoreLabel(question.score)}</strong>
        <span>{question.rationale}{question.needsReview ? " · 建议复核" : ""}</span></li>)}</ol>
    </details>
    <p className="small muted">{report.recommendationReason}</p>
  </section>;
}

export function InterviewRecords({ demo, id }: { demo: boolean; id?: string }) {
  const [authorized, setAuthorized] = useState<boolean>();
  const [records, setRecords] = useState<z.infer<typeof listSchema>>();
  const [detail, setDetail] = useState<z.infer<typeof detailSchema>>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const scoreKey = useRef<string | undefined>(undefined);
  const path = id ? `${base}/${encodeURIComponent(id)}` : base;

  const load = useCallback(async (signal?: AbortSignal) => {
    if (id) setDetail(await api(path, detailSchema, { signal }));
    else setRecords(await api(path, listSchema, { signal }));
    setAuthorized(true);
  }, [id, path]);

  const handle = useCallback((error: unknown) => {
    if (needsLogin(error)) {
      setAuthorized(false);
      setRecords(undefined);
      setDetail(undefined);
    } else {
      if (error instanceof ClientApiError && error.code === "INTERVIEW_NOT_FOUND") setDetail(undefined);
      setError(error instanceof Error ? error.message : "请求失败，请刷新重试");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).catch((error: unknown) => { if (!controller.signal.aborted) handle(error); });
    return () => controller.abort();
  }, [load, handle]);

  async function run(operation: () => Promise<void>) {
    setError("");
    setBusy(true);
    try { await operation(); }
    catch (error) { handle(error); }
    finally { setBusy(false); }
  }

  async function more() {
    if (!records?.nextCursor) return;
    const next = await api(`${base}?before=${records.nextCursor}`, listSchema);
    setRecords({ ...next, items: [...records.items, ...next.items] });
  }

  async function generate() {
    scoreKey.current ??= crypto.randomUUID();
    await api(`${path}/score`, reportDocumentSchema, { method: "POST", body: {}, key: scoreKey.current });
    await load();
    scoreKey.current = undefined;
  }

  async function logout() {
    await api("/api/admin/logout", z.object({ ok: z.boolean() }), { method: "POST", body: {} });
    setRecords(undefined);
    setDetail(undefined);
    setAuthorized(false);
  }

  return <Shell section="面试记录">
    <main className="workspace formal-workspace">
      <header className="formal-hero">
        <p className="eyebrow">INTERVIEW RECORDS</p>
        <h1>{id ? "面试详情" : "面试记录"}</h1>
        <p>{id ? "查看场次进度、候选人回答与面试评价。" : "查阅保留期内的全部场次，从发出邀请到完成评价。"}</p>
        <div className="formal-tags">
          {id ? <Link href="/admin/interviews">← 返回面试记录</Link> : <Link href="/admin">数据治理 →</Link>}
          {authorized && <button type="button" disabled={busy} onClick={() => void run(logout)}>退出管理员</button>}
        </div>
      </header>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {authorized === undefined && !error && <p role="status">正在加载面试记录…</p>}
      {authorized === false && <WorkspaceLogin admin demo={demo} onReady={async () => { setError(""); await load(); }} />}
      {authorized && records && <section className="panel record-section">
        <div className="section-heading">
          <div><h2>全部场次</h2><p className="muted">按创建时间倒序，包含尚未开始和进行中的面试。</p></div>
          <button className="button secondary" disabled={busy} onClick={() => void run(() => load())}>刷新列表</button>
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>候选人</th><th>岗位</th><th>进度</th><th>创建时间</th><th>详情</th></tr></thead>
          <tbody>{records.items.map((record) => <tr key={record.id}>
            <td><strong>{record.candidateName}</strong></td><td>{record.jobTitle}</td>
            <td><span className={`status ${record.status === "interviewing" ? "live" : ""}`}>{labels[record.status]}</span></td>
            <td>{formatDate(record.createdAt)}</td>
            <td><Link className="text-button" href={`/admin/interviews/${record.id}`} aria-label={`查看记录 · ${record.candidateName}`}>查看记录 →</Link></td>
          </tr>)}</tbody>
        </table></div>
        {!records.items.length && <p className="empty-state">保留期内暂无面试记录。</p>}
        {records.nextCursor && <button className="button secondary" disabled={busy} onClick={() => void run(more)}>加载更早的面试</button>}
      </section>}
      {authorized && detail && <>
        <section className="panel record-section">
          <div className="section-heading">
            <div><h2>{detail.interview.candidateName} · {detail.interview.jobTitle}</h2>
              <span className="status">{labels[detail.interview.status]}</span> <span className="small muted">{detail.interview.mode === "text" ? "文字面试" : "语音面试"}</span></div>
            <button className="button secondary" disabled={busy} onClick={() => void run(() => load())}>刷新详情</button>
          </div>
          <dl className="record-meta">
            <div><dt>创建</dt><dd>{formatDate(detail.interview.createdAt)}</dd></div>
            <div><dt>开始</dt><dd>{formatDate(detail.interview.startedAt)}</dd></div>
            <div><dt>结束</dt><dd>{formatDate(detail.interview.finishedAt)}</dd></div>
            <div><dt>保留至</dt><dd>{formatDate(detail.interview.retainedUntil)}</dd></div>
          </dl>
        </section>
        {detail.report ? <Evaluation report={detail.report} /> : <section className="panel record-section">
          <h2>面试评价</h2>
          {detail.interview.status === "scoring" ? <>
            <p className="muted">面试已结束。生成评价后可核对各维度得分和对应原话。</p>
            <button className="button primary" disabled={busy} onClick={() => void run(generate)}>{busy ? "处理中…" : "生成面试评价"}</button>
          </> : <p className="muted">{detail.interview.status === "cancelled" ? "候选人已撤回同意。" : "面试结束后可生成评价。"}</p>}
        </section>}
        <section className="panel record-section">
          <h2>面试对话</h2>
          {detail.turns.length ? <ol className="record-transcript">{detail.turns.map((turn) => <li key={turn.seq} data-role={turn.role}>
            <span>{turn.role === "candidate" ? "候选人" : turn.role === "interviewer" ? "AI 面试官" : "系统"} · {turn.seq}</span>
            <p>{turn.content}</p>
          </li>)}</ol> : <p className="muted">{detail.interview.status === "cancelled" ? "撤回后对话不可查阅。" : "暂无可查看的对话。"}</p>}
        </section>
      </>}
    </main>
  </Shell>;
}
