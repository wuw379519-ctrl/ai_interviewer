"""Task 6b: pipeline, VAD barge-in, supersede in-flight discard, latency probes."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from interviewer.contracts import SpeechOutput
from interviewer.main import create_app
from interviewer.realtime.fakes import FakeASR, FakeTTS
from interviewer.realtime.pipeline import pcm16le_to_wav, sine_pcm16le
from interviewer.realtime.session_store import CLOSE_SUPERSEDED
from interviewer.realtime.vad import EnergyVad, VadConfig
from interviewer.settings import Settings


def _app_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        sqlite_path=str(tmp_path / "pipe.sqlite3"),
        secret="fixture-" * 8,
        admin_key="fixture-admin",
        recruiter_key="fixture-recruiter",
        provider="fake",
    )
    app = create_app(settings)
    service = app.state.service
    fake_asr = FakeASR(delay_ms=2.0)
    fake_tts = FakeTTS(delay_ms=2.0)
    service.gateway.asr = fake_asr
    service.gateway.tts = fake_tts

    def _transcribe(content: bytes, *, connection: object | None = None) -> str:
        _ = connection
        return fake_asr.transcribe(content).text

    service.gateway.transcribe = _transcribe  # type: ignore[method-assign]
    return TestClient(app)


def _seed_interviewing(client: TestClient) -> tuple[str, str, dict[str, str]]:
    assert client.post("/api/auth/login", json={}).status_code == 200
    job = client.post(
        "/api/jobs",
        json={
            "title": "Pipe岗位" + uuid4().hex[:4],
            "jdText": "面向研发的岗位说明，负责实验系统实现、质量验证、协作与学习，以量化结果和个人贡献说明任务成效。",
            "recruitmentTrack": "general",
        },
    )
    assert job.status_code == 201, job.text
    job_id = job.json()["id"]
    extracted = client.post(f"/api/jobs/{job_id}/competencies:extract", json={})
    assert extracted.status_code == 200
    assert client.patch(
        f"/api/jobs/{job_id}/competencies",
        json={"competencies": extracted.json()["competencies"]},
    ).status_code == 200
    person = client.post("/api/candidates", json={"jobId": job_id, "fullName": "Pipe候选人"})
    assert person.status_code == 201
    assert client.post(
        f"/api/candidates/{person.json()['id']}/resume",
        json={"text": "技能Python；项目：我主导实验模块，个人负责实现和验证，将处理耗时降低30%。"},
    ).status_code == 201
    invited = client.post(
        "/api/interviews",
        json={
            "jobId": job_id,
            "candidateId": person.json()["id"],
            "durationMinutes": 15,
            "mode": "text",
            "cameraRequired": False,
        },
    )
    assert invited.status_code == 201, invited.text
    body = invited.json()
    interview_id = str(body["interviewId"])
    token = str(body["inviteToken"])
    headers = {"Authorization": f"Bearer {token}"}
    state = client.get(f"/api/interviews/{interview_id}/state", headers=headers).json()
    assert client.post(
        f"/api/interviews/{interview_id}/consent",
        headers=headers,
        json={"accepted": True, "consentVersion": state["consentVersion"]},
    ).status_code == 200
    assert client.post(f"/api/interviews/{interview_id}/start", headers=headers, json={}).status_code == 200
    return interview_id, token, headers


def _auth(ws: object, token: str, resume: int = 0) -> dict[str, object]:
    ws.send_text(json.dumps({  # type: ignore[attr-defined]
        "v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": resume,
    }))
    ready = json.loads(ws.receive_text())  # type: ignore[attr-defined]
    assert ready["type"] == "ready"
    return ready


def _drain_until(ws: object, typ: str, limit: int = 40) -> dict[str, object]:
    seen: list[str] = []
    for _ in range(limit):
        msg = json.loads(ws.receive_text())  # type: ignore[attr-defined]
        seen.append(str(msg.get("type")))
        if msg["type"] == typ:
            return msg
    raise AssertionError(f"did not see {typ}; saw {seen}")


def test_energy_vad_onset_on_loud_tone() -> None:
    vad = EnergyVad(VadConfig(energy_threshold=500.0, onset_ms=40))
    quiet = sine_pcm16le(duration_ms=50, amplitude=10)
    loud = sine_pcm16le(duration_ms=100, amplitude=8000)
    assert not vad.push(quiet).just_started
    decision = vad.push(loud)
    assert decision.just_started
    assert decision.speech_active


def test_pipeline_text_input_to_question_and_tts(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, token, _ = _seed_interviewing(client)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            _auth(ws, token)
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "text_input",
                "text": "我主导了实验模块，个人负责实现，将耗时降低30%。",
                "idempotencyKey": "ws-text-" + uuid4().hex,
            }))
            final = _drain_until(ws, "final_transcript")
            assert "主导" in final["text"]
            question = _drain_until(ws, "question")
            assert question["text"]
            tts = _drain_until(ws, "tts_chunk")
            assert tts.get("audioBase64")
            live = client.app.state.session_store.get(interview_id)
            assert live is not None and live.pipeline is not None
            sample = live.pipeline.last_latency
            assert sample is not None
            assert sample.llm_first_ms is not None and sample.llm_first_ms < 800
            assert sample.tts_first_ms is not None and sample.tts_first_ms < 400
            assert sample.e2e_ms is not None and sample.e2e_ms < 1500


def test_pipeline_audio_end_turn_asr_path(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, token, _ = _seed_interviewing(client)
        pcm = sine_pcm16le(duration_ms=120, amplitude=6000)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            _auth(ws, token)
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "audio_chunk",
                "seq": 0,
                "pcmBase64": base64.b64encode(pcm).decode("ascii"),
                "format": "pcm16le_16k",
            }))
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "end_turn",
                "idempotencyKey": "ws-audio-" + uuid4().hex,
            }))
            partial = _drain_until(ws, "partial_transcript")
            assert partial["text"]
            final = _drain_until(ws, "final_transcript")
            assert final["text"]
            question = _drain_until(ws, "question")
            assert question["text"]
            live = client.app.state.session_store.get(interview_id)
            assert live and live.pipeline and live.pipeline.last_latency
            assert live.pipeline.last_latency.asr_first_ms is not None
            assert live.pipeline.last_latency.asr_first_ms < 300


def test_vad_barge_in_clears_tts_within_200ms(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, token, _ = _seed_interviewing(client)
        # Slow TTS chunks so barge-in can fire mid-play.
        client.app.state.service.gateway.tts = FakeTTS(delay_ms=1.0, payload=b"\x00\x01" * 8000)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            _auth(ws, token)
            live = client.app.state.session_store.get(interview_id)
            assert live and live.pipeline and live.pipeline.player
            live.pipeline.player.chunk_delay_ms = 40.0
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "text_input",
                "text": "我主导了实验模块，个人负责实现，将耗时降低30%。",
                "idempotencyKey": "ws-barge-" + uuid4().hex,
            }))
            _drain_until(ws, "tts_chunk")
            # Loud speech while TTS playing → VAD barge-in
            loud = sine_pcm16le(duration_ms=120, amplitude=12000)
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "audio_chunk",
                "seq": 1,
                "pcmBase64": base64.b64encode(loud).decode("ascii"),
            }))
            interrupted = _drain_until(ws, "interrupted")
            assert interrupted.get("reason") == "vad_barge_in"
            live = client.app.state.session_store.get(interview_id)
            assert live and live.pipeline and live.pipeline.last_interrupt
            assert live.pipeline.last_interrupt.silence_ms <= 200.0
            assert live.pipeline.player is not None
            assert live.pipeline.player.playing is False


def test_supersede_discards_inflight_turn(tmp_path: Path) -> None:
    """Old connection in-flight turn is cancelled; new connection resumes events only."""

    class SlowASR(FakeASR):
        def transcribe(self, content: bytes) -> SpeechOutput:
            time.sleep(0.35)
            return super().transcribe(content)

    with _app_client(tmp_path) as client:
        interview_id, token, headers = _seed_interviewing(client)
        slow = SlowASR(delay_ms=0.0)
        client.app.state.service.gateway.asr = slow

        def _slow_transcribe(content: bytes, *, connection: object | None = None) -> str:
            _ = connection
            return slow.transcribe(content).text

        client.app.state.service.gateway.transcribe = _slow_transcribe  # type: ignore[method-assign]
        pcm = sine_pcm16le(duration_ms=80, amplitude=5000)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws1:
            ready1 = _auth(ws1, token)
            seq_before = int(ready1["resumeFromSeq"])
            ws1.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "audio_chunk",
                "seq": 0,
                "pcmBase64": base64.b64encode(pcm).decode("ascii"),
            }))
            # Kick off end_turn without waiting — then supersede.
            ws1.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "end_turn",
                "idempotencyKey": "ws-inflight-" + uuid4().hex,
            }))
            with client.websocket_connect(f"/ws/interview/{interview_id}") as ws2:
                ready2 = _auth(ws2, token, resume=seq_before)
                assert ready2["type"] == "ready"
                closed_code: int | None = None
                for _ in range(30):
                    try:
                        ws1.receive_text()
                    except WebSocketDisconnect as error:
                        closed_code = error.code
                        break
                assert closed_code == CLOSE_SUPERSEDED
                # New connection can still submit a distinct turn; no duplicate ask from discarded path.
                ws2.send_text(json.dumps({
                    "v": "aii-ws-v1",
                    "type": "text_input",
                    "text": "我主导了实验模块，个人负责实现，将耗时降低30%。",
                    "idempotencyKey": "ws-after-resume-" + uuid4().hex,
                }))
                question = _drain_until(ws2, "question")
                assert question["text"]
        # HTTP state still consistent (one answer path from ws2).
        state = client.get(f"/api/interviews/{interview_id}/state", headers=headers).json()
        assert state["status"] in {"interviewing", "wrapping_up"}


def test_audio_chunk_seq_must_increase(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        interview_id, token, _ = _seed_interviewing(client)
        pcm = base64.b64encode(sine_pcm16le(40)).decode("ascii")
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            _auth(ws, token)
            ws.send_text(json.dumps({"v": "aii-ws-v1", "type": "audio_chunk", "seq": 0, "pcmBase64": pcm}))
            ws.send_text(json.dumps({"v": "aii-ws-v1", "type": "audio_chunk", "seq": 0, "pcmBase64": pcm}))
            err = _drain_until(ws, "error")
            assert err["code"] == "VALIDATION_FAILED"


def test_pcm16le_to_wav_header() -> None:
    pcm = sine_pcm16le(20)
    wav = pcm16le_to_wav(pcm)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
