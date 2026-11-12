"""Rule-based interview fallbacks when LLM decision times out or the circuit is open."""
from __future__ import annotations

from collections.abc import Mapping


def rule_next_question(prompts_by_seq: Mapping[int, str], current_seq: int) -> str:
    """Pick the next plan prompt strictly by increasing seq; never block the dialogue."""
    upcoming = sorted(seq for seq in prompts_by_seq if seq > current_seq)
    if upcoming:
        return prompts_by_seq[upcoming[0]]
    if current_seq in prompts_by_seq:
        return prompts_by_seq[current_seq]
    if prompts_by_seq:
        return prompts_by_seq[min(prompts_by_seq)]
    return "本次面试到此结束，谢谢你的时间。后续结果由招聘者复核。"
