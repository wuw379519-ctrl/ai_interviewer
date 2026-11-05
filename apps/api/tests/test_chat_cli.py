import importlib.util
from pathlib import Path

import pytest

from interviewer.llm_service import FAKE_QUESTIONS, ChatConfig


def run_cli(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    path = Path(__file__).resolve().parents[3] / "scripts" / "test_chat.py"
    spec = importlib.util.spec_from_file_location("manual_chat_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(ChatConfig, "from_env", lambda **_kwargs: ChatConfig())
    monkeypatch.setattr("sys.argv", [str(path), "--fake"])
    values = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(values))
    module.main()


def test_no_candidate_answers_collected_before_explicit_cli_consent(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run_cli(monkeypatch, ["no"])
    output = capsys.readouterr().out
    assert "未开始面试" in output
    assert "面试官：" not in output


def test_cli_preserves_loop_and_handles_empty_input_and_exit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run_cli(monkeypatch, ["yes", "", "我负责后端", "通过合成测试降低耗时30%", "/exit"])
    output = capsys.readouterr().out
    assert "fake 本地演示" in output and "请输入回答" in output
    assert output.count("面试官：") == 3


def test_text_cli_rejects_overlong_answer_and_accepts_limit(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run_cli(monkeypatch, ["yes", "答" * 4800, "答" * 4000, "/exit"])
    output = capsys.readouterr().out
    assert "本次回答 4800 字，超过 4000 字上限，请分两段作答" in output
    assert "对话消息结构无效" not in output
    assert output.count("面试官：") == 2
    assert f"面试官：{FAKE_QUESTIONS[0]}" in output
