const API = "http://127.0.0.1:8010/api/interview";
const SESSION_KEY = "interviewer-practice-token";
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const element = (id) => document.getElementById(id);

const consentForm = element("consent-form");
const accept = element("accept");
const start = element("start");
const erase = element("erase");
const fields = element("answer-fields");
const answer = element("answer");
const audio = element("audio");
const send = element("send");
const conversation = element("conversation");

let info;
let token = sessionStorage.getItem(SESSION_KEY) || "";
let active = false;
let waiting = false;
let needsErase = false;
let pendingKey = "";
let rounds = 0;

class RequestError extends Error {
  constructor(status, message, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(path, { method = "GET", body, headers = {} } = {}) {
  let response;
  try {
    response = await fetch(`${API}/${path}`, {
      method, body, credentials: "omit", cache: "no-store",
      headers: { ...headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  } catch {
    throw new RequestError(0, "无法连接面试服务。请确认后端已在 8010 启动，然后重试。");
  }
  if (response.status === 204) return;
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload) {
    throw new RequestError(response.status, payload?.error?.message || "请求失败，请稍后重试。", payload?.error?.code);
  }
  return payload;
}

function setFeedback(message, isError = false) {
  const feedback = element("feedback");
  feedback.textContent = message;
  feedback.dataset.state = isError ? "error" : "normal";
}

function updateControls() {
  consentForm.hidden = active;
  element("active-note").hidden = !active;
  accept.disabled = !info || waiting || needsErase;
  start.disabled = accept.disabled || !accept.checked;
  fields.disabled = !active || waiting || needsErase;
  audio.disabled = !info?.audio_enabled;
  erase.hidden = !token || !info;
  erase.disabled = waiting;
  send.disabled = fields.disabled || (!answer.value.trim() && !audio.files.length);
}

function addMessage(role, text) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const label = document.createElement("p");
  label.className = "role";
  label.textContent = role === "candidate" ? "候选人" : "面试官";
  const bubble = document.createElement("p");
  bubble.className = "bubble";
  bubble.textContent = text;
  item.append(label, bubble);
  conversation.append(item);
}

function addTurn(turn) {
  addMessage("candidate", turn.user_text);
  addMessage("interviewer", turn.ai_reply);
  rounds += 1;
  element("round-count").textContent = `${rounds} 轮对话`;
  conversation.scrollTop = conversation.scrollHeight;
}

function showHistory(turns) {
  conversation.replaceChildren();
  rounds = 0;
  element("round-count").textContent = "0 轮对话";
  addMessage("interviewer", info.opening);
  turns.forEach(addTurn);
}

function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
  token = "";
  active = false;
  needsErase = false;
  pendingKey = "";
  accept.checked = false;
  answer.value = "";
  audio.value = "";
  showHistory([]);
}

function handleFailure(error) {
  if (error.status === 401 && info) clearSession();
  if (error.code === "CONSENT_REQUIRED") needsErase = true;
  setFeedback(error.message, true);
}

async function initialize() {
  try {
    info = await request("chat");
    element("consent-copy").textContent = info.consent_text;
    element("consent-version").textContent = `说明版本 ${info.consent_version}`;
    const badge = element("model-badge");
    badge.dataset.state = "ready";
    badge.textContent = info.fake ? "本地演示 · Fake" : "已配置模型";
    if (!info.audio_enabled) {
      element("input-hint").textContent = "当前仅支持文字 · 启用本机 Whisper 后可上传音频文件";
    }
    showHistory([]);
    if (token) {
      const session = await request("session");
      showHistory(session.turns);
      active = true;
    }
    setFeedback(active ? "已恢复会话，可以继续作答。" : "请先阅读并确认知情说明。");
  } catch (error) {
    if (!info) {
      const badge = element("model-badge");
      badge.dataset.state = "error";
      badge.textContent = "服务未连接";
      element("consent-copy").textContent = "启动后端后，请刷新本页。";
    }
    handleFailure(error);
  } finally {
    updateControls();
  }
}

accept.addEventListener("change", updateControls);
consentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!accept.checked || !info || waiting || needsErase) return;
  waiting = true;
  updateControls();
  try {
    if (!token) {
      token = Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) => byte.toString(16).padStart(2, "0")).join("");
      sessionStorage.setItem(SESSION_KEY, token);
    }
    const session = await request("session", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepted: true, consent_version: info.consent_version }),
    });
    active = true;
    showHistory(session.turns);
    setFeedback("可以开始作答。");
  } catch (error) {
    handleFailure(error);
  } finally {
    waiting = false;
    updateControls();
    if (active) answer.focus();
  }
});

function inputChanged() {
  pendingKey = "";
  updateControls();
}

answer.addEventListener("input", inputChanged);
audio.addEventListener("change", inputChanged);
element("answer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!active || waiting) return;
  const text = answer.value.trim();
  const file = audio.files[0];
  if (Boolean(text) === Boolean(file)) {
    setFeedback("请填写文字或选择一个音频文件，每轮只发送一种。", true);
    return;
  }
  if (file && (file.size === 0 || file.size > MAX_FILE_BYTES)) {
    setFeedback("请选择非空且不超过 16 MiB 的音频文件。", true);
    return;
  }
  const body = new FormData();
  if (file) body.append("file", file);
  else body.append("text", text);
  pendingKey ||= crypto.randomUUID();
  waiting = true;
  setFeedback(file ? "本机正在转写音频，随后生成追问…" : "面试官正在生成追问…");
  updateControls();
  try {
    const turn = await request("chat", { method: "POST", body, headers: { "Idempotency-Key": pendingKey } });
    addTurn(turn);
    answer.value = "";
    audio.value = "";
    pendingKey = "";
    setFeedback(file ? "已发送音频转写并收到追问。" : "已收到追问。");
  } catch (error) {
    handleFailure(error);
  } finally {
    waiting = false;
    updateControls();
  }
});

erase.addEventListener("click", async () => {
  if (waiting || !window.confirm("删除本次练习和已保存的所有回答？")) return;
  waiting = true;
  updateControls();
  try {
    await request("session", { method: "DELETE" });
    clearSession();
    setFeedback("本次会话已删除。可重新开始练习。");
  } catch (error) {
    handleFailure(error);
  } finally {
    waiting = false;
    updateControls();
  }
});

initialize();
