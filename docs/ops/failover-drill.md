# 单供应商故障自动切换演练（Task 8a）

对齐架构 **§3.3 AI 能力网关** 与 Task 5 Gateway：主 LLM/ASR/TTS 故障时不得卡住对话。

## 目标

| 故障面 | 期望降级 |
| --- | --- |
| LLM 决策超时 / 抛错 / 熔断打开 | `rule_next_question`（按题序下一题），`source` ∈ `timeout_fallback` / `error_fallback` / `circuit_fallback` |
| ASR 不可用 / 熔断 | `SPEECH_UNAVAILABLE`，可改文字继续 |
| TTS 不可用 / 熔断 | `SPEECH_UNAVAILABLE` 或跳过播报，题目文字仍可达 |

## 本地手工步骤（fake）

1. `LLM_PROVIDER=fake` 起 API（compose 或 `uvicorn`）。
2. 在测试/临时注入中让 primary `decide` 抛错或 `elapsed_sec > timeout_sec`（见下方 pytest）。
3. 确认返回规则下一题，且对话可继续 `answer`。
4. 对 ASR：将 Gateway ASR 设为失败实现，调用转写应得到 `SPEECH_UNAVAILABLE`，文字通道仍可用。

## 自动化

```powershell
$py = '.\.venv-clean\Scripts\python.exe'
$env:PYTHONPATH = 'apps/api'
& $py -m pytest -c apps/api/pyproject.toml apps/api/tests/test_failover_drill.py -q
```

用例覆盖：LLM error/timeout/circuit → rule fallback；ASR/TTS → `SPEECH_UNAVAILABLE`。

## 生产注意

- 演练勿指向真实候选人场次；使用合成账号与 `LLM_PROVIDER=fake` 或显式获准的 staging。
- 熔断阈值见 `CircuitBreaker`；冷却期间所有请求走 fallback，恢复后半开探测。
- 本演练不替代多供应商真实路由（若仅配置单一 internal 端点，降级到规则/不可用提示即可满足「不卡死」）。
