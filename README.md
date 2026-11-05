# 研究生校招 AI 面试官 · Python 版

FastAPI 后端和终端面试工具，可运行结构化面试、证据评分、报告、人工改分、审计和数据删除。使用 Python 3.11+，默认用 SQLite 和 fake 模型。此目录提供 API 和 CLI，原仓库保留招聘者工作台、候选人网页、摄像头界面和报告打印页。

## 在本机启动

以下命令在本目录运行。复用本机已就绪的 Python 3.11 环境。

```powershell
$py = 'D:\work\ai_interviewer\.venv311\Scripts\python.exe'
$env:PYTHONPATH = 'apps/api'
& $py --version
& $py -m interviewer.cli migrate
& $py -m interviewer.cli seed
& $py -m uvicorn interviewer.main:app --host 127.0.0.1 --port 8000
```

`seed` 只向空库写入合成数据。默认数据库为本目录的 `.data/python/interviews.sqlite3`。需要自定义配置时，将 `.env.example` 复制为 `.env` 后填写。本目录使用独立数据库和配置。

- 健康检查访问 `http://127.0.0.1:8000/api/health`，就绪检查访问 `http://127.0.0.1:8000/api/ready`。
- API 契约为 `http://127.0.0.1:8000/api/openapi.json`，可用 `python -m interviewer.cli openapi` 导出本地文件。浏览器直接调用 API 可用对应的 API 客户端，应用未启用依赖外部 CDN 的交互式文档。
- 开发模式可用 `POST /api/auth/login` 和空 JSON 对象建立合成演示会话。候选人 API 接受邀请返回的 `inviteToken` 作为 Bearer 令牌，回答前仍须明确同意。生产设置见 `.env.example`。
- 已有 PostgreSQL 16 时，填入 `DB_DRIVER=postgres` 和 `DATABASE_URL`，然后用同一迁移命令。已有脱敏快照可通过 `python -m interviewer.cli import-snapshot --file <文件>` 导入空库。

在其他机器可创建 Python 3.11 虚拟环境。离线准备好 wheel 目录后，使用 `python -m pip install --no-index --find-links <wheel目录> -r apps/api/requirements.lock`。

## 文本与本地音频面试

```powershell
& $py scripts/test_chat.py --fake
& $py scripts/voice_interviewer.py --fake
```

输入 `yes` 同意后开始，输入 `/exit` 退出。每轮最多 4000 字。语音脚本也接受本地音频路径，使用 `STT_MODEL_PATH` 指定已有 `base.pt`。其他音频编码可用 `FFMPEG_PATH` 指定现有 FFmpeg。可选语音依赖见 `apps/api/requirements-whisper.txt`；Python 3.11 额外应用 `apps/api/constraints-python311.txt`。`STT_INITIAL_PROMPT` 可以提示模型偏向简体。`--real` 仅用于明确获准的模型端点，模型参数见 `.env.example`。

## Python 验证

```powershell
& $py -m ruff check --config apps/api/pyproject.toml apps/api scripts
& $py -m mypy --config-file apps/api/pyproject.toml apps/api/interviewer scripts
& $py -m pytest -c apps/api/pyproject.toml apps/api/tests
& $py -m interviewer.cli evals
```

PostgreSQL 测试需要明确指定可丢弃的 `TEST_DATABASE_URL`。Python 服务镜像配置位于 `apps/api/Dockerfile`，本机运行可直接使用上述 Uvicorn 命令。
