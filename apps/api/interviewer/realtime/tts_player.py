"""Server-side TTS chunk queue with cancel for barge-in (Task 6b)."""
from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from interviewer.realtime.protocol import TtsChunkMessage

SendFn = Callable[[object], Awaitable[None]]

# ~40 ms of PCM16LE @ 16 kHz mono per chunk when synthesizing raw PCM; WAV is sent as whole then sliced.
DEFAULT_CHUNK_BYTES = 1280


@dataclass
class TtsPlayer:
    send: SendFn
    chunk_bytes: int = DEFAULT_CHUNK_BYTES
    chunk_delay_ms: float = 0.0
    _queue: asyncio.Queue[bytes | None] = field(default_factory=asyncio.Queue)
    _seq: int = 0
    _generation: int = 0
    _pump_task: asyncio.Task[None] | None = None
    playing: bool = False

    @property
    def generation(self) -> int:
        return self._generation

    def bump_generation(self, generation: int) -> None:
        """Align cancel generation with pipeline (barge-in / supersede)."""
        self._generation = generation

    def cancel(self) -> None:
        """Drop queued audio and stop the pump; client must clear its play queue on interrupted."""
        self._generation += 1
        self.playing = False
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
        self._pump_task = None
        self._seq = 0

    async def play(self, audio: bytes, *, generation: int) -> None:
        """Enqueue audio for chunked tts_chunk delivery; no-op if generation already cancelled."""
        if generation < self._generation:
            return
        self._generation = generation
        self.playing = True
        self._seq = 0
        offset = 0
        while offset < len(audio):
            piece = audio[offset : offset + self.chunk_bytes]
            offset += len(piece)
            await self._queue.put(piece)
        await self._queue.put(None)
        self._pump_task = asyncio.create_task(self._pump(generation))
        try:
            await self._pump_task
        except asyncio.CancelledError:
            return

    async def _pump(self, generation: int) -> None:
        try:
            while True:
                if generation != self._generation:
                    return
                item = await self._queue.get()
                if item is None:
                    self.playing = False
                    return
                if generation != self._generation:
                    return
                encoded = base64.b64encode(item).decode("ascii")
                await self.send(TtsChunkMessage(seq=self._seq, audioBase64=encoded))
                self._seq += 1
                if self.chunk_delay_ms > 0:
                    await asyncio.sleep(self.chunk_delay_ms / 1000.0)
        except asyncio.CancelledError:
            self.playing = False
            raise
