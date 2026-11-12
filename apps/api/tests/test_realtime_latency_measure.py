"""Task 6b latency + barge-in acceptance measurement (fake providers, no network)."""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from interviewer.main import create_app
from interviewer.realtime.fakes import FakeASR, FakeTTS
from interviewer.realtime.pipeline import sine_pcm16le
from interviewer.settings import ROOT, Settings


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - rank) + ordered[high] * (rank - low)


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        sqlite_path=str(tmp_path / "latency.sqlite3"),
        secret="fixture-" * 8,
        admin_key="fixture-admin",
        recruiter_key="fixture-recruiter",
        provider="fake",
    )
    app = create_app(settings)
    fake_asr = FakeASR(delay_ms=8.0)
    fake_tts = FakeTTS(delay_ms=8.0, payload=b"\x00\x01" * 2500)
    app.state.service.gateway.asr = fake_asr
    app.state.service.gateway.tts = fake_tts

    def _transcribe(content: bytes, *, connection: object | None = None) -> str:
        _ = connection
        return fake_asr.transcribe(content).text

    app.state.service.gateway.transcribe = _transcribe  # type: ignore[method-assign]
    return TestClient(app)


def _seed(client: TestClient) -> tuple[str, str]:
    assert client.post("/api/auth/login", json={}).status_code == 200
    job = client.post(
        "/api/jobs",
        json={
            "title": "Lat" + uuid4().hex[:4],
            "jdText": "面向研发的岗位说明，负责实验系统实现、质量验证、协作与学习，以量化结果和个人贡献说明任务成效。",
            "recruitmentTrack": "general",
        },
    ).json()
    extracted = client.post(f"/api/jobs/{job['id']}/competencies:extract", json={}).json()
    client.patch(f"/api/jobs/{job['id']}/competencies", json={"competencies": extracted["competencies"]})
    person = client.post("/api/candidates", json={"jobId": job["id"], "fullName": "Lat"}).json()
    client.post(
        f"/api/candidates/{person['id']}/resume",
        json={"text": "技能Python；项目：我主导实验模块，个人负责实现和验证，将处理耗时降低30%。"},
    )
    invited = client.post(
        "/api/interviews",
        json={
            "jobId": job["id"],
            "candidateId": person["id"],
            "durationMinutes": 15,
            "mode": "text",
            "cameraRequired": False,
        },
    ).json()
    interview_id = str(invited["interviewId"])
    token = str(invited["inviteToken"])
    headers = {"Authorization": f"Bearer {token}"}
    state = client.get(f"/api/interviews/{interview_id}/state", headers=headers).json()
    client.post(
        f"/api/interviews/{interview_id}/consent",
        headers=headers,
        json={"accepted": True, "consentVersion": state["consentVersion"]},
    )
    client.post(f"/api/interviews/{interview_id}/start", headers=headers, json={})
    return interview_id, token


def _drain_types(ws: object, wanted: set[str], limit: int = 50) -> dict[str, object] | None:
    last: dict[str, object] | None = None
    for _ in range(limit):
        msg = json.loads(ws.receive_text())  # type: ignore[attr-defined]
        last = msg
        if msg["type"] in wanted:
            return msg
        if msg["type"] == "error":
            return msg
    return last


def test_measure_realtime_latency_and_write_acceptance(tmp_path: Path) -> None:
    samples = 8
    asr_ms: list[float] = []
    llm_ms: list[float] = []
    tts_ms: list[float] = []
    e2e_ms: list[float] = []
    interrupt_ms: list[float] = []

    # Fresh interview per sample so we never exhaust the question plan mid-harness.
    for i in range(samples):
        with _client(tmp_path / f"s{i}") as client:
            interview_id, token = _seed(client)
            with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
                ws.send_text(json.dumps({
                    "v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": 0,
                }))
                assert json.loads(ws.receive_text())["type"] == "ready"
                live = client.app.state.session_store.get(interview_id)
                assert live and live.pipeline

                pcm = sine_pcm16le(duration_ms=50, amplitude=7000)
                ws.send_text(json.dumps({
                    "v": "aii-ws-v1",
                    "type": "audio_chunk",
                    "seq": 0,
                    "pcmBase64": base64.b64encode(pcm).decode("ascii"),
                }))
                ws.send_text(json.dumps({
                    "v": "aii-ws-v1",
                    "type": "end_turn",
                    "idempotencyKey": f"lat-{uuid4().hex}",
                }))
                msg = _drain_types(ws, {"tts_chunk", "error"})
                assert msg is not None and msg["type"] == "tts_chunk", msg
                sample = live.pipeline.last_latency
                assert sample is not None
                assert sample.asr_first_ms is not None
                assert sample.llm_first_ms is not None
                assert sample.tts_first_ms is not None
                assert sample.e2e_ms is not None
                asr_ms.append(sample.asr_first_ms)
                llm_ms.append(sample.llm_first_ms)
                tts_ms.append(sample.tts_first_ms)
                e2e_ms.append(sample.e2e_ms)
                ws.send_text(json.dumps({"v": "aii-ws-v1", "type": "close"}))

    # Dedicated barge-in sample.
    with _client(tmp_path / "barge") as client:
        interview_id, token = _seed(client)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": 0,
            }))
            assert json.loads(ws.receive_text())["type"] == "ready"
            live = client.app.state.session_store.get(interview_id)
            assert live and live.pipeline and live.pipeline.player
            live.pipeline.player.chunk_delay_ms = 30.0
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "text_input",
                "text": "我主导了实验模块，个人负责实现，将耗时降低30%。",
                "idempotencyKey": f"lat-barge-{uuid4().hex}",
            }))
            assert _drain_types(ws, {"tts_chunk"}) is not None
            loud = sine_pcm16le(duration_ms=120, amplitude=12000)
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "audio_chunk",
                "seq": 1,
                "pcmBase64": base64.b64encode(loud).decode("ascii"),
            }))
            interrupted = _drain_types(ws, {"interrupted"})
            assert interrupted is not None and interrupted["type"] == "interrupted"
            assert live.pipeline.last_interrupt is not None
            interrupt_ms.append(live.pipeline.last_interrupt.silence_ms)

    assert len(asr_ms) == samples
    assert interrupt_ms and max(interrupt_ms) <= 200

    report = {
        "method": {
            "provider": "fake ASR/TTS + fake LLM via service.turn",
            "harness": "pytest test_measure_realtime_latency_and_write_acceptance",
            "points": {
                "asr_first_ms": "T_asr - T0 after gateway.transcribe returns",
                "llm_first_ms": "service.turn wall time until utterance",
                "tts_first_ms": "first tts_chunk send - post-turn",
                "e2e_ms": "first tts_chunk - T0",
                "interrupt_silence_ms": "interrupted_sent - vad_onset",
            },
            "sample_size": samples,
        },
        "asr_first_ms": {
            "n": len(asr_ms), "p50": _percentile(asr_ms, 0.5),
            "p95": _percentile(asr_ms, 0.95), "max": max(asr_ms), "values_ms": asr_ms,
        },
        "llm_first_ms": {
            "n": len(llm_ms), "p50": _percentile(llm_ms, 0.5),
            "p95": _percentile(llm_ms, 0.95), "max": max(llm_ms), "values_ms": llm_ms,
        },
        "tts_first_ms": {
            "n": len(tts_ms), "p50": _percentile(tts_ms, 0.5),
            "p95": _percentile(tts_ms, 0.95), "max": max(tts_ms), "values_ms": tts_ms,
        },
        "e2e_ms": {
            "n": len(e2e_ms), "p50": _percentile(e2e_ms, 0.5),
            "p95": _percentile(e2e_ms, 0.95), "max": max(e2e_ms), "values_ms": e2e_ms,
        },
        "interrupt_silence_ms": {
            "n": len(interrupt_ms), "values": interrupt_ms,
            "max": max(interrupt_ms), "budget_ms": 200, "pass": max(interrupt_ms) <= 200,
        },
        "budgets": {"asr_first_ms": 300, "llm_first_ms": 800, "tts_first_ms": 400, "e2e_p95_ms": 1500},
        "pass": {
            "asr": _percentile(asr_ms, 0.95) < 300,
            "llm": _percentile(llm_ms, 0.95) < 800,
            "tts": _percentile(tts_ms, 0.95) < 400,
            "e2e": _percentile(e2e_ms, 0.95) < 1500,
            "interrupt_200ms": max(interrupt_ms) <= 200,
        },
    }
    assert all(report["pass"].values()), report

    out = ROOT / "docs" / "acceptance" / "evidence" / "task6b-realtime-latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
