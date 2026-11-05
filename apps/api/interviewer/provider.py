from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import Contract, Object
from .errors import DomainError
from .safety import guard_output
from .settings import Settings

T = TypeVar("T", bound=Contract)


@dataclass
class Generation(Generic[T]):
    data: T
    usage: Object


class LLMProvider(Protocol):
    name: str
    model: str

    def structured(self, operation: str, messages: list[dict[str, str]], schema: type[T],
                   fixture: Object) -> Generation[T]: ...

    def stream(self, text: str) -> Iterator[str]: ...


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)


class Completion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    class Message(BaseModel):
        model_config = ConfigDict(extra="ignore")
        content: str

    class Choice(BaseModel):
        model_config = ConfigDict(extra="ignore")
        message: Completion.Message

    choices: list[Choice] = Field(min_length=1)
    usage: TokenUsage = Field(default_factory=TokenUsage)


class Provider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.name = settings.provider
        self.model = "fixture-v1" if self.name == "fake" else settings.llm_model
        if self.name not in {"fake", "internal", "openai", "anthropic", "deepseek"}:
            raise DomainError("LLM_PROVIDER_UNAVAILABLE", "未支持的模型配置")
        if self.name != "fake" and not (settings.llm_base_url and settings.llm_model):
            raise DomainError("LLM_PROVIDER_UNAVAILABLE", "请配置模型网关地址与模型名称")

    def usage(self, prompt: int, completion: int) -> Object:
        cost = 0.0 if self.name == "fake" else ((prompt * (self.settings.input_price or 0) +
                                                completion * (self.settings.output_price or 0)) / 1000)
        return {"promptTokens": prompt, "completionTokens": completion, "totalTokens": prompt + completion,
                "estimatedCostUsd": cost}

    def structured(self, operation: str, messages: list[dict[str, str]], schema: type[T],
                   fixture: Object) -> Generation[T]:
        if self.name == "fake":
            data = schema.model_validate(fixture)
            guard_output(data.model_dump_json())
            return Generation(data, self.usage(math.ceil(sum(len(row["content"]) for row in messages) / 3),
                                               math.ceil(len(data.model_dump_json()) / 3)))
        prompt_tokens, completion_tokens = 0, 0
        for attempt in range(2):
            try:
                with httpx.Client(timeout=20, follow_redirects=False) as client:
                    response = client.post(self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                                           headers={"Authorization": f"Bearer {self.settings.llm_key}"} if self.settings.llm_key else {},
                                           json={"model": self.model, "messages": messages, "temperature": 0.1,
                                                 "response_format": {"type": "json_object"}, "max_tokens": 12000})
                    response.raise_for_status()
                    result = Completion.model_validate_json(response.content)
                prompt_tokens += result.usage.prompt_tokens
                completion_tokens += result.usage.completion_tokens
                content = guard_output(result.choices[0].message.content)
                if attempt:
                    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
                    first, last = content.find("{"), content.rfind("}")
                    if first >= 0 and last >= first:
                        content = content[first:last + 1]
                data = schema.model_validate_json(content)
                return Generation(data, self.usage(prompt_tokens, completion_tokens))
            except (httpx.HTTPError, ValidationError, DomainError):
                if attempt:
                    raise DomainError("LLM_STRUCTURED_OUTPUT_INVALID", f"{operation}结构化结果重试后仍未通过校验") from None
        raise DomainError("LLM_PROVIDER_UNAVAILABLE", "模型服务不可用")

    def stream(self, text: str) -> Iterator[str]:
        guard_output(text)
        for offset in range(0, len(text), 10):
            yield text[offset:offset + 10]
