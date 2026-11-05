"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { z } from "zod";
import { confirmCompetenciesSchema, competencySetSchema, createdInterviewSchema, resumeProfileSchema, unverifiedClaimSchema, GRADUATE_TOPICS, type RecruitmentTrack, type CompetencyDraft } from "@aii/core";
import { api } from "@/lib/client-api";
import { Shell } from "./shell";
import { InterviewMediaOptions } from "./interview-media-options";

const idSchema = z.object({ id: z.string().uuid() });
const resumeSchema = z.object({ id: z.string(), parsed: resumeProfileSchema, unverifiedClaims: z.array(unverifiedClaimSchema) });
const DEMO_JD = "研究生校招研发工程师：参与企业产品研发与实验验证，使用 TypeScript、Python、SQL 分析问题并实现可维护的模块。欢迎科研、课程、竞赛与实习项目经历，能解释个人贡献、方法选择与量化结果，愿意与团队协作并主动学习。本岗位要求CET-4总分至少425分、研究生期间无挂科记录，成绩由招聘者人工核验。";
const DEMO_RESUME = "技能：TypeScript、Python、SQL\n研究经历：2024—2026，研究生阶段参与实验室数据分析项目。\n项目：主导实验数据平台优化，我负责指标分析、数据处理和核心模块实现，将处理时间从4.2秒降低到1.6秒，交付效率提升30%。\n项目：与同学协商将重复实验脚本改为配置化实现，按期完成，三个月返工为0。";

function GraduatePreview({ dimensions }: { dimensions: CompetencyDraft[] }) {
  return <div className="notice"><h3>研究生校招 · 固定必问与硬指标</h3><p>CET-4 ≥425分；研究生期间没有曾经不及格记录（补考、重修后通过仍计入）。候选人口述待招聘者核验证明，能力高分不能抵消硬指标。</p><ol>{GRADUATE_TOPICS.map((topic) => <li key={topic.key}>{topic.sourceNumber ? `原表${topic.sourceNumber} · ` : "新增 · "}{topic.label}{topic.mode === "scored" ? ` → ${dimensions[topic.dimension]?.name ?? "待确认维度"}` : " · 不计能力分"}</li>)}</ol><p className="small">原表“家庭情况”改为自愿说明工作安排，不询问亲属、婚育或家庭收入。必问表示面试官必须触达，候选人仍可跳过。每个能力维度另补齐至2道评分题。</p></div>;
}

export function InterviewWizard() {
  const [step, setStep] = useState(1), [title, setTitle] = useState(""), [jdText, setJd] = useState("");
  const [jobId, setJobId] = useState(""), [candidateId, setCandidateId] = useState(""), [dimensions, setDimensions] = useState<CompetencyDraft[]>([]);
  const [name, setName] = useState(""), [email, setEmail] = useState(""), [resumeText, setResumeText] = useState("");
  const [file, setFile] = useState<File>(), [parsed, setParsed] = useState<z.infer<typeof resumeSchema>>();
  const [duration, setDuration] = useState(15), [created, setCreated] = useState<z.infer<typeof createdInterviewSchema>>(), [inviteUrl, setInviteUrl] = useState("");
  const [mode, setMode] = useState<"text" | "voice">("voice"), [cameraRequired, setCameraRequired] = useState(true);
  const [recruitmentTrack, setRecruitmentTrack] = useState<RecruitmentTrack>("graduate_campus");
  const [busy, setBusy] = useState(""), [error, setError] = useState(""), [copied, setCopied] = useState(false), [fixture, setFixture] = useState(false);
  const keys = useRef(new Map<string, string>());
  function key(operation: string) { if (!keys.current.has(operation)) keys.current.set(operation, crypto.randomUUID()); return keys.current.get(operation)!; }
  async function task(label: string, work: () => Promise<void>) {
    setError(""); setBusy(label);
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "操作未成功，请重试"); } finally { setBusy(""); }
  }
  function demo() { setTitle("研究生校招研发工程师"); setJd(DEMO_JD); setName("演示候选人 A"); setResumeText(DEMO_RESUME); }
  async function extract() {
    await task("正在抽取岗位标准…", async () => {
      const job = jobId ? { id: jobId } : await api("/api/jobs", idSchema, { method: "POST", body: { title, jdText, recruitmentTrack }, key: key("job") });
      setJobId(job.id);
      const result = await api(`/api/jobs/${job.id}/competencies:extract`, competencySetSchema.and(z.object({ fixture: z.boolean() })), { method: "POST", body: {}, key: key("extract") });
      setDimensions(result.competencies); setFixture(result.fixture);
    });
  }
  function editDimension(index: number, patch: Partial<CompetencyDraft>) { setDimensions((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item)); }
  async function confirm() {
    await task("正在确认岗位标准…", async () => {
      const body = confirmCompetenciesSchema.parse({ competencies: dimensions });
      await api(`/api/jobs/${jobId}/competencies`, z.object({ status: z.literal("confirmed") }), { method: "PATCH", body, key: key("confirm") });
      setStep(2);
    });
  }
  async function parse() {
    await task("正在解析并脱敏…", async () => {
      const candidate = candidateId ? { id: candidateId } : await api("/api/candidates", idSchema, {
        method: "POST", body: { jobId, fullName: name, ...(email ? { email } : {}) }, key: key("candidate"),
      });
      setCandidateId(candidate.id);
      const form = new FormData(); if (file) form.append("file", file);
      const result = await api(`/api/candidates/${candidate.id}/resume`, resumeSchema, {
        method: "POST", body: file ? form : { text: resumeText }, key: key("resume"),
      });
      setParsed(result); setStep(3);
    });
  }
  async function create() {
    await task("正在生成面试计划…", async () => {
      const result = await api("/api/interviews", createdInterviewSchema, { method: "POST", body: { jobId, candidateId, durationMinutes: duration, mode, cameraRequired }, key: key("interview") });
      setCreated(result); setInviteUrl(`${window.location.origin}/i/${result.interviewId}#token=${result.inviteToken}`);
    });
  }
  return <Shell section="创建面试"><main className="workspace wizard-workspace"><Link className="back-link" href="/">← 返回工作台</Link><div className="page-intro"><div><p className="eyebrow">NEW INTERVIEW</p><h1>为一次好面试，做好准备。</h1><p className="muted">三个步骤，把岗位要求转化为一致的面试标准。</p></div>{!jobId && <button className="button secondary" onClick={demo}>载入演示资料</button>}</div>
    <ol className="wizard-steps" aria-label="创建进度">{["岗位与评估标准", "候选人与简历", "面试配置与邀请"].map((label, index) => <li key={label} aria-current={step === index + 1 ? "step" : undefined} className={step >= index + 1 ? "current" : ""}><span>{step > index + 1 ? "✓" : index + 1}</span>{label}</li>)}</ol>
    {error && <div className="error-banner" role="alert">{error}<span> 如提示未登录，请先<Link href="/">进入工作台</Link>。</span></div>}
    {created ? <section className="panel success-panel"><span className="success-symbol" aria-hidden="true">✓</span><p className="eyebrow">INVITATION READY</p><h2>准备就绪，把舞台交给候选人。</h2><p className="muted">{title} · {duration} 分钟 · {created.questionCount} 道核心题 · {dimensions.length} 个维度</p><label>专属邀请链接<input readOnly value={inviteUrl} onFocus={(event) => event.target.select()} /></label><div className="button-row"><button className="button secondary" onClick={() => { void navigator.clipboard.writeText(inviteUrl).then(() => setCopied(true)).catch(() => setError("无法访问剪贴板，请选择链接后复制")); }}>{copied ? "已复制" : "复制邀请链接"}</button><a className="button primary" href={inviteUrl} target="_blank" rel="noreferrer">以候选人身份体验 ↗</a></div><p className="small muted">链接有效期 7 天，持有完整链接即可进入本场面试。请仅发送给对应候选人。</p></section> : <>
    {step === 1 && <section className="panel form-panel"><div className="section-heading"><div><h2>从岗位真正需要的能力开始</h2><p className="muted">AI 提出草稿，你确认后才生效。岗位已有面试后，评估标准将冻结。</p></div><span className="step-label">01 / 03</span></div><form onSubmit={(event) => { event.preventDefault(); void (dimensions.length ? confirm() : extract()); }}>
      <label>招聘场景<select value={recruitmentTrack} disabled={Boolean(jobId)} onChange={(event) => setRecruitmentTrack(event.target.value as RecruitmentTrack)}><option value="graduate_campus">研究生校招 · 固定必问与资格核验</option><option value="general">通用岗位面试</option></select></label>
      <label>岗位名称<input required minLength={2} maxLength={120} value={title} disabled={Boolean(jobId)} onChange={(event) => setTitle(event.target.value)} placeholder="例如：研究生校招研发工程师" /></label>
      <label>岗位描述 JD<textarea required minLength={30} maxLength={20000} rows={7} value={jdText} disabled={Boolean(jobId)} onChange={(event) => setJd(event.target.value)} placeholder="粘贴岗位职责、工作场景与能力要求…" /></label>
      {dimensions.length > 0 && <div className="dimension-editor"><div className="section-heading"><h3>确认胜任力与行为锚点</h3><span className={Math.abs(dimensions.reduce((sum, item) => sum + item.weight, 0) - 1) < 0.00001 ? "pill" : "error"}>权重合计 {(dimensions.reduce((sum, item) => sum + item.weight, 0) * 100).toFixed(0)}%</span></div>{fixture && <p className="small muted">演示模式提供通用维度草稿，请结合 JD 编辑。真实模型接入后按岗位抽取。</p>}
        {dimensions.map((dimension, index) => <details className="dimension-card" key={index} open={index === 0}><summary><span className="dimension-number">0{index + 1}</span><strong>{dimension.name}</strong><span>{Math.round(dimension.weight * 100)}%</span></summary><div className="dimension-body"><div className="two-column"><label>维度名称<input value={dimension.name} onChange={(event) => editDimension(index, { name: event.target.value })} required /></label><label>权重（%）<input type="number" min={1} max={100} step={0.01} value={Number((dimension.weight * 100).toFixed(2))} onChange={(event) => editDimension(index, { weight: Number(event.target.value) / 100 })} required /></label></div><label>维度定义<textarea rows={2} value={dimension.description} onChange={(event) => editDimension(index, { description: event.target.value })} required /></label><p className="small muted">五级行为锚点 BARS · 描述可观察的行为</p>{dimension.bars.map((bar, barIndex) => <label className="anchor-row" key={bar.level}><span>L{bar.level}</span><input aria-label={`${dimension.name} L${bar.level} 行为锚点`} value={bar.anchor} onChange={(event) => editDimension(index, { bars: dimension.bars.map((item, itemIndex) => itemIndex === barIndex ? { ...item, anchor: event.target.value } : item) })} required /></label>)}</div></details>)}
      </div>}{recruitmentTrack === "graduate_campus" && <GraduatePreview dimensions={dimensions} />}<div className="form-actions"><p className="small muted">不以受保护属性作为评估维度。</p><button className="button primary" disabled={Boolean(busy)}>{busy || (dimensions.length ? "确认标准，下一步 →" : "抽取胜任力 →")}</button></div></form></section>}
    {step === 2 && <section className="panel form-panel"><div className="section-heading"><div><h2>了解经历，不预设判断</h2><p className="muted">联系方式仅用于招聘联络，不进入评估。简历中的无关属性会被剔除。</p></div><span className="step-label">02 / 03</span></div><form onSubmit={(event) => { event.preventDefault(); void parse(); }}><div className="two-column"><label>候选人姓名<input required value={name} onChange={(event) => setName(event.target.value)} disabled={Boolean(candidateId)} /></label><label>邮箱 <span className="muted">选填</span><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} disabled={Boolean(candidateId)} /></label></div><label>上传简历 <span className="muted">PDF / DOCX，≤2MB，文字版</span><input type="file" accept=".pdf,.docx" onChange={(event) => setFile(event.target.files?.[0])} /></label><div className="separator"><span>或粘贴简历文本</span></div><label>简历文本<textarea rows={8} minLength={20} maxLength={30000} required={!file} disabled={Boolean(file)} value={resumeText} onChange={(event) => setResumeText(event.target.value)} placeholder="工作经历、技能、项目与成果…" /></label><div className="form-actions"><span className="small muted">只保留与岗位能力有关的信息。</span><button className="button primary" disabled={Boolean(busy)}>{busy || "解析简历，下一步 →"}</button></div></form></section>}
    {step === 3 && <div className="config-grid"><section className="panel form-panel"><div className="section-heading"><div><h2>给对话留出合适的空间</h2><p className="muted">同岗位、同档位使用同一套核心题。</p></div><span className="step-label">03 / 03</span></div><InterviewMediaOptions mode={mode} cameraRequired={cameraRequired} onModeChange={(value) => { setMode(value); keys.current.delete("interview"); }} onCameraChange={(value) => { setCameraRequired(value); keys.current.delete("interview"); }} /><fieldset><legend>面试时长</legend><div className="duration-grid">{[15, 30, 45].map((minutes) => <label className={`duration-option ${duration === minutes ? "selected" : ""}`} key={minutes}><input type="radio" name="duration" value={minutes} checked={duration === minutes} onChange={() => { setDuration(minutes); keys.current.delete("interview"); }} /><strong>{minutes}<small>分钟</small></strong><span>{minutes === 15 ? "聚焦核心经历" : minutes === 30 ? "充分展开行为" : "深入讨论取舍"}</span></label>)}</div></fieldset>{recruitmentTrack === "graduate_campus" && <GraduatePreview dimensions={dimensions} />}<div className="config-summary"><div><span>面试方式</span><strong>{mode === "voice" ? "语音问答 · 转写核对" : "文本对话 · 流式输出"}</strong></div><div><span>评估标准</span><strong>{dimensions.length} 个维度，每维度 2–3 题</strong></div><div><span>追问策略</span><strong>仅补缺项，最多两层</strong></div><div><span>数据保留期</span><strong>90 天</strong></div></div><p className="small muted">候选人需先完成知情同意，可暂停、撤回。面试结束后可生成证据报告并进行人工核验、改分和复核。</p><button className="button primary full-width" disabled={Boolean(busy)} onClick={() => void create()}>{busy || "生成计划并创建邀请 →"}</button></section><aside className="panel resume-preview"><p className="eyebrow">RESUME CHECKPOINTS</p><h2>待验证声明</h2><p className="small muted">以下为简历原文，尚未被验证。用于后续追问，不改变核心题与权重。</p><ol className="claim-list">{parsed?.unverifiedClaims.map((claim) => <li key={claim.id}>{claim.text}<span>来自{claim.sourceSection}</span></li>)}</ol>{parsed?.unverifiedClaims.length === 0 && <p className="muted">未发现明确声明，面试将以岗位核心题为准。</p>}<div className="skill-tags">{parsed?.parsed.skills.map((skill) => <span key={skill}>{skill}</span>)}</div></aside></div>}
    </>}</main></Shell>;
}
