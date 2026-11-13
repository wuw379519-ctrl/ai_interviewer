"""Lightweight vision observation for Task 9b — no heavy DL deps in CI."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VisionObservation:
    face_count: int
    source: str


class VisionDetector(Protocol):
    def observe(self, frame: bytes, *, image_format: str) -> VisionObservation:
        """Inspect one still frame; must not retain the bytes."""


class FakeVisionDetector:
    """Deterministic stub for tests/CI. Configure face_count per scenario."""

    def __init__(self, face_count: int = 1) -> None:
        self.face_count = face_count
        self.calls = 0
        self.last_format: str | None = None
        self.last_byte_len = 0

    def observe(self, frame: bytes, *, image_format: str) -> VisionObservation:
        self.calls += 1
        self.last_format = image_format
        self.last_byte_len = len(frame)
        return VisionObservation(face_count=max(0, int(self.face_count)), source="fake")


class OpenCvHaarVisionDetector:
    """Optional OpenCV Haar cascade — falls back to FakeVisionDetector if cv2 missing."""

    def __init__(self) -> None:
        self._fallback = FakeVisionDetector(face_count=1)
        self._cascade: object | None = None
        self._cv2: object | None = None
        try:
            import cv2

            path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            loaded = cv2.CascadeClassifier(path)
            if loaded.empty():
                self._cascade = None
            else:
                self._cascade = loaded
            self._cv2 = cv2
        except Exception:
            self._cascade = None
            self._cv2 = None

    def observe(self, frame: bytes, *, image_format: str) -> VisionObservation:
        cv2 = self._cv2
        cascade = self._cascade
        if cascade is None or cv2 is None:
            return self._fallback.observe(frame, image_format=image_format)
        import numpy as np

        array = np.frombuffer(frame, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)  # type: ignore[attr-defined]
        if image is None:
            return VisionObservation(face_count=0, source="opencv_haar")
        faces = cascade.detectMultiScale(image, scaleFactor=1.1, minNeighbors=4)  # type: ignore[attr-defined]
        count = int(len(faces))
        return VisionObservation(face_count=count, source="opencv_haar")


def default_vision_detector() -> VisionDetector:
    """Prefer OpenCV when available; otherwise Fake (CI / slim images)."""
    try:
        import cv2  # noqa: F401

        return OpenCvHaarVisionDetector()
    except Exception:
        return FakeVisionDetector(face_count=1)
