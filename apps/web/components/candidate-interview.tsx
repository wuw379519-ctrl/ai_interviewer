"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { interviewStateSchema, type InterviewView, type MediaReport } from "@aii/core";
import { api, streamTurn, ClientApiError, type TurnSubmission } from "@/lib/client-api";
import { Brand } from "./shell";
import { createLocalRecognition } from "@/lib/browser-speech";
import { useInterviewDevices, deviceStatus } from "./use-interview-devices";
import { useInterviewSpeech } from "./use-interview-speech";
import { InterviewMediaPanel } from "./interview-media-panel";
import { VideoInterviewRoom } from "./video-interview-room";
import { usePlaybackInterruption } from "./use-playback-interruption";
import { useProctorSignals } from "@/lib/proctor/use-proctor-signals";

const okSchema = z.object({ interviewId: z.string(), status: z.string() });
export function CandidateInterview({ id }: { id: string }) {
  const [token, setToken] = useState(""), [view, setView] = useState<InterviewView>(), [accepted, setAccepted] = useState(false);
  const [draft, setDraft] = useState(""), [stream, setStream] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [online, setOnline] = useState(true), [remaining, setRemaining] = useState(0), [confirm, setConfirm] = useState<"finish" | "withdraw" | null>(null), [withdrawn, setWithdrawn] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const posting = useRef(false), pending = useRef<{ key: string; body: TurnSubmission } | null>(null);
  const withdrawnRef = useRef(false), modalRef = useRef<HTMLElement>(null);
  const devices = useInterviewDevices();
  const speech = useInterviewSpeech({ id, token, stream: devices.stream, server: view?.speechServerEnabled ?? false,
    edge: view?.ttsServerEnabled ?? false, questionSeq: view?.questionSeq, turnSeq: view?.turns.filter((turn) => turn.role === "interviewer").at(-1)?.seq, draft, setDraft });
  const interruption = usePlaybackInterruption(devices.stream, speech.speaking, speech.stopPlayback);
  const mediaSyncing = useRef(false), lastSpoken = useRef("");
  const proctorActive = Boolean(
    token && view && ["interviewing", "wrapping_up"].includes(view.status) && !view.pausedAt && !withdrawn,
  );
  useProctorSignals({
    interviewId: id,
    token,
    active: proctorActive,
    questionSeq: view?.questionSeq,
    stream: devices.stream,
  });
  const needsMedia = Boolean(view && (view.cameraRequired || (view.mode === "voice" && !view.textFallback)));
  const mediaReady = !view || ((!view.cameraRequired || devices.status.cameraActive) && (view.mode !== "voice" || view.textFallback || devices.status.microphoneActive));
  const formalCampus = view?.formalText && view.recruitmentTrack === "graduate_campus";
  const requiredQualification = formalCampus && view.currentQuestion?.assessmentMode === "eligibility";
  const timeUp = formalCampus && remaining <= 0 && !requiredQualification;
  const inputBlocked = busy || uncertain || !online || !mediaReady || speech.listening || speech.transcribing || speech.preparing;
  const refresh = useCallback(async (credential: string) => {
    try {
    const state = await api(`/api/interviews/${id}/state`, interviewStateSchema, { token: credential, signal: AbortSignal.timeout(8000) });
    setView(state); setRemaining(state.remainingSec); setOnline(true);
    return state;
    } catch (error) {
      if (error instanceof ClientApiError && ["UNAUTHORIZED", "CANDIDATE_DELETED"].includes(error.code)) {
        speech.cancel(); devices.release(); setDraft(""); pending.current = null; setView(undefined);
        setError("本场面试已失效、撤回、删除或到期，已停止设备采集。请联系招聘者。"); sessionStorage.removeItem(`aii-invite:${id}`);
      }
      throw error;
    }
  }, [id, speech.cancel, devices.release]);
  useEffect(() => {
    const credential = new URLSearchParams(window.location.hash.slice(1)).get("token") || sessionStorage.getItem(`aii-invite:${id}`) || "";
    if (!credential) { setError("链接缺少邀请凭证。请使用招聘者发送的完整专属链接。"); return; }
    sessionStorage.setItem(`aii-invite:${id}`, credential);
    history.replaceState(null, "", window.location.pathname);
    setToken(credential);
    void refresh(credential).catch((error: unknown) => setError(error instanceof Error ? error.message : "无法连接"));
    const onOffline = () => { setOnline(false); speech.cancel(); devices.release(); };
    const onOnline = () => { if (!posting.current) void refresh(credential).catch(() => setOnline(false)); };
    window.addEventListener("offline", onOffline); window.addEventListener("online", onOnline);
    const interval = window.setInterval(() => { if (!posting.current && !withdrawnRef.current) void refresh(credential).catch(() => setOnline(false)); }, 5000);
    return () => { clearInterval(interval); window.removeEventListener("offline", onOffline); window.removeEventListener("online", onOnline); };
  }, [id, refresh, speech.cancel, devices.release]);
  useEffect(() => {
    if (!view || view.pausedAt || !["interviewing", "wrapping_up"].includes(view.status)) return;
    const interval = window.setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => clearInterval(interval);
  }, [view?.status, view?.pausedAt, view]);
  useEffect(() => {
    if (!confirm) return;
    const previous = document.activeElement;
    const buttons = modalRef.current?.querySelectorAll<HTMLButtonElement>("button");
    buttons?.[0]?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirm(null);
      if (event.key !== "Tab" || !buttons?.length) return;
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", handle);
    return () => { window.removeEventListener("keydown", handle); if (previous instanceof HTMLElement) previous.focus(); };
  }, [confirm]);
  useEffect(() => {
    if (!view || !needsMedia || withdrawn || !["consented", "warmup", "interviewing", "wrapping_up"].includes(view.status)) return;
    const report = async (reason: "heartbeat" | "device_lost") => {
      if (posting.current || mediaSyncing.current || !navigator.onLine) return;
      mediaSyncing.current = true;
      try {
        const status = deviceStatus(devices.stream);
        if (reason === "device_lost") speech.cancel();
        const result = await api(`/api/interviews/${id}/media`, z.object({ pausedAt: z.string().nullable() }), {
          method: "POST", token, body: { ...status, reason },
        });
        if (result.pausedAt && !view.pausedAt) await refresh(token);
      } catch { setOnline(false); } finally { mediaSyncing.current = false; }
    };
    if (!mediaReady && !busy) void report("device_lost");
    const timer = setInterval(() => { void report("heartbeat"); }, 5000);
    return () => clearInterval(timer);
  }, [id, token, view?.status, view?.pausedAt, needsMedia, mediaReady, devices.stream, devices.status.cameraActive, devices.status.microphoneActive, busy, withdrawn, refresh, speech.cancel]);
  useEffect(() => {
    if (!view || view.mode !== "voice" || !["interviewing", "wrapping_up"].includes(view.status) || view.pausedAt || !mediaReady || !speech.hasVoice) return;
    const text = view.currentQuestion?.text, key = `${view.turns.at(-1)?.seq}:${text}`;
    if (text && lastSpoken.current !== key) { lastSpoken.current = key; speech.speak(text); }
  }, [view?.status, view?.pausedAt, view?.currentQuestion?.text, view?.turns.at(-1)?.seq, mediaReady, speech.hasVoice, speech.speak, view?.mode]);
  useEffect(() => {
    if (withdrawn || (view && !["invited", "consented", "warmup", "interviewing", "wrapping_up"].includes(view.status))) { speech.cancel(); devices.release(); }
    else if (view?.pausedAt) { speech.cancel(); devices.release(); }
  }, [withdrawn, view?.status, view?.pausedAt, speech.cancel, devices.release]);

  async function mutation(operation: string, body: unknown = {}) {
    return api(`/api/interviews/${id}/${operation}`, okSchema, { method: "POST", token, body, key: crypto.randomUUID() });
  }
  async function run(work: () => Promise<void>) {
    setBusy(true); posting.current = true; setError("");
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : "连接中断，请重试"); }
    finally { setBusy(false); posting.current = false; }
  }
  async function start() {
    await run(async () => {
      if (view?.status === "invited") await mutation("consent", { accepted: true, consentVersion: view.consentVersion });
      if (view && (view.mode === "voice" || view.cameraRequired)) {
        await checkDevices(view.textFallback);
        if (view.mode === "voice" && !view.textFallback && !view.speechServerEnabled) await createLocalRecognition();
      }
      await mutation("start"); await refresh(token);
    });
    await refresh(token).catch(() => undefined);
  }
  async function sendMedia(report: MediaReport) {
    await api(`/api/interviews/${id}/media`, okSchema, { method: "POST", token, body: report });
  }
  async function checkDevices(textFallback = view?.textFallback ?? false) {
    if (!view) return;
    const status = await devices.acquire(view.cameraRequired, view.mode === "voice" && !textFallback);
    await sendMedia({ ...status, reason: "check", textFallback }); await refresh(token);
  }
  async function pauseAndRelease() {
    speech.cancel(); devices.release();
    await run(async () => {
      if (view && ["interviewing", "wrapping_up"].includes(view.status)) await mutation("pause", { paused: true });
      if (view && (view.mode === "voice" || view.cameraRequired) && !["created", "invited"].includes(view.status)) await sendMedia({ cameraActive: false, microphoneActive: false, reason: "paused" });
      await refresh(token);
    });
  }
  async function resume() {
    await run(async () => {
      if (!mediaReady) await checkDevices();
      await mutation("pause", { paused: false }); await refresh(token);
    });
  }
  async function fallback() { speech.cancel(); await run(() => checkDevices(true)); }
  async function submit(action: "answer" | "repeat" | "skip") {
    if (!mediaReady) { setError("请先重新检测本场要求的设备，再继续回答。"); return; }
    speech.cancel();
    await run(async () => {
      pending.current ??= { key: crypto.randomUUID(), body: { action, ...(action === "answer" ? { content: draft } : {}),
        ...(view?.formalText ? { expectedQuestionSeq: view.questionSeq } : {}) } };
      try {
        setStream("");
        const result = await streamTurn(id, token, pending.current.key, pending.current.body, setStream);
        if (pending.current.body.action === "answer") setDraft("");
        pending.current = null; setUncertain(false);
        if (result.kind === "complete" && result.status !== "scoring") await mutation("finish");
        await refresh(token); setStream("");
        if (action === "repeat" && view?.mode === "voice") speech.speak(result.text);
      } catch (error) {
        if (view?.formalText && error instanceof ClientApiError && ["RESOURCE_CONFLICT", "INTERVIEW_CLOSED"].includes(error.code)) {
          pending.current = null;
          setUncertain(false);
          await refresh(token);
        } else setUncertain(true);
        throw error;
      }
    });
  }
  async function close(kind: "finish" | "withdraw") {
    speech.cancel(); devices.release();
    await run(async () => {
      await mutation(kind); setConfirm(null);
      if (kind === "withdraw") { withdrawnRef.current = true; setWithdrawn(true); sessionStorage.removeItem(`aii-invite:${id}`); }
      else await refresh(token);
    });
  }
  const active = view && ["interviewing", "wrapping_up"].includes(view.status);
  const completed = view && ["scoring", "report_ready", "reviewed"].includes(view.status);
  return <div className={view?.formalText ? "candidate-app formal-candidate" : "candidate-app"}><header className="candidate-header"><Brand /><span className="small muted">专属面试空间 · {view?.mode === "voice" ? "语音问答" : "文本对话"}</span></header><main className="candidate-main">
    <div className="candidate-heading"><p className="eyebrow">{view?.formalText ? "FORMAL INTERVIEW · TEXT" : "A CONVERSATION ABOUT YOUR WORK"}</p><h1>{view?.jobTitle ?? "准备，让经历被听见。"}</h1><p className="muted">不必追求完美答案，分享具体经历与真实思考就好。</p></div>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {!view && !error && <div className="panel candidate-card" role="status">正在连接你的面试…</div>}
    {withdrawn ? <section className="panel candidate-card"><h2>已撤回同意</h2><p>面试已停止，邀请凭证已失效，不会继续采集回答。如需删除已有数据，请联系邀请你的招聘者。</p></section> : view && <>
      {!online && <div className="offline-banner" role="status">连接暂时中断。当前题目保持不变，正在尝试恢复连接；未提交的文字仅保留在当前页面。</div>}
      {["created", "invited", "consented", "warmup"].includes(view.status) && <section className="panel candidate-card"><div className="consent-heading"><span className="notice-icon">◇</span><div><h2>开始前，请了解这次面试</h2><p className="small muted">预计 {view.durationMinutes} 分钟 · {view.totalQuestions} 道核心题 · 可随时暂停</p></div></div><div className="consent-facts"><div><strong>AI 面试官</strong><span>最终结果由人类复核</span></div><div><strong>{view.mode === "voice" ? "语音转写后确认" : "文字作答"}</strong><span>{view.cameraRequired ? "摄像头仅本地预览" : "本场不要求摄像头"}</span></div><div><strong>最多保留 {view.retentionDays} 天</strong><span>可撤回和申请删除</span></div></div><p className="consent-copy">{view.consentText}</p>{view.mode === "voice" && <p className="small muted">本场转写方式：{view.speechServerEnabled ? `${view.speechProcessorLabel}（音频发送至该服务；处理政策请向招聘者确认）` : "设备端离线识别，音频不发送至服务器"}。</p>}<p className="small muted">同意文本版本：{view.consentVersion}{view.retainedUntil ? ` · 最晚保留至 ${new Date(view.retainedUntil).toLocaleDateString("zh-CN")}` : ""}</p>{view.status === "invited" && <label className="checkbox-label"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} />我已阅读并明确同意以上说明</label>}<button className="button primary full-width" disabled={busy || !online || (view.status === "invited" && !accepted)} onClick={() => void start()}>{busy ? (view.cameraRequired || view.mode === "voice" ? "正在检测设备…" : "正在开始…") : (view.cameraRequired || view.mode === "voice") ? "同意、检测设备并开始 →" : "同意并开始面试 →"}</button></section>}
      {(view.mode === "voice" || view.cameraRequired) && ["consented", "warmup", "interviewing", "wrapping_up"].includes(view.status) && <InterviewMediaPanel
        view={view} stream={devices.stream} cameraActive={devices.status.cameraActive} microphoneActive={devices.status.microphoneActive}
        error={devices.error || speech.error} disabled={busy || !online}
        onCheck={() => void run(() => checkDevices())} onRelease={() => void pauseAndRelease()}
        onFallback={() => void fallback()} onInstall={() => void speech.install()} />}
      {view.cameraRequired && active && !view.pausedAt && token && (
        <VideoInterviewRoom
          interviewId={id}
          token={token}
          stream={devices.stream}
          enabled={Boolean(online && mediaReady)}
          fps={5}
        />
      )}
      {active && <>
        {view.recruitmentTrack === "graduate_campus" && <p className="notice">研究生校招 · 固定必问已触达 {view.mandatoryAsked}/{view.mandatoryTotal}。CET-4 ≥425分、研究生期间无挂科，待招聘者人工核验证明。{formalCampus ? "资格题须作答，暂不确定可填写待核验。其他题可跳过。" : "可以跳过不愿回答的问题。"}</p>}
        <div className="interview-toolbar"><div><span className={`connection-dot ${online ? "" : "offline"}`} /><span>{online ? "已连接 · 服务端保存进度" : "正在恢复连接"}</span></div><span className="timer" aria-label="剩余时间">{view.pausedAt ? "已暂停 · " : "剩余 "}{Math.floor(remaining / 60).toString().padStart(2, "0")}:{(remaining % 60).toString().padStart(2, "0")}</span></div>
        <section className="panel candidate-card interview-card"><div className="question-meta"><span className="pill">{view.status === "wrapping_up" ? "收尾补充" : view.followupsAsked > 0 ? `深入聊一聊 · 追问 ${view.followupsAsked}/2` : requiredQualification ? "硬性资格 · 必答" : view.currentQuestion?.mandatory ? (formalCampus ? "校招固定题" : "校招固定必问") : "核心问题"}</span><span className="small muted">第 {Math.max(1, view.questionSeq)} / {view.totalQuestions} 题</span></div><progress className="interview-progress" aria-label="面试进度" max={view.totalQuestions} value={view.answeredQuestions} />
          <div className="interviewer-label"><span className="interviewer-symbol">微</span><span>AI 面试官</span></div><h2 className="current-question" data-testid="current-question" aria-live="polite">{stream || view.currentQuestion?.text}</h2>
          {view.currentQuestion?.assessmentMode !== undefined && view.currentQuestion.assessmentMode !== "scored" && <p className="small muted">{view.currentQuestion.assessmentMode === "eligibility" ? "岗位硬指标事实记录，资格以人工核验证明为准。此题不计能力分。" : "此题用于了解岗位相关事实，不计能力分，可以不回答。"}</p>}
          {view.mode === "voice" && !view.pausedAt && <div className="voice-tools" aria-label="语音面试控制">
            <div className="button-row"><button type="button" className="button secondary" disabled={!speech.hasVoice || busy || speech.listening || speech.transcribing || speech.preparing} onClick={() => speech.speaking ? speech.stopPlayback() : speech.speak(view.currentQuestion?.text ?? "")}>{speech.speaking ? "打断播报" : "朗读题目"}</button>
              {view.textFallback ? <button type="button" className="button secondary" disabled={busy || !online} onClick={() => void run(() => checkDevices(false))}>恢复语音输入</button> :
                <button type="button" className="button primary" disabled={busy || !online || !mediaReady || speech.transcribing || speech.preparing} onClick={() => speech.listening ? speech.stop() : void speech.start()}>{speech.preparing ? "正在检查识别能力…" : speech.transcribing ? "正在转写…" : speech.listening ? "结束语音输入" : "开始语音输入"}</button>}
            </div>{!view.textFallback && <><label className="checkbox-label"><input type="checkbox" checked={interruption.enabled} onChange={(event) => interruption.setEnabled(event.target.checked)} />启用本地声音打断播报</label><p className="small muted">仅播报时在本机检测持续电平，不录音、不识别内容；建议佩戴耳机，环境噪声也可能触发。打断后仍需点击语音输入，核对后提交。</p>{interruption.notice && <p role="status">{interruption.notice}</p>}</>}<p className="small muted" role="status">{speech.listening ? "正在聆听，题目播报已停止；结束后请核对文字，再发送回答。" : view.textFallback ? "当前使用文字回退，摄像头要求仍保留。" : "点击开始语音输入可打断播报。语音仅用于转写内容，不分析声纹或情绪；核对文字后再提交。"}</p>
          </div>}
          {view.pausedAt ? <div className="pause-state"><h3>慢慢来，我们在这里等你。</h3><p>题目与已提交内容均已保存。暂停期间不计时。</p><button className="button primary" disabled={busy || !online} onClick={() => void resume()}>继续面试</button></div> : timeUp ? <div className="notice"><div><p>面试计时已结束。系统会先补问尚未完成的资格题，再结束面试。</p><button className="button primary" disabled={busy || !online} onClick={() => void submit("skip")}>{uncertain ? "确认提交结果" : "继续"}</button></div></div> : <form onSubmit={(event) => { event.preventDefault(); void submit("answer"); }}><label className="answer-label" htmlFor="answer">你的回答<span>{view.mode === "voice" ? "先核对语音转写，再发送" : requiredQualification ? "暂不确定可填写待核验" : view.currentQuestion?.assessmentMode === "scored" ? "可以从情境、行动与结果说起" : "说明相关事实即可，也可以跳过"}</span></label><textarea id="answer" className="answer-input" rows={6} value={draft} onChange={(event) => { speech.stopPlayback(); setDraft(event.target.value); }} placeholder={requiredQualification ? "请说明相关事实。暂不确定时可填写待核验。" : view.currentQuestion?.assessmentMode === "scored" ? "例如：当时遇到了什么问题？你具体做了什么？最后发生了哪些变化？" : "请说明相关事实；不确定或不愿提供时可以说明，或点击跳过。"} maxLength={4000} required disabled={inputBlocked} /><div className="answer-footer"><span className="small muted">{draft.length} / 4000 · 只有提交后才保存文字</span>{uncertain ? <button type="button" className="button primary" disabled={busy || !online || !mediaReady || speech.listening || speech.transcribing} onClick={() => void submit("answer")}>确认提交结果</button> : <button className="button primary" disabled={inputBlocked || !draft.trim()}>{busy ? "正在回应…" : "发送回答 ↑"}</button>}</div></form>}
          <div className="interview-controls"><button className="text-button" disabled={busy || Boolean(view.pausedAt) || uncertain || !online} onClick={() => void submit("repeat")}>↻ 请再说一次</button><button className="text-button" disabled={busy || Boolean(view.pausedAt) || uncertain || !online || requiredQualification || timeUp} onClick={() => void submit("skip")}>跳过本题 →</button><button className="text-button" disabled={busy || Boolean(view.pausedAt) || uncertain || !online} onClick={() => void pauseAndRelease()}>Ⅱ 暂停一下</button></div>
        </section><div className="candidate-bottom"><button className="text-button" disabled={busy || !online || uncertain} onClick={() => setConfirm("finish")}>提前结束面试</button><button className="text-button" disabled={busy || !online} onClick={() => setConfirm("withdraw")}>撤回同意</button></div>
        <details className="transcript"><summary>查看已保存的对话记录（{view.turns.length} 轮）</summary><ol>{view.turns.map((turn) => <li key={turn.seq}><span>{turn.role === "candidate" ? "你" : "AI 面试官"}</span><p>{turn.content}</p></li>)}</ol></details>
      </>}
      {completed && <section className="panel candidate-card completion"><span className="success-symbol">✓</span><p className="eyebrow">CONVERSATION COMPLETE</p><h2>感谢分享，这次对话已保存。</h2><p>你已经完成本场面试。后续评估由招聘者复核，AI 不会自动作出录用或淘汰决定。</p><div className="notice"><p>本次面试已进入评分阶段。招聘者可生成带原文证据的报告并进行人工复核；请等待招聘者沟通下一步。</p></div><button className="text-button" disabled={busy} onClick={() => setConfirm("withdraw")}>撤回本次面试同意</button></section>}
    </>}
    {confirm && <div className="modal-backdrop"><section ref={modalRef} className="panel confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title">{confirm === "withdraw" ? "撤回本次面试同意？" : "现在结束本场面试？"}</h2><p>{confirm === "withdraw" ? "撤回后立即停止采集，专属链接将失效。你仍可以联系招聘者提出删除已有数据的请求。" : "结束后无法继续回答，已提交的内容会保留供评估使用。"}</p><div className="button-row"><button autoFocus className="button secondary" onClick={() => setConfirm(null)}>返回</button><button className="button primary" disabled={busy} onClick={() => void close(confirm)}>{busy ? "处理中…" : confirm === "withdraw" ? "确认撤回" : "确认结束"}</button></div></section></div>}
    <p className="candidate-footnote">{view?.formalText ? "本场仅记录主动提交的文字回答。" : view?.cameraRequired ? "不做人脸、表情、情绪、视线或声纹分析。开启摄像头时，低频 JPEG 帧经加密通道发送供防作弊扩展；不做自动录用/淘汰。" : "不做人脸、表情、情绪、视线或声纹分析。摄像头画面仅本地预览，不上传、不录像。"}</p>
  </main></div>;
}
