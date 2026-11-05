import importlib.util
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from interviewer import stt_service
from interviewer.errors import DomainError
from interviewer.llm_service import FAKE_QUESTIONS, OPENING_MESSAGE, SYSTEM_PROMPT, ChatConfig, ChatMessage, LLMService


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


def run_cli(
    monkeypatch: pytest.MonkeyPatch, answers: list[str], build_service: Callable[[ChatConfig], LLMService] | None = None,
) -> None:
    path = Path(__file__).resolve().parents[3] / "scripts" / "voice_interviewer.py"
    spec = importlib.util.spec_from_file_location("voice_interviewer_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if build_service is not None:
        monkeypatch.setattr("interviewer.llm_service.LLMService", build_service)
        monkeypatch.setattr(ChatConfig, "from_env", lambda **_kwargs: ChatConfig(provider="internal", base_url="http://127.0.0.1:9000/v1"))
    monkeypatch.setattr("sys.argv", [str(path), "--real" if build_service is not None else "--fake"])
    values = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(values))
    module.main()


def test_voice_cli_uses_generated_opening_and_shared_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    audio = tmp_path / "demo audio.wav"
    audio.touch()
    invalid = tmp_path / "unsupported.wav"
    invalid.touch()
    transcript = "我负责合成项目的数据缓存"
    typed = "我对 /api 做了合成压测"
    replies = ("你好，我是AI面试官。你参与过哪个技术项目？", "缓存失效时你如何保证一致性？", "你用哪个指标衡量压测结果？")
    requests: list[list[ChatMessage]] = []

    def transcribe(path: str) -> str:
        if Path(path) == invalid:
            raise DomainError("SPEECH_UNAVAILABLE", "格式无效")
        assert Path(path) == audio
        return transcript

    def respond(request: httpx.Request) -> httpx.Response:
        index = len(requests)
        requests.append(ChatRequest.model_validate_json(request.content).messages)
        return httpx.Response(200, json={"choices": [{"message": {"content": replies[index]}, "finish_reason": "stop"}]})

    monkeypatch.setattr(stt_service, "transcribe_audio", transcribe)
    run_cli(monkeypatch, ["yes", str(invalid), "missing.wav", r"\\host\share\audio.wav", f'"{audio}"', typed, "/exit"],
            lambda config: LLMService(config, httpx.MockTransport(respond)))

    output = capsys.readouterr().out
    assert "转写未完成" in output and "未找到音频文件" in output and "网络共享路径不受支持" in output
    assert output.count("【候选人语音识别】") == 1 and f"【候选人语音识别】{transcript}" in output
    assert output.count("【面试官】") == 3
    for reply in replies:
        assert f"【面试官】{reply}" in output
    assert len(requests) == 3
    assert "还没有候选人回答" in requests[0][0].content
    assert [message.role for message in requests[2]] == ["system", "assistant", "user", "assistant", "user"]
    assert requests[2][0].content == SYSTEM_PROMPT and requests[2][1].content == replies[0]
    assert requests[2][:3] == requests[1]
    assert transcript in requests[2][2].content and typed in requests[2][4].content
    assert "<<<CANDIDATE_DATA_JSON>>>" in requests[2][2].content and "<<<CANDIDATE_DATA_JSON>>>" in requests[2][4].content


def test_voice_cli_waits_for_consent(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run_cli(monkeypatch, ["no"], lambda _config: pytest.fail("must wait for consent before creating a session"))
    output = capsys.readouterr().out
    assert "cli-voice-v1" in output and "未开始面试" in output
    assert "【面试官】" not in output


def test_voice_cli_fake_uses_local_opening_and_two_turns_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    audio = tmp_path / "demo.wav"
    audio.touch()
    audio_calls: list[Path] = []

    def transcribe(path: str) -> str:
        audio_calls.append(Path(path))
        return "合成语音回答"

    monkeypatch.setattr(stt_service, "transcribe_audio", transcribe)
    monkeypatch.setattr("interviewer.llm_service.ROOT", tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "internal")
    monkeypatch.setattr(httpx.Client, "send", lambda *_args, **_kwargs: pytest.fail("fake must not send HTTP"))
    run_cli(monkeypatch, ["yes", "答" * 4800, str(audio), "答" * 4000, "/exit"])

    output = capsys.readouterr().out
    assert audio_calls == [audio]
    assert "【候选人语音识别】合成语音回答" in output
    assert "本机 fake 演示，文字不出本机；音频由本地 Whisper 转写" in output
    assert "真实模式将文字发送" not in output
    assert "本次回答 4800 字，超过 4000 字上限，请分两段作答" in output
    assert "对话消息结构无效" not in output
    assert [line for line in output.splitlines() if line.startswith("【面试官】")] == [
        f"【面试官】{question}" for question in (OPENING_MESSAGE, *FAKE_QUESTIONS[:2])
    ]
