# 本地Whisper接入（阶段2增量，非完整验收）

2026-11-04。保留所有既有断言和默认演示链路。新增本地权重适配器、启动预加载、超时/并发保护、配置及11项离线测试；未改变数据库模式和既有迁移。

## 实跑结果

在fake LLM、STT_PROVIDER=auto、清空HTTP STT配置、禁用Next遥测环境中执行：

```powershell
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

实际输出摘要：

```text
All checks passed!
Success: no issues found in 21 source files
Test Files 17 passed (17)
Tests 239 passed (239)
collected 103 items
95 passed, 8 skipped, 1 warning in 17.44s
Compiled successfully in 4.2s
Generating static pages (5/5)
```

与本轮已实跑的阶段1基线比较：Vitest239→239；pytest收集92→103，通过84→95，PG跳过8→8。没有减少测试。8项因未配置可丢弃PG16而跳过；FastAPI TestClient原有httpx弃用警告保留。使用本机缓存pnpm11.25.0，仓库声明仍为10.34.9，未下载包管理器。不是托管CI证明；本增量尚未重跑浏览器E2E。

## 权重准备

用户明确要求执行`whisper.load_model("base")`以取得权重，作为本次手工准备下载的授权，不扩展为启动时允许下载。现有仓库Python执行该调用实际失败：`ModuleNotFoundError: No module named 'whisper'`。随后从OpenAI Whisper源码列出的官方base地址直接下载，SHA-256验证后才激活文件：

- 忽略目录：`.data/models/whisper/base.pt`。
- 字节数：145262807。
- SHA-256：`ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e`。
- 来源：[Whisper官方模型清单](https://github.com/openai/whisper/blob/main/whisper/__init__.py)。

权重保留在 Git 忽略目录。本机 `.env` 已配置 `STT_PROVIDER=whisper`、`STT_MODEL_PATH` 和 `STT_MODEL_SHA256`。当前通过 `node scripts/python.mjs` 实际运行 `.venv311` 的 Python 3.11.9。旧 `.venv` 也保留了同版本的清单内可选依赖，包括 `openai-whisper==20250625`、CPU Torch `2.15.0+cpu` 和 `numpy==2.4.6`。两个环境的 NetworkX 版本分别为 3.6.1 和 3.7。可选依赖清单是 `apps/api/requirements-whisper.txt`，Python 3.11 另用 `apps/api/constraints-python311.txt`。

```powershell
node scripts/python.mjs --version
node scripts/python.mjs -c 'import sys; print(sys.executable)'
```

```text
Python 3.11.9
D:\work\ai_interviewer\.venv311\Scripts\python.exe
```

手工加载验收（未转写音频）：

```powershell
node scripts/python.mjs -m interviewer.voice_acceptance --whisper
```

历史加载记录显示 `ok=true`、`provider=local_whisper`、`model=base`、`device=cpu`，`weightsSha256` 与官方 base 一致，`durationMs≈6640`。证据在忽略目录 `.data/acceptance/voice/`。后续已用授权合成 WAV 完成本地转写，CER 仍待验收。

## 中文输出风格限制

未设 `initial_prompt` 时，Whisper base 模型可能输出繁体。可在根目录 `.env` 配置 `STT_INITIAL_PROMPT="以下是普通话技术面试回答，请使用简体中文和简体标点。"`。空值省略该参数。非空提示仅引导转写风格，模型仍可能输出繁体。

R-voice-01 使用 `node scripts/python.mjs scripts/voice_interviewer.py --fake` 和同一段授权 WAV 复跑。空提示输出繁体，配置示例提示后该段输出简体，标点仍有差异。两次均使用本机 Whisper。

## 未通过项

真实10段中文样本/CER、口音/静音质量、partial、持久化分片与杀进程补发、ASR/LLM共载GPU观测均未执行。现有HTTP转写预览TTL仍在内存，不声称满足阶段2持久恢复验收。后续PG16/Docker与模型校准保持必做。Edge在线播报另受此前禁外网规则限制，尚无用户例外确认，未发实际请求。
