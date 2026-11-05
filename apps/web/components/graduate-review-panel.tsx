"use client";
import { useRef, useState } from "react";
import { graduateVerificationInputSchema, reportDocumentSchema, type ReportDocument } from "@aii/core";
import { api } from "@/lib/client-api";

export const qualificationLabels = { met: "已核验满足", not_met: "已核验不满足", pending: "待人工核验" };
export function GraduateReviewPanel({ report, onUpdated }: { report: ReportDocument; onUpdated: (report: ReportDocument) => void }) {
  const saved = report.campus?.verification;
  const [score, setScore] = useState(saved?.cet4Score?.toString() ?? ""), [failed, setFailed] = useState(saved?.failedGraduateCourses?.toString() ?? "");
  const [cetReference, setCetReference] = useState(saved?.cet4Reference ?? ""), [transcriptReference, setTranscriptReference] = useState(saved?.transcriptReference ?? ""), [note, setNote] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [message, setMessage] = useState("");
  const pending = useRef<{ fingerprint: string; key: string } | null>(null);
  const campus = report.campus;
  if (!campus) return null;
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      const body = graduateVerificationInputSchema.parse({ expectedRevision: report.revision, cet4Score: score === "" ? null : Number(score),
        failedGraduateCourses: failed === "" ? null : Number(failed), cet4Reference: cetReference, transcriptReference, note });
      const fingerprint = JSON.stringify(body);
      if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, key: crypto.randomUUID() };
      const updated = await api(`/api/interviews/${report.interviewId}/eligibility`, reportDocumentSchema, { method: "PATCH", body, key: pending.current.key });
      onUpdated(updated); pending.current = null; setNote(""); setMessage("核验已保存，原值、新值、核验人、时间与说明已留痕。");
    } catch (error) { setError(error instanceof Error ? error.message : "核验未保存，请刷新报告后重试"); }
    finally { setBusy(false); }
  }
  return <section className="panel report-editor no-print" aria-labelledby="graduate-review-title"><h2 id="graduate-review-title">研究生校招 · 岗位硬指标核验</h2>
    <p data-testid="qualification-status"><strong>{qualificationLabels[campus.status]}</strong> · CET-4 ≥425分；研究生期间无曾经不及格记录，补考或重修后通过仍计入。</p>
    <p>面试中的自述不视为核验完成。请由招聘者查看成绩报告与完整研究生成绩单后录入；无证明时保留空白，不能把“未知”填成0。不要求证件号、考试账号或密码。</p>
    <details><summary>固定必问触达 {campus.mandatoryAsked}/{campus.mandatoryTotal} · 已回答 {campus.mandatoryAnswered}</summary><ol>{campus.topics.map((topic) => <li key={topic.key}>{topic.label} · {topic.skipped ? "候选人跳过" : topic.answered ? "已回答" : topic.asked ? "已提问，未回答" : "未触达"}{topic.responses.map((response) => <blockquote key={response.turnId}><p>{response.quote}</p><span className="small muted">turn_id: {response.turnId} · 候选人原话（脱敏）</span></blockquote>)}</li>)}</ol></details>
    {saved && <p className="small muted">最近核验：{saved.reviewerName} · {new Date(saved.reviewedAt).toLocaleString("zh-CN")} · {saved.note}</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}{message && <p className="notice" role="status">{message}</p>}
    <form onSubmit={(event) => { event.preventDefault(); void save(); }}><div className="two-column">
      <label>CET-4核验分数（未知留空）<input type="number" min={0} max={710} step={1} value={score} onChange={(event) => setScore(event.target.value)} /></label>
      <label>研究生期间曾挂科门数（未知留空）<input type="number" min={0} max={200} step={1} value={failed} onChange={(event) => setFailed(event.target.value)} /></label>
      <label>四级成绩报告核验来源<input maxLength={200} minLength={score === "" ? undefined : 3} required={score !== ""} value={cetReference} onChange={(event) => setCetReference(event.target.value)} placeholder="例如：已查看候选人出示的成绩报告" /></label>
      <label>完整研究生成绩单核验来源<input maxLength={200} minLength={failed === "" ? undefined : 3} required={failed !== ""} value={transcriptReference} onChange={(event) => setTranscriptReference(event.target.value)} placeholder="例如：已查看含补考重修记录的完整成绩单" /></label>
    </div><label>核验说明<textarea minLength={4} maxLength={600} rows={2} required value={note} onChange={(event) => setNote(event.target.value)} /></label><p className="small muted">仅记录核验来源说明，不上传证书或成绩单。操作者与时间由服务端记录。薪资偏好、个人工作安排不计能力分。</p><button className="button primary" disabled={busy}>{busy ? "保存核验中…" : "保存资格核验并留痕"}</button></form>
  </section>;
}
