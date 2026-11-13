"""Task 9b: FakeVisionDetector → proctor_logs + riskItems (no heavy CV deps)."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import interviewer.realtime.pipeline as pipeline_mod
from interviewer.proctoring import list_proctor_logs, score_proctor_risks
from interviewer.proctoring.vision import FakeVisionDetector
from interviewer.realtime.pipeline import RealtimePipeline
from interviewer.realtime.protocol import VideoChunkMessage
from interviewer.realtime.session_store import LiveSession
from interviewer.tenancy import DEFAULT_TENANT_ID, reset_current_tenant, set_current_tenant
from test_proctoring import _app, _seed_interviewing


TINY_JPEG = base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")


class _FakeWs:
    """Minimal stand-in for LiveSession.websocket (unused by vision path)."""


def test_score_vision_and_camera_risk_items() -> None:
    none = score_proctor_risks([])
    assert none == []
    risks = score_proctor_risks([
        {"signalType": "no_face", "payload": {"durationSec": 12}},
        {"signalType": "multi_face", "payload": {"faceCount": 2}},
        {"signalType": "camera_stall", "payload": {"idleSec": 11}},
        {"signalType": "camera_lost", "payload": {"reason": "track_ended"}},
        {"signalType": "tab_hidden", "payload": {}},
        {"signalType": "answer_latency", "payload": {"latencyMs": 400}},
    ])
    codes = {item.code for item in risks}
    assert "no_face_detected" in codes
    assert "multi_face_detected" in codes
    assert "camera_feed_interrupted" in codes
    assert "tab_switch_noted" in codes
    assert "answer_too_fast" in codes
    assert all(item.affects_score is False for item in risks)


def _pipeline(service: Any, interview_id: str, vision: FakeVisionDetector) -> tuple[RealtimePipeline, list[object]]:
    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    session = LiveSession(
        interview_id=interview_id,
        tenant_id=DEFAULT_TENANT_ID,
        connection_id="vision-test-" + uuid4().hex[:8],
        websocket=_FakeWs(),  # type: ignore[arg-type]
    )
    pipe = RealtimePipeline(
        service=service,
        session=session,
        send=send,
        vision=vision,
    )
    return pipe, sent


def test_fake_vision_no_face_and_multi_face_emit_logs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pipeline_mod, "NO_FACE_SEC", 0.05)
    monkeypatch.setattr(pipeline_mod, "MULTI_FACE_SEC", 0.05)

    async def _run() -> None:
        with _app(tmp_path) as client:
            interview_id, _token = _seed_interviewing(client)
            service = client.app.state.service
            vision = FakeVisionDetector(face_count=0)
            pipeline, _sent = _pipeline(service, interview_id, vision)

            await pipeline.handle_video_chunk(VideoChunkMessage.model_validate({
                "type": "video_chunk", "seq": 0, "frameBase64": TINY_JPEG, "format": "jpeg",
            }))
            await asyncio.sleep(0.06)
            await pipeline.handle_video_chunk(VideoChunkMessage.model_validate({
                "type": "video_chunk", "seq": 1, "frameBase64": TINY_JPEG, "format": "jpeg",
            }))
            assert vision.calls >= 2
            assert pipeline.last_video_bytes is None

            vision.face_count = 2
            await pipeline.handle_video_chunk(VideoChunkMessage.model_validate({
                "type": "video_chunk", "seq": 2, "frameBase64": TINY_JPEG, "format": "jpeg",
            }))
            await asyncio.sleep(0.06)
            await pipeline.handle_video_chunk(VideoChunkMessage.model_validate({
                "type": "video_chunk", "seq": 3, "frameBase64": TINY_JPEG, "format": "jpeg",
            }))
            pipeline.cancel()

            token = set_current_tenant(DEFAULT_TENANT_ID)
            try:
                with service.database.unit_of_work() as connection:
                    rows = list_proctor_logs(connection, interview_id)
            finally:
                reset_current_tenant(token)
            types = {str(row["signalType"]) for row in rows}
            assert "no_face" in types
            assert "multi_face" in types
            risks = score_proctor_risks(rows)
            codes = {item.code for item in risks}
            assert "no_face_detected" in codes
            assert "multi_face_detected" in codes
            assert all(item.affects_score is False for item in risks)

    asyncio.run(_run())


def test_camera_stall_watcher_logs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(pipeline_mod, "VIDEO_STALL_SEC", 0.05)

    async def _run() -> None:
        with _app(tmp_path) as client:
            interview_id, _token = _seed_interviewing(client)
            service = client.app.state.service
            vision = FakeVisionDetector(face_count=1)
            pipeline, sent = _pipeline(service, interview_id, vision)

            await pipeline.handle_video_chunk(VideoChunkMessage.model_validate({
                "type": "video_chunk", "seq": 0, "frameBase64": TINY_JPEG, "format": "jpeg",
            }))
            # Backdate so the next stall-loop tick sees idle >= VIDEO_STALL_SEC.
            assert pipeline.last_video_mono is not None
            pipeline.last_video_mono -= 1.0
            # Ensure watcher is running even if __post_init__ had no loop.
            if pipeline.stall_task is None or pipeline.stall_task.done():
                pipeline.stall_task = asyncio.create_task(pipeline._watch_video_stall())
            for _ in range(40):
                await asyncio.sleep(0.05)
                if any(getattr(m, "type", None) == "state_changed" for m in sent):
                    break
            pipeline.cancel()

            assert any(
                getattr(m, "type", None) == "state_changed"
                and getattr(m, "detail", {}) is not None
                and dict(getattr(m, "detail", {}) or {}).get("via") == "camera_stall"
                for m in sent
            )
            token = set_current_tenant(DEFAULT_TENANT_ID)
            try:
                with service.database.unit_of_work() as connection:
                    rows = list_proctor_logs(connection, interview_id)
            finally:
                reset_current_tenant(token)
            assert any(row["signalType"] == "camera_stall" for row in rows)
            risks = score_proctor_risks(rows)
            assert any(item.code == "camera_feed_interrupted" for item in risks)

    asyncio.run(_run())


def test_ws_camera_lost_proctor_signal(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        interview_id, token = _seed_interviewing(client)
        with client.websocket_connect(f"/ws/interview/{interview_id}") as ws:
            ws.send_text(json.dumps({
                "v": "aii-ws-v1", "type": "auth", "token": token, "resumeFromSeq": 0,
            }))
            for _ in range(8):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "ready":
                    break
            ws.send_text(json.dumps({
                "v": "aii-ws-v1",
                "type": "proctor_signal",
                "signalType": "camera_lost",
                "payload": {"reason": "permission_denied"},
            }))
            ack = None
            for _ in range(12):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "state_changed" and msg.get("detail", {}).get("signalType") == "camera_lost":
                    ack = msg
                    break
            assert ack is not None
        service = client.app.state.service
        token_ctx = set_current_tenant(DEFAULT_TENANT_ID)
        try:
            with service.database.unit_of_work() as connection:
                rows = list_proctor_logs(connection, interview_id)
                assert any(row["signalType"] == "camera_lost" for row in rows)
                risks = score_proctor_risks(rows)
                assert any(item.code == "camera_feed_interrupted" for item in risks)
        finally:
            reset_current_tenant(token_ctx)
