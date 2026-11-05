# Edge TTS接入：默认关闭，真实调用未验收

2026-11-04。仅继续当前语音任务；没有推进模型评分校准或PG部署阶段。

## 文件与行为

- `apps/api/interviewer/tts.py`：显式外网开关、固定版本库适配、流式音频组装、超时、并发、输出上限、当前题目双重校验。
- `settings.py`、`.env.example`：TTS_PROVIDER/ALLOW_EXTERNAL/VOICE/RATE/TIMEOUT/CONNECT_TIMEOUT/MAX_CONCURRENCY。
- `service.py`：版本化Edge知情说明与状态字段；`main.py`：鉴权的当前题目音频GET接口。
- `apps/web/lib/question-audio.ts`、`use-interview-speech.ts`、`candidate-interview.tsx`：同源获取MP3、播放/打断、停止时释放URL与请求；Zod状态边界在`packages/core/src/transport.ts`。
- `apps/api/requirements-edge.txt`：可选`edge-tts==7.3.1`；用于实际协议调用，默认环境不需要，尚未安装。不是完整传递依赖wheel锁。
- `voice_acceptance.py`：显式手工本地加载/固定句公网测试，CI不调用。
- 新增Python/TS测试与E2E用例；Playwright/隔离生产脚本强制关闭真实语音provider；`docs/openapi.json`重新导出33路径。

## 许可与环境边界

[Edge项目官方说明](https://github.com/rany2/edge-tts)明确使用在线Microsoft服务。运行时外网限制仍有效，用户尚未确认例外。Edge TTS 依赖尚未安装，也未发出真实 Edge 请求。`TTS_PROVIDER=edge` 且许可标志为 false 时直接启动失败。获准后仍需准备锁定依赖的离线 wheel 集合及外网策略。

Whisper base.pt 已按用户要求下载并校验。当前通过 `.venv311` 的 Python 3.11.9 运行，已完成本地加载和授权合成 WAV 转写，CER 与 GPU 共载仍待验收。Edge 默认关闭。详见[本地 Whisper 接入](本地Whisper接入.md)。

## 验证结果

精确命令：

```powershell
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm test:e2e
node scripts/python.mjs -m interviewer.cli openapi
node scripts/python.mjs -m ruff check --config apps/api/pyproject.toml apps/api
node scripts/python.mjs -m mypy --config-file apps/api/pyproject.toml apps/api/interviewer
node scripts/python.mjs -m interviewer.voice_acceptance --help
```

测试环境显式fake LLM、STT_PROVIDER=auto、清空STT地址/模型、TTS_PROVIDER=local、TTS_ALLOW_EXTERNAL=false、关闭Next遥测，使用缓存pnpm11.25.0（声明版本10.34.9未下载）。浏览器在隔离3101/8101和独立SQLite运行，全部合成媒体，不控制真实设备。

实际输出摘要：

```text
All checks passed!
Success: no issues found in 23 source files
Test Files 18 passed (18)
Tests 243 passed (243)
collected 118 items
110 passed, 8 skipped, 1 warning in 26.87s
Compiled successfully in 4.7s
Generating static pages (5/5)
16 passed (4.1m)
{"paths": 33}
```

23源文件结果是手工验收脚本加入后的补充mypy；四项流水线中的初次mypy为22文件，均通过。帮助命令只打印参数，不加载真实库、不发请求。

本阶段1实际基线→当前：Vitest239→243；pytest收集92→118、通过84→110、PG跳过8→8；浏览器15→16，全部通过。Edge增量相对Whisper提交新增15项Python、4项TS和1项E2E。8项跳过仍是缺少明确PG16测试库，没有新增跳过或删除/放宽旧断言。保留原FastAPI/httpx弃用警告。没有托管CI、真实Edge、真实Whisper转写、PG16/Docker或CER通过声明。

## 未解决与下一步

Whisper 后续仍需完成阶段 2 的 10 段样本 CER 与持久续传。Edge 固定句验收待外网例外确认与离线 wheel 集合。阶段 3–5 仍待各自验收。
