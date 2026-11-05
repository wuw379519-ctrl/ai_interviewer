"""Explicit, interactive interviewer CLI; no real endpoint is used by CI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    sys.path.insert(0, str(ROOT / "apps/api"))
    from interviewer.errors import DomainError
    from interviewer.llm_service import MAX_CHAT_MESSAGE_CHARS, ChatConfig, InterviewConversation, LLMService, OPENING_MESSAGE

    parser = argparse.ArgumentParser(description="授权测试内容的终端面试练习；不保存对话，不生成分数。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fake", action="store_true", help="确定性本地演示，不调用模型端点")
    mode.add_argument("--real", action="store_true", help="明确使用已配置且获准的OpenAI兼容端点")
    args = parser.parse_args()
    try:
        config = ChatConfig.from_env(provider="fake" if args.fake else "internal" if args.real else None)
        conversation = InterviewConversation(LLMService(config))
    except (ValidationError, DomainError, httpx.InvalidURL):
        raise SystemExit("模型配置无效。请检查.env中的模型、地址、超时和外网许可；配置值未输出。") from None

    print("当前模式：" + ("fake 本地演示（没有调用真实模型）" if config.provider == "fake" else "真实OpenAI兼容端点"))
    print("知情说明 cli-chat-v1：由AI提问；真实模式会将文字发送到配置的模型服务，其保留政策由该服务决定。")
    print("本脚本仅在内存保留测试对话，不录音、不落盘；请只输入获授权的测试内容。/exit撤回本地测试并结束。")
    try:
        if input("输入 yes 明确同意开始，其他输入退出：").strip().lower() != "yes":
            print("未开始面试，未采集候选人回答。")
            return
        print("面试官：" + OPENING_MESSAGE)
        while True:
            answer = input("候选人（/exit退出）：").strip()
            if answer.lower() in {"/exit", "/quit", "exit", "quit", "退出"}:
                break
            if not answer:
                print("请输入回答，或输入 /exit 退出。")
                continue
            if len(answer) > MAX_CHAT_MESSAGE_CHARS:
                print(f"本次回答 {len(answer)} 字，超过 {MAX_CHAT_MESSAGE_CHARS} 字上限，请分两段作答")
                continue
            try:
                print("面试官：" + conversation.answer(answer))
            except DomainError as error:
                print("请求未完成：" + error.message)
                print("本轮未加入历史，可重新输入同一回答重试，或 /exit 结束。")
    except (EOFError, KeyboardInterrupt):
        print("\n测试已结束。")
    finally:
        conversation.messages.clear()


if __name__ == "__main__":
    main()
