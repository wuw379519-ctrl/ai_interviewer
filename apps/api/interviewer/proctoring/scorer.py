"""Rule-based proctor risk scoring — hints for humans only (never auto hire/reject)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from interviewer.contracts import Object

Severity = Literal["hint", "review"]

# Thresholds — calibrate with real data later (documented limitation).
TAB_HIDDEN_REVIEW_THRESHOLD = 3
ANSWER_LATENCY_FAST_MS = 3000
SILENCE_RATIO_HINT = 0.7
VOLUME_SPIKE_RMS_DELTA = 4000.0


@dataclass(frozen=True)
class ProctorRiskItem:
    code: str
    severity: Severity
    message: str
    signal_count: int
    affects_score: bool = False  # always False — safety red line
    for_human_review: bool = True

    def payload(self) -> Object:
        raw = asdict(self)
        return {
            "code": raw["code"],
            "severity": raw["severity"],
            "message": raw["message"],
            "signalCount": raw["signal_count"],
            "affectsScore": raw["affects_score"],
            "forHumanReview": raw["for_human_review"],
        }


def score_proctor_risks(logs: list[Object]) -> list[ProctorRiskItem]:
    """Map proctor_logs → structured risk items. No item enters the scoring evidence chain."""
    items: list[ProctorRiskItem] = []
    tab_events = [row for row in logs if str(row.get("signalType")) in {"tab_hidden", "window_blur"}]
    if len(tab_events) >= TAB_HIDDEN_REVIEW_THRESHOLD:
        items.append(ProctorRiskItem(
            code="excessive_tab_switch",
            severity="review",
            message=f"切屏/失焦 {len(tab_events)} 次（阈值≥{TAB_HIDDEN_REVIEW_THRESHOLD}），建议人工核对面试过程。",
            signal_count=len(tab_events),
            affects_score=False,
            for_human_review=True,
        ))
    elif len(tab_events) > 0:
        items.append(ProctorRiskItem(
            code="tab_switch_noted",
            severity="hint",
            message=f"记录到切屏/失焦 {len(tab_events)} 次，仅提示，不参与评分。",
            signal_count=len(tab_events),
            affects_score=False,
            for_human_review=False,
        ))

    fast = [
        row for row in logs
        if str(row.get("signalType")) == "answer_latency"
        and _payload_number(row, "latencyMs") is not None
        and float(_payload_number(row, "latencyMs") or 0) < ANSWER_LATENCY_FAST_MS
    ]
    if fast:
        items.append(ProctorRiskItem(
            code="answer_too_fast",
            severity="review",
            message=f"有 {len(fast)} 次作答启动快于 {ANSWER_LATENCY_FAST_MS}ms，可能为预写/念稿，供人工复核。",
            signal_count=len(fast),
            affects_score=False,
            for_human_review=True,
        ))

    silence = [
        row for row in logs
        if str(row.get("signalType")) == "silence_ratio"
        and (_payload_number(row, "ratio") or 0) >= SILENCE_RATIO_HINT
    ]
    if silence:
        items.append(ProctorRiskItem(
            code="high_silence_ratio",
            severity="hint",
            message=f"音频静音比例偏高（≥{SILENCE_RATIO_HINT:.0%}）{len(silence)} 次，仅提示环境/设备问题。",
            signal_count=len(silence),
            affects_score=False,
            for_human_review=False,
        ))

    spikes = [
        row for row in logs
        if str(row.get("signalType")) == "volume_spike"
        and (_payload_number(row, "rmsDelta") or 0) >= VOLUME_SPIKE_RMS_DELTA
    ]
    if spikes:
        items.append(ProctorRiskItem(
            code="volume_spike",
            severity="hint",
            message=f"记录到音量变化偏大 {len(spikes)} 次，可能为环境噪声或设备切换，仅供人工参考。",
            signal_count=len(spikes),
            affects_score=False,
            for_human_review=False,
        ))

    # Contradiction detection intentionally deferred (LLM cost / false positives).
    return items


def _payload_number(row: Object, key: str) -> float | None:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
