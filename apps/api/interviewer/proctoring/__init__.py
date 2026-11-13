"""Proctoring signals and risk rules (Task 7 / 9b). Risks never auto hire/reject."""
from __future__ import annotations

from .scorer import ProctorRiskItem, score_proctor_risks
from .signals import SIGNAL_TYPES, append_proctor_log, list_proctor_logs
from .vision import FakeVisionDetector, VisionDetector, VisionObservation, default_vision_detector

__all__ = [
    "SIGNAL_TYPES",
    "FakeVisionDetector",
    "ProctorRiskItem",
    "VisionDetector",
    "VisionObservation",
    "append_proctor_log",
    "default_vision_detector",
    "list_proctor_logs",
    "score_proctor_risks",
]
