"""AI Gateway: routing, timeout fallback, circuit breaker, ai_usage metering, business import ban."""
from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import TypeVar

from sqlalchemy import select

from interviewer import database as db
from interviewer.ai.circuit import CircuitBreaker
from interviewer.ai.fallback import rule_next_question
from interviewer.ai.gateway import AIGateway, NullASR, NullTTS
from interviewer.contracts import Contract, Object
from interviewer.errors import DomainError
from interviewer.provider import Generation, Provider
from interviewer.settings import Settings

T = TypeVar("T", bound=Contract)

ROOT = Path(__file__).resolve().parents[3]
BUSINESS_DIRS = (
    ROOT / "apps" / "api" / "interviewer" / "service.py",
    ROOT / "apps" / "api" / "interviewer" / "assessment.py",
    ROOT / "apps" / "api" / "interviewer" / "speech.py",
    ROOT / "apps" / "api" / "interviewer" / "formal.py",
    ROOT / "apps" / "api" / "interviewer" / "governance.py",
    ROOT / "apps" / "api" / "interviewer" / "records.py",
    ROOT / "apps" / "api" / "interviewer" / "modules",
)

FORBIDDEN_MODULES = frozenset({
    "openai", "anthropic", "edge_tts", "whisper", "httpx",
})
FORBIDDEN_FROM = frozenset({
    ("interviewer.provider", "Provider"),
    ("interviewer.local_whisper", "LocalWhisper"),
    ("interviewer.tts", "EdgeTTS"),
    ("provider", "Provider"),
    ("local_whisper", "LocalWhisper"),
    ("tts", "EdgeTTS"),
})


def _under_type_checking(tree: ast.AST, node: ast.AST) -> bool:
    for parent in ast.walk(tree):
        if not isinstance(parent, ast.If):
            continue
        test = parent.test
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            for child in ast.walk(parent):
                if child is node:
                    return True
    return False


class CountingLLM:
    def __init__(self, name: str, *, fail: bool = False, reply: str = "下一题？") -> None:
        self.name = name
        self.model = f"{name}-model"
        self.calls = 0
        self.fail = fail
        self.reply = reply

    def usage(self, prompt: int, completion: int) -> Object:
        return {"promptTokens": prompt, "completionTokens": completion, "totalTokens": prompt + completion,
                "estimatedCostUsd": 0.0}

    def structured(self, operation: str, messages: list[dict[str, str]], schema: type[T],
                   fixture: Object) -> Generation[T]:
        self.calls += 1
        if self.fail:
            raise DomainError("LLM_PROVIDER_UNAVAILABLE", f"{self.name} failed")
        data = schema.model_validate(fixture)
        return Generation(data, self.usage(3, 3))

    def stream(self, text: str) -> Iterator[str]:
        self.calls += 1
        if self.fail:
            raise DomainError("LLM_PROVIDER_UNAVAILABLE", f"{self.name} failed")
        yield text


def _gateway(primary: CountingLLM, *, threshold: int = 3) -> AIGateway:
    settings = Settings(provider=primary.name)
    return AIGateway(
        settings,
        primary,
        NullASR(),
        NullTTS(),
        llm_circuit=CircuitBreaker(failure_threshold=threshold, cooldown_sec=60.0),
    )


def test_rule_next_question_follows_plan_order() -> None:
    prompts = {1: "一", 2: "二", 3: "三"}
    assert rule_next_question(prompts, 1) == "二"
    assert rule_next_question(prompts, 3) == "三"


def test_gateway_routes_to_configured_primary_provider() -> None:
    provider_a = CountingLLM("alpha")
    provider_b = CountingLLM("beta")
    gateway = _gateway(provider_a)

    def call_a() -> str:
        provider_a.calls += 1
        return provider_a.reply

    text, source = gateway.decide_next_question(
        {1: "一", 2: "二"}, 1, primary=call_a, elapsed_sec=0.1,
    )
    assert source == "primary"
    assert text == "下一题？"
    assert provider_a.calls == 1
    assert provider_b.calls == 0
    assert gateway.name == "alpha"

    def call_b() -> str:
        provider_b.calls += 1
        return "B题"

    gateway_b = _gateway(provider_b)
    assert gateway_b.name == "beta"
    gateway_b.decide_next_question({1: "一", 2: "二"}, 1, primary=call_b, elapsed_sec=0.0)
    assert provider_b.calls == 1
    assert provider_a.calls == 1


def test_llm_decision_timeout_uses_rule_fallback_without_calling_primary() -> None:
    primary = CountingLLM("slow")
    gateway = _gateway(primary)
    before = gateway.llm_primary_calls

    def call() -> str:
        primary.calls += 1
        return primary.reply

    text, source = gateway.decide_next_question(
        {1: "首题", 2: "下一题按序"},
        1,
        primary=call,
        elapsed_sec=3.5,
        timeout_sec=3.0,
    )
    assert source == "timeout_fallback"
    assert text == "下一题按序"
    assert primary.calls == 0
    assert gateway.llm_primary_calls == before


def test_llm_decision_error_falls_back_and_records_failure() -> None:
    primary = CountingLLM("broken", fail=True)
    gateway = _gateway(primary, threshold=5)

    def boom() -> str:
        primary.calls += 1
        raise DomainError("LLM_PROVIDER_UNAVAILABLE", "boom")

    text, source = gateway.decide_next_question({1: "A", 2: "B"}, 1, primary=boom, elapsed_sec=0.0)
    assert source == "error_fallback"
    assert text == "B"
    assert primary.calls == 1
    assert gateway.llm_circuit.failures == 1


def test_circuit_opens_and_blocks_further_primary_calls() -> None:
    primary = CountingLLM("flaky", fail=True)
    gateway = _gateway(primary, threshold=3)

    def boom() -> str:
        primary.calls += 1
        raise DomainError("LLM_PROVIDER_UNAVAILABLE", "fail")

    for _ in range(3):
        source = gateway.decide_next_question({1: "A", 2: "B"}, 1, primary=boom, elapsed_sec=0.0)[1]
        assert source == "error_fallback"
    assert primary.calls == 3
    assert gateway.llm_primary_calls == 3
    assert gateway.llm_circuit.is_open
    blocked = gateway.decide_next_question({1: "A", 2: "B"}, 1, primary=boom, elapsed_sec=0.0)
    assert blocked[1] == "circuit_fallback"
    assert primary.calls == 3
    assert gateway.llm_primary_calls == 3
    assert gateway.llm_circuit.calls_blocked >= 1


def test_fake_structured_writes_ai_usage(tmp_path: Path) -> None:
    path = tmp_path / "usage.sqlite3"
    database = db.Database(Settings(sqlite_path=str(path), provider="fake"))
    try:
        database.migrate()
        llm = Provider(Settings(provider="fake"))
        gateway = AIGateway(Settings(provider="fake"), llm, NullASR(), NullTTS())
        from interviewer.contracts import CompetencySet
        from interviewer.domain import fixture_competencies
        with database.unit_of_work() as connection:
            generation = gateway.structured(
                "competency_extraction",
                [{"role": "system", "content": "x" * 30}, {"role": "user", "content": "y" * 30}],
                CompetencySet,
                fixture_competencies(False).payload(),
            )
            gateway.meter(connection, "llm_tokens", float(int(str(generation.usage.get("totalTokens", 0) or 0))))
            rows = db.rows(connection, select(db.ai_usage).order_by(db.ai_usage.c.ts))
        assert len(rows) == 1
        assert str(rows[0]["provider"]) == "fake"
        assert str(rows[0]["kind"]) == "llm_tokens"
        assert float(str(rows[0]["amount"])) >= 0
    finally:
        database.close()


def test_business_modules_do_not_import_provider_sdks_or_concrete_providers() -> None:
    files: list[Path] = []
    for target in BUSINESS_DIRS:
        if target.is_file():
            files.append(target)
        else:
            files.extend(sorted(target.rglob("*.py")))
    offenders: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if _under_type_checking(tree, node):
                continue  # type-only imports OK; runtime business path must stay clean
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in FORBIDDEN_MODULES:
                        offenders.append(f"{path.relative_to(ROOT)}: import {alias.name}")
            else:
                module = node.module or ""
                root = module.split(".", 1)[0]
                if root in FORBIDDEN_MODULES:
                    offenders.append(f"{path.relative_to(ROOT)}: from {module} import ...")
                for alias in node.names:
                    if (module, alias.name) in FORBIDDEN_FROM:
                        offenders.append(f"{path.relative_to(ROOT)}: from {module} import {alias.name}")
    assert offenders == [], offenders
