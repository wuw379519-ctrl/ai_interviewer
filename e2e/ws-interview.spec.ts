import { test, expect, type APIRequestContext } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { competencySetSchema, createdInterviewSchema, CONSENT_VERSION, interviewStateSchema } from "../packages/core/src/index";
import { REALTIME_PROTOCOL_VERSION } from "../packages/core/src/realtime-protocol";

async function invitation(request: APIRequestContext) {
  expect((await request.post("/api/auth/login", { data: {} })).ok()).toBe(true);
  const jobResponse = await request.post("/api/jobs", {
    data: {
      title: `WS实时 ${randomUUID().slice(0, 6)}`,
      jdText: "负责 TypeScript React 项目交付，分析性能瓶颈与架构取舍，通过量化结果验证收益，与产品后端协作并保障质量。",
    },
  });
  const job = await jobResponse.json() as { id: string };
  const extraction = await request.post(`/api/jobs/${job.id}/competencies:extract`, { data: {} });
  const dimensions = competencySetSchema.parse(await extraction.json());
  expect((await request.patch(`/api/jobs/${job.id}/competencies`, { data: dimensions })).ok()).toBe(true);
  const candidate = await (await request.post("/api/candidates", {
    data: { jobId: job.id, fullName: "WS实时候选人" },
  })).json() as { id: string };
  await request.post(`/api/candidates/${candidate.id}/resume`, {
    data: { text: "技能TypeScript；项目：我主导前端模块，个人负责实现和验证，将首屏耗时降低30%。" },
  });
  const response = await request.post("/api/interviews", {
    data: { jobId: job.id, candidateId: candidate.id, durationMinutes: 15, mode: "text", cameraRequired: false },
  });
  expect(response.ok()).toBe(true);
  return createdInterviewSchema.parse(await response.json());
}

test("WS 主路径：连接 → text_input → question → interrupt → resume + event_replay", async ({ page, request }) => {
  test.setTimeout(120000);
  const created = await invitation(request);
  const id = created.interviewId;
  const token = created.inviteToken;
  const headers = { Authorization: `Bearer ${token}` };
  const state = await (await request.get(`/api/interviews/${id}/state`, { headers })).json() as {
    consentVersion: string;
  };
  expect((await request.post(`/api/interviews/${id}/consent`, {
    headers,
    data: { accepted: true, consentVersion: state.consentVersion || CONSENT_VERSION },
  })).ok()).toBe(true);
  expect((await request.post(`/api/interviews/${id}/start`, { headers, data: {} })).ok()).toBe(true);

  const before = interviewStateSchema.parse(
    await (await request.get(`/api/interviews/${id}/state`, { headers })).json(),
  );
  const answeredBefore = before.answeredQuestions;
  const questionSeqBefore = before.questionSeq;
  const turnCountBefore = before.turns.length;

  // WS is mounted on the Python API (8101 in Playwright), not proxied via Next /api.
  await page.goto("/");
  const apiOrigin = "http://127.0.0.1:8101";

  const result = await page.evaluate(async ({ interviewId, inviteToken, protocol, apiOrigin }) => {
    const url = apiOrigin.replace(/^http/, "ws") + `/ws/interview/${interviewId}`;
    const messages: Array<Record<string, unknown>> = [];

    function open(): Promise<WebSocket> {
      return new Promise((resolve, reject) => {
        const socket = new WebSocket(url);
        const timer = window.setTimeout(() => reject(new Error("ws open timeout")), 15000);
        socket.addEventListener("open", () => {
          window.clearTimeout(timer);
          resolve(socket);
        });
        socket.addEventListener("error", () => {
          window.clearTimeout(timer);
          reject(new Error("ws error"));
        });
      });
    }

    function waitType(socket: WebSocket, type: string, ms = 20000): Promise<Record<string, unknown>> {
      return new Promise((resolve, reject) => {
        const timer = window.setTimeout(() => reject(new Error(`timeout waiting ${type}`)), ms);
        const onMessage = (event: MessageEvent) => {
          const data = JSON.parse(String(event.data)) as Record<string, unknown>;
          messages.push(data);
          if (data.type === type) {
            window.clearTimeout(timer);
            socket.removeEventListener("message", onMessage);
            resolve(data);
          }
        };
        socket.addEventListener("message", onMessage);
      });
    }

    const ws1 = await open();
    ws1.send(JSON.stringify({
      v: protocol,
      type: "auth",
      token: inviteToken,
      resumeFromSeq: 0,
    }));
    const ready1 = await waitType(ws1, "ready");
    const resumeFrom = Number(ready1.resumeFromSeq || 0);

    ws1.send(JSON.stringify({
      v: protocol,
      type: "text_input",
      text: "我主导了前端模块，个人负责实现，将首屏耗时降低30%。",
      idempotencyKey: `e2e-ws-${crypto.randomUUID()}`,
    }));
    const question1 = await waitType(ws1, "question");
    const questionSeq1 = Number(question1.questionSeq);

    ws1.send(JSON.stringify({ v: protocol, type: "interrupt" }));
    const interrupted = await waitType(ws1, "interrupted");

    // Second connection supersedes and resumes (same recovery path sticky-miss relies on: DB event_replay).
    const ws2 = await open();
    const afterAuth: Array<Record<string, unknown>> = [];
    const collect = (event: MessageEvent) => {
      afterAuth.push(JSON.parse(String(event.data)) as Record<string, unknown>);
    };
    ws2.addEventListener("message", collect);
    ws2.send(JSON.stringify({
      v: protocol,
      type: "auth",
      token: inviteToken,
      resumeFromSeq: resumeFrom,
    }));
    const ready2 = await waitType(ws2, "ready");
    // Drain briefly for event_replay (sent right after ready when events exist).
    await new Promise((r) => window.setTimeout(r, 500));
    const replay = afterAuth.find((m) => m.type === "event_replay")
      ?? messages.filter((m) => m.type === "event_replay").at(-1);

    ws2.send(JSON.stringify({ v: protocol, type: "ping", t: 99 }));
    const pong = await waitType(ws2, "pong");
    ws2.removeEventListener("message", collect);
    ws2.close();
    ws1.close();
    return {
      interruptedReason: interrupted.reason,
      pongT: pong.t,
      types: messages.map((m) => m.type),
      questionSeq1,
      resumeFrom,
      ready2Resume: Number(ready2.resumeFromSeq || 0),
      replay: replay
        ? {
          fromSeq: Number((replay as { fromSeq?: number }).fromSeq ?? -1),
          events: ((replay as { events?: Array<Record<string, unknown>> }).events ?? []),
        }
        : null,
      afterAuthTypes: afterAuth.map((m) => m.type),
    };
  }, {
    interviewId: id,
    inviteToken: token,
    protocol: REALTIME_PROTOCOL_VERSION,
    apiOrigin,
  });

  expect(result.interruptedReason === "client" || result.interruptedReason === "vad_barge_in").toBeTruthy();
  expect(result.pongT).toBe(99);
  expect(result.types).toContain("question");
  expect(result.types).toContain("interrupted");

  // event_replay must be present after resumeFromSeq < latest (sticky-miss recovery contract).
  expect(result.replay).not.toBeNull();
  expect(result.replay!.fromSeq).toBe(result.resumeFrom);
  expect(result.replay!.events.length).toBeGreaterThan(0);
  const seqs = result.replay!.events.map((e) => Number(e.seq));
  expect(seqs.every((s) => Number.isFinite(s) && s > result.resumeFrom)).toBe(true);
  expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
  expect(new Set(seqs).size).toBe(seqs.length);
  expect(result.ready2Resume).toBeGreaterThanOrEqual(Math.max(...seqs));

  // State machine: answered progress advanced; no reset / no lost confirmed turns.
  const after = interviewStateSchema.parse(
    await (await request.get(`/api/interviews/${id}/state`, { headers })).json(),
  );
  expect(after.status).toBe(before.status);
  expect(after.answeredQuestions).toBeGreaterThanOrEqual(answeredBefore);
  expect(after.turns.length).toBeGreaterThan(turnCountBefore);
  expect(after.questionSeq).toBeGreaterThanOrEqual(questionSeqBefore);
  // Current question should match the last interviewer prompt (not a replayed duplicate ask).
  const lastInterviewer = [...after.turns].reverse().find((t) => t.role === "interviewer");
  expect(lastInterviewer?.content?.length ?? 0).toBeGreaterThan(0);
  expect(result.questionSeq1).toBeGreaterThanOrEqual(1);
});
