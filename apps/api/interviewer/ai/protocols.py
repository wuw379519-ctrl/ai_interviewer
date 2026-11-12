"""Shared AI provider protocols. Sync shapes match the existing runtime (architecture §3.3 async forms are reserved for Task 6 streaming)."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, TypeVar

from interviewer.contracts import Contract, Object, SpeechOutput
from interviewer.provider import Generation

T = TypeVar("T", bound=Contract)


class LLMProvider(Protocol):
    name: str
    model: str

    def structured(self, operation: str, messages: list[dict[str, str]], schema: type[T],
                   fixture: Object) -> Generation[T]: ...

    def stream(self, text: str) -> Iterator[str]: ...

    def usage(self, prompt: int, completion: int) -> Object: ...


class ASRProvider(Protocol):
    name: str

    def transcribe(self, content: bytes) -> SpeechOutput: ...

    def load(self) -> object: ...

    def close(self) -> None: ...


class TTSProvider(Protocol):
    name: str

    def prepare(self) -> None: ...

    async def synthesize(self, text: str) -> bytes: ...
