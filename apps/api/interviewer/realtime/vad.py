"""Energy-threshold VAD for barge-in (Task 6b).

Chosen over Whisper: Whisper is ASR, not endpointing; tests/CI forbid real STT;
RMS threshold is deterministic and meets the 200ms barge-in budget.
"""
from __future__ import annotations

import array
import math
from dataclasses import dataclass


@dataclass
class VadConfig:
    """PCM16LE mono @ 16 kHz."""

    sample_rate: int = 16_000
    # Absolute RMS of int16 samples; ~500 ≈ quiet room speech onset for synthetic tones.
    energy_threshold: float = 500.0
    onset_ms: int = 80
    hangover_ms: int = 200


@dataclass
class VadDecision:
    speech_active: bool
    just_started: bool
    rms: float


class EnergyVad:
    """Push PCM frames; report speech onset for barge-in."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self._speech_active = False
        self._above_ms = 0.0
        self._below_ms = 0.0

    def reset(self) -> None:
        self._speech_active = False
        self._above_ms = 0.0
        self._below_ms = 0.0

    def push(self, pcm16le: bytes) -> VadDecision:
        if len(pcm16le) < 2:
            return VadDecision(speech_active=self._speech_active, just_started=False, rms=0.0)
        # Truncate odd trailing byte.
        usable = pcm16le if len(pcm16le) % 2 == 0 else pcm16le[:-1]
        samples = array.array("h")
        samples.frombytes(usable)
        if not samples:
            return VadDecision(speech_active=self._speech_active, just_started=False, rms=0.0)
        mean_sq = sum(float(s) * float(s) for s in samples) / len(samples)
        rms = math.sqrt(mean_sq)
        frame_ms = 1000.0 * len(samples) / float(self.config.sample_rate)
        just_started = False
        if rms >= self.config.energy_threshold:
            self._above_ms += frame_ms
            self._below_ms = 0.0
            if not self._speech_active and self._above_ms >= self.config.onset_ms:
                self._speech_active = True
                just_started = True
        else:
            self._below_ms += frame_ms
            self._above_ms = 0.0
            if self._speech_active and self._below_ms >= self.config.hangover_ms:
                self._speech_active = False
        return VadDecision(speech_active=self._speech_active, just_started=just_started, rms=rms)
