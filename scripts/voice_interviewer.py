"""Manual local-audio and text interview, with in-memory conversation history."""
from __future__ import annotations

import argparse
import errno
import re
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".wma", ".aiff", ".amr"}


def local_audio_path(value: str) -> Path | None:
    """Return an existing file, None for text, or raise for an invalid file input."""
    unquoted = value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else value
    if unquoted.startswith(("//", "\\\\")) or re.fullmatch(r"[a-zA-Z][\w+.-]*://\S+", unquoted):
        raise ValueError("请使用本地音频文件，URL 和网络共享路径不受支持。")
    explicit_path = False
    try:
        path = Path(unquoted).expanduser()
        explicit_path = (bool(path.drive) or unquoted.startswith(("./", "../", ".\\", "..\\", "~/", "~\\"))
                         or path.suffix.lower() in AUDIO_SUFFIXES)
        if path.is_file():
            return path
        if path.is_dir() or explicit_path:
            raise ValueError("未找到音频文件，请检查路径，或直接输入文字回答。")
    except (OSError, RuntimeError) as error:
        if not explicit_path and (getattr(error, "errno", None) == errno.ENAMETOOLONG or getattr(error, "winerror", None) == 206):
            return None
        raise ValueError("无法读取该路径，请检查文件权限，或直接输入文字回答。") from None
    return None


def main() -> None:
    sys.path.insert(0, str(ROOT / "apps/api"))
    from interviewer.errors import DomainError
    from interviewer.llm_service import (
        MAX_CHAT_MESSAGE_CHARS,
        ChatConfig,
        InterviewConversation,
        LLMService,
    )
    from interviewer.stt_service import transcribe_audio

    parser = argparse.ArgumentParser(description="用本地音频文件或文字完成终端面试练习。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fake", action="store_true", help="使用本地演示模型（默认），音频仍由本地 Whisper 转写")
    mode.add_argument("--real", action="store_true", help="使用已配置且获准的 OpenAI 兼容端点")
    args = parser.parse_args()
    try:
        config = ChatConfig.from_env(provider="internal" if args.real else "fake")
    except (ValidationError, DomainError, httpx.InvalidURL):
        raise SystemExit("模型配置无效，请检查 .env 中的模型地址、模型名、超时和网络许可。") from None

    print("当前模式 " + ("真实模型端点" if args.real else "fake 本地演示"))
    print("知情说明 cli-voice-v1。由 AI 提问，音频在本机转写，脚本仅在内存保留对话。")
    if args.real:
        print("真实模式将文字发送至配置的模型服务，其保留政策由该服务决定。")
    else:
        print("本机 fake 演示，文字不出本机；音频由本地 Whisper 转写。")
    print("请使用获授权的测试内容，输入 /exit 可结束。")
    try:
        if input("输入 yes 明确同意开始，其他输入退出 > ").strip().lower() != "yes":
            print("未开始面试，未采集候选人回答。")
            return
        try:
            conversation = InterviewConversation(LLMService(config), generate_opening=True)
        except DomainError as error:
            raise SystemExit(f"面试开场失败。{error.message}") from None

        print(f"【面试官】{conversation.opening}")
        while True:
            value = input("请输入本地音频文件路径或文字回答（/exit 退出）> ").strip()
            if value.lower() == "/exit":
                return
            if not value:
                continue
            try:
                # Windows can reject long answers as oversized filenames before the answer check.
                audio = local_audio_path(value) if len(value) <= MAX_CHAT_MESSAGE_CHARS else None
            except ValueError as error:
                print(error)
                continue
            if audio is not None:
                try:
                    value = transcribe_audio(str(audio))
                except DomainError as error:
                    print(f"转写未完成。{error.message}。可重试或直接输入文字回答。")
                    continue
                except (OSError, ValidationError):
                    print("转写未完成，请检查音频文件权限和本地 STT 配置，或直接输入文字回答。")
                    continue
                print(f"【候选人语音识别】{value}")
            if len(value) > MAX_CHAT_MESSAGE_CHARS:
                print(f"本次回答 {len(value)} 字，超过 {MAX_CHAT_MESSAGE_CHARS} 字上限，请分两段作答")
                continue
            try:
                print(f"【面试官】{conversation.answer(value)}")
            except DomainError as error:
                print(f"本轮未加入对话。{error.message}。可重新输入回答或 /exit 结束。")
    except (EOFError, KeyboardInterrupt):
        print("\n测试已结束。")


if __name__ == "__main__":
    main()
