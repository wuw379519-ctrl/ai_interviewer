# R-python-01 独立 Python 版验收

`docs/acceptance` 已恢复来源提交 `3c2c873` 的历史记录，其中的命令和证据属于原仓库。独立版的运行和验证使用本目录 README 的 Python 命令。

- FastAPI 迁移及 Python 3.11 兼容见[现状与差距](现状与差距.md)、[Python 3.11 兼容记录](Python311兼容.md)。
- 本地语音见[本地 Whisper 接入](本地Whisper接入.md)、[本地文件语音封装](本地文件语音封装.md)。
- LLM 文本问答见[文本闭环](LLM文本闭环.md)。
- R-voice-01 的单次 4000 字前置校验、`STT_INITIAL_PROMPT` 透传和 fake 模式说明沿用原实现，分别由 `test_chat_cli.py`、`test_local_whisper.py` 和 `test_voice_interviewer_cli.py` 验证。Whisper 的提示词可以引导简体风格，空提示时 base 模型可能输出繁体。

## 配置后的本地语音复跑

使用本机 Python 3.11.9，按 [README](../../README.md) 注入 `STT_MODEL_PATH`、`STT_MODEL_SHA256` 和 `FFMPEG_PATH` 后，本地 Whisper 转写通过。将同一段获授权的合成 WAV 在本机转为 22.05 kHz 单声道 PCM，交由语音 CLI 转为 Whisper 所用采样率。额外设置 `STT_INITIAL_PROMPT` 为简体提示。未更改已有 `.env` 或权重文件。

```powershell
$audio = 'D:/work/ai_interviewer/.data/acceptance/voice/authorized-synthetic-zh.wav'
$converted = Join-Path ([IO.Path]::GetTempPath()) ("synthetic-22050-{0}.wav" -f [guid]::NewGuid())
& $env:FFMPEG_PATH -nostdin -loglevel error -i $audio -ac 1 -ar 22050 -c:a pcm_s16le $converted
& $py -c 'import sys, wave; f=wave.open(sys.argv[1]); print(f"Fixture {f.getframerate()} Hz / {f.getnchannels()} channel / PCM")' $converted
@('yes', ('答' * 4800), $converted, '我用对照实验验证了实现效果。', '/exit') | & $py scripts/voice_interviewer.py --fake
```

实际输出摘录：

```text
Fixture 22050 Hz / 1 channel / PCM
本机 fake 演示，文字不出本机；音频由本地 Whisper 转写。
本次回答 4800 字，超过 4000 字上限，请分两段作答
【候选人语音识别】你好,我负责研究项目的核心实现通过实验验证结果。
【面试官】这项实现中，你个人做出的关键技术决策是什么？
【面试官】你用什么测试或指标验证这个方案的效果？
```

## 独立版 Python 门禁

使用 README 中的三个 Python 门禁和离线评测。额外运行默认 Ruff 检查和独立 I001 检查。

```powershell
& $py -m ruff check --config apps/api/pyproject.toml apps/api scripts
& $py -m ruff check scripts/voice_interviewer.py
& $py -m ruff check --isolated --select I001 scripts/voice_interviewer.py
& $py -m mypy --config-file apps/api/pyproject.toml apps/api/interviewer scripts
& $py -m pytest -c apps/api/pyproject.toml apps/api/tests -rs
& $py -m interviewer.cli evals
```

```text
Python 3.11.9
All checks passed!
All checks passed!
All checks passed!
Success: no issues found in 29 source files
184 passed, 8 skipped in 25.04s
```

离线评测实际输出包含 `"transcripts": 24`、`"scoreRangeHits": 24`、`"evidenceCitationRate": 1.0` 和 `"injectionResisted": 10`。Python 通过数为 184 → 184，断言和跳过规则保持不变。未执行 `--real`，未提供 `TEST_DATABASE_URL`，8 项 PostgreSQL 测试按条件跳过。托管 CI 工作流已恢复，本记录仅代表本地执行结果。
