"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { z } from "zod";
import { reportDocumentSchema, type ReportDocument, type ScoreValue } from "@aii/core";
import { api, ClientApiError } from "@/lib/client-api";
import { Shell } from "./shell";
import { ReportRadar } from "./report-radar";
import { GraduateReviewPanel, qualificationLabels } from "./graduate-review-panel";
import { ReportProctorRisks } from "./report-proctor-risks";

const recommendations = { strong_yes: "strong_yes · 建议重点推进", yes: "yes · 建议推进", mixed: "mixed · 待补充或人工复核", no: "no · 当前证据暂不支持推进" };
const scoreText = (value: ScoreValue) => value === "insufficient_evidence" ? "证据不足" : `${value}/5`;
export function ReportPanel({ id }: { id: string }) {
  const [report, setReport] = useState<ReportDocument>(), [loading, setLoading] = useState(true), [unauthorized, setUnauthorized] = useState(false);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [selected, setSelected] = useState("");
  const [newValue, setNewValue] = useState<ScoreValue>("3"), [reason, setReason] = useState(""), [evidenceId, setEvidenceId] = useState("");
  const [reviewNote, setReviewNote] = useState(""), [message, setMessage] = useState("");
  const editInput = useRef<HTMLSelectElement>(null), pending = useRef<{ fingerprint: string; key: string } | null>(null);
  const load = useCallback(async () => {
    try { setReport(await api(`/api/interviews/${id}/report`, reportDocumentSchema)); setUnauthorized(false); setError(""); }
    catch (error) { setUnauthorized(error instanceof ClientApiError && error.code === "UNAUTHORIZED"); setError(error instanceof Error ? error.message : "报告加载失败"); }
    finally { setLoading(false); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (selected) editInput.current?.focus(); }, [selected]);
  async function write(path: string, method: string, body: unknown, success: string) {
    setBusy(true); setError(""); setMessage("");
    const fingerprint = `${path}:${JSON.stringify(body)}`;
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, key: crypto.randomUUID() };
    try {
      setReport(await api(path, reportDocumentSchema, { method, body, key: pending.current.key }));
      pending.current = null; setSelected(""); setReason(""); setMessage(success);
    } catch (error) { setError(error instanceof Error ? error.message : "操作未成功，可以重试"); }
    finally { setBusy(false); }
  }
  function edit(scoreId: string) {
    const row = report?.dimensions.find((dimension) => dimension.scoreId === scoreId); if (!row) return;
    setNewValue(row.score); setEvidenceId(row.evidenceIds[0] ?? ""); setReason(""); setSelected(scoreId);
  }
  const selectedDimension = report?.dimensions.find((row) => row.scoreId === selected);
  const citations = report?.evidence.filter((row) => row.competencyId === selectedDimension?.competencyId) ?? [];
  async function print() {
    if (!report) return;
    setBusy(true); setError("");
    try { await api(`/api/interviews/${id}/print`, z.object({ ok: z.boolean() }), { method: "POST", body: { expectedRevision: report.revision }, key: crypto.randomUUID() }); window.print(); }
    catch (error) { setError(error instanceof Error ? error.message : "导出未完成"); }
    finally { setBusy(false); }
  }
  return <Shell section="面试报告"><main className="report-workspace">
    <div className="report-actions no-print"><Link href="/" className="text-button">← 返回工作台</Link><div className="button-row">
      <button className="button secondary" disabled={busy || loading} onClick={() => void load()}>刷新报告</button>
      {report && <button className="button primary" disabled={busy} onClick={() => void print()}>打印 / 另存为 PDF</button>}
    </div></div>
    {error && <p className="error-banner no-print" role="alert">{error}</p>}
    {message && <p className="notice no-print" role="status">{message}</p>}
    {loading ? <section className="panel report-empty" role="status">正在加载面试报告…</section> : !report ? <section className="panel report-empty no-print">
      <p className="eyebrow">EVIDENCE BEFORE JUDGMENT</p><h1>{unauthorized ? "请先登录招聘工作台" : "准备生成证据报告"}</h1>
      <p>面试完成后，使用全部转录进行两次独立评分。引用需通过原文校验，缺证据时保留为证据不足。</p>
      {unauthorized ? <Link href="/" className="button primary">前往登录</Link> : <button className="button primary" disabled={busy} onClick={() => void write(`/api/interviews/${id}/score`, "POST", {}, "报告已生成，等待人工复核。")}>{busy ? "正在校验证据与生成报告…" : "生成证据报告"}</button>}
    </section> : <>
      <article className="report-document" aria-label="面试评分报告">
        <section className="report-sheet" data-testid="report-sheet">
          <header className="report-heading"><div><p className="eyebrow">见微 / EVIDENCE REPORT</p><h1>结构化面试报告</h1><p>{report.jobTitle}</p></div><div className="report-identity"><strong>{report.candidateLabel}</strong><span>{report.status === "reviewed" ? "已人工复核" : "等待人工复核"} · v{report.revision}</span><span>{report.metadata.generatedAt.slice(0, 10)}</span></div></header>
          {(report.fixture || report.metadata.provider === "fake") && <p className="report-demo">确定性演示报告 · 使用虚构资料与规则样例评分，不代表真实模型评估。</p>}
          <section className="report-overview"><div><p className="eyebrow">OVERALL ASSESSMENT</p><div className="report-number">{report.overallScore?.toFixed(2) ?? "—"}<span>/ 5</span></div><p>证据覆盖权重 {Math.round(report.coverage * 100)}%</p><p className="report-summary">{report.overallSummary}</p></div><ReportRadar dimensions={report.dimensions} /></section>
          <section className="report-dimensions"><h2>胜任力维度</h2><table><thead><tr><th>维度 / 权重</th><th>评分</th><th>校验与原文依据</th><th className="no-print">复核</th></tr></thead><tbody>
            {report.dimensions.map((row, index) => <tr key={row.competencyId}><td><strong><span className="report-print-only">维度 {index + 1} · </span>{row.competencyName}</strong><span className="report-weight">{Math.round(row.weight * 100)}%</span></td><td className="report-value">{scoreText(row.score)}</td><td>{row.needsReview ? <span className="review-flag">需人工复核</span> : row.score === "insufficient_evidence" ? "无有效引用" : `${row.evidenceIds.length}条原文引用`}<details className="no-print"><summary>查看评分说明</summary><p>{row.rationale}</p><p>原始采样：{row.sampleValues.map(scoreText).join(" / ") || "历史样例"}</p></details></td><td className="no-print"><button className="text-button" disabled={busy} onClick={() => edit(row.scoreId)} aria-label={`复核${row.competencyName}`}>改分</button></td></tr>)}
          </tbody></table></section>
          <section className="report-findings"><div><h2>亮点</h2>{report.highlights.length ? <ul>{report.highlights.map((text) => <li key={text}>{text}</li>)}</ul> : <p>暂无足够证据支持明确亮点。</p>}</div><div><h2>待验证风险</h2>{report.risks.length ? <ul>{report.risks.map((text) => <li key={text}>{text}</li>)}</ul> : <p>未发现规则标记项；不代表不存在其他风险。</p>}</div></section>
          <section className="report-recommendation"><h2>{recommendations[report.recommendation]}</h2><p>{report.recommendationReason}</p>{report.campus && <p className="report-qualification">岗位硬指标：{qualificationLabels[report.campus.status]} · CET-4 {report.campus.verification?.cet4Score ?? "待核验"}（要求≥425） · 曾挂科 {report.campus.verification?.failedGraduateCourses ?? "待核验"}门（要求0） · 必问触达 {report.campus.mandatoryAsked}/{report.campus.mandatoryTotal}</p>}<strong>仅供人类招聘者复核，AI 不自动录用或淘汰。</strong></section>
          <footer className="report-footer">面试 {report.interviewId} · 联系方式默认隐去<span>1 / 2</span></footer>
        </section>
        <section className="report-sheet" data-testid="report-sheet">
          <header className="report-evidence-heading"><h2>原文证据与下一轮验证</h2><span>{report.candidateLabel} · v{report.revision}</span></header>
          <ReportProctorRisks items={report.riskItems} />
          <div className="report-evidence-grid">{report.dimensions.map((dimension, index) => {
            const evidence = report.evidence.filter((row) => dimension.evidenceIds.includes(row.id)), first = evidence[0];
            return <section className="report-evidence-card" key={dimension.competencyId}><h3><span className="no-print">{dimension.competencyName}</span><span className="report-print-only">维度 {index + 1}</span> · {scoreText(dimension.score)}</h3>{first ? <><blockquote>“{first.quote}”</blockquote><p className="report-citation">turn_id: {first.turnId} · #{first.turnSeq}</p>{evidence.length > 1 && <details className="no-print"><summary>查看其余{evidence.length - 1}条证据</summary>{evidence.slice(1).map((row) => <div key={row.id}><blockquote>“{row.quote}”</blockquote><p className="report-citation">turn_id: {row.turnId} · 第{row.turnSeq}轮</p></div>)}</details>}</> : <p>insufficient_evidence · 无可验证原文，不编造引用。</p>}</section>;
          })}</div>
          <section className="report-question-scores"><h2>逐题评分 <span>原始 AI 结果；人工改分作用于维度分</span></h2>{report.questions.length ? <table><thead><tr><th>题号</th><th>维度</th><th>分数</th><th>原文轮次</th></tr></thead><tbody>{report.questions.map((row) => <tr key={row.questionId}><td>{row.seq}</td><td><span className="no-print">{report.dimensions.find((dimension) => dimension.competencyId === row.competencyId)?.competencyName}</span><span className="report-print-only">维度 {report.dimensions.findIndex((dimension) => dimension.competencyId === row.competencyId) + 1}</span></td><td>{scoreText(row.score)}{row.needsReview ? " · 需复核" : ""}</td><td>{[...new Set(report.evidence.filter((evidence) => row.evidenceIds.includes(evidence.id)).map((evidence) => evidence.turnSeq))].map((seq) => `#${seq}`).join("、") || "—"}</td></tr>)}</tbody></table> : <p>历史种子报告未保存逐题结果，仅作样例。</p>}</section>
          <section className="report-next"><h2>建议下一轮追问</h2><ol>{report.nextQuestions.map((text) => <li key={text}>{text}</li>)}</ol></section>
          <section className="report-metadata"><h2>生成与复核记录</h2><p>{report.metadata.provider} / {report.metadata.model} · {report.metadata.samplingRuns}次采样 · 转录已去标识化</p><p>Token：输入 {report.metadata.promptTokens} / 输出 {report.metadata.completionTokens} / 合计 {report.metadata.totalTokens} · 估算成本 ${report.metadata.estimatedCostUsd.toFixed(6)}</p><p>{report.metadata.costBasis === "unpriced_internal" ? "未配置内网模型单价；0美元不代表实际免费。" : (report.metadata.costBasis === "fixture_free" || report.metadata.provider === "fake") ? "fake为免费确定性演示；token为字符近似估算。" : "按配置单价估算；token可能含近似值，以网关账单为准。"} 人工改分 {report.revisions.length}次。</p></section>
          <footer className="report-footer">本地摄像头与设备状态不参与评分 · 原文证据展示已脱敏<span>2 / 2</span></footer>
        </section>
      </article>
      {report.campus && <GraduateReviewPanel key={report.campus.verification?.reviewedAt ?? "unverified"} report={report} onUpdated={setReport} />}
      {selectedDimension && <section className="panel report-editor no-print" aria-labelledby="score-editor-title"><h2 id="score-editor-title">人工复核 · {selectedDimension.competencyName}</h2><p>当前值：{scoreText(selectedDimension.score)}。填写理由后保存；原始逐题 AI 评分保持可追溯。</p><form onSubmit={(event) => { event.preventDefault(); void write(`/api/scores/${selected}`, "PATCH", { value: newValue, reason, expectedRevision: report.revision, ...(evidenceId ? { evidenceId } : {}) }, "改分已保存，原值、新值、操作者、时间和理由均已留痕。"); }}>
        <label>新的维度分<select ref={editInput} value={newValue} onChange={(event) => setNewValue(event.target.value as ScoreValue)}>{["1", "2", "3", "4", "5", "insufficient_evidence"].map((value) => <option key={value} value={value}>{scoreText(value as ScoreValue)}</option>)}</select></label>
        {newValue !== "insufficient_evidence" && <label>原文证据<select value={evidenceId} onChange={(event) => setEvidenceId(event.target.value)} required><option value="">请选择同一维度证据</option>{citations.map((row) => <option key={row.id} value={row.id}>第{row.turnSeq}轮：{row.quote.slice(0, 60)}</option>)}</select></label>}
        <label>改分理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength={4} maxLength={600} required rows={3} /></label><p className="small muted">操作者由服务端登录身份记录；当前为共享工作空间账号。</p><div className="button-row"><button className="button primary" disabled={busy}>{busy ? "保存中…" : "保存改分并留痕"}</button><button className="button secondary" type="button" onClick={() => setSelected("")}>取消改分</button></div>
      </form></section>}
      <section className="panel report-editor no-print"><h2>人工复核记录</h2>{report.revisions.length ? <ol className="revision-history">{report.revisions.map((row) => <li key={row.id}><strong>{row.actorName ?? row.actorId}</strong> · {new Date(row.at).toLocaleString("zh-CN")} · {scoreText(row.oldValue)} → {scoreText(row.newValue)}<p>{row.reason}</p></li>)}</ol> : <p>尚无人工改分记录。</p>}
        {report.status !== "reviewed" && <form onSubmit={(event) => { event.preventDefault(); void write(`/api/interviews/${id}/review`, "POST", { expectedRevision: report.revision, note: reviewNote }, "报告已标记人工复核完成；录用决定仍由招聘者作出。"); }}><label>复核说明<textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} minLength={4} maxLength={600} required rows={2} /></label><p className="small muted">{report.campus && (report.campus.status === "pending" || report.campus.mandatoryAsked < report.campus.mandatoryTotal) ? "硬指标待核验或必问未全部触达，暂不能标记完整复核。请核验证明或另行人工补面。" : "请确认已核对能力证据与岗位标准；复核不执行录用或淘汰。"}</p><button className="button primary" disabled={busy || Boolean(report.campus && (report.campus.status === "pending" || report.campus.mandatoryAsked < report.campus.mandatoryTotal))}>确认人工复核完成</button></form>}
        {report.status === "report_ready" && !report.revisions.length && !report.campus?.verification && <div className="report-rerun"><p>尚未进行人工改分，可重新运行两次采样；已有人工改分或已复核的报告不能被模型覆盖。</p><button className="button secondary" disabled={busy} onClick={() => void write(`/api/interviews/${id}/score`, "POST", { rerun: true }, "报告已重新生成。")}>重新运行评分</button></div>}
      </section>
    </>}
  </main></Shell>;
}
