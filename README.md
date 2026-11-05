# 研究生校招 AI 面试官 · Python 版

FastAPI 后端和终端面试工具，可运行结构化面试、证据评分、报告、人工改分、审计和数据删除。使用 Python 3.11+，默认用 SQLite 和 fake 模型。API 和 CLI 可独立运行。招聘者工作台、候选人网页、摄像头界面和报告打印页可通过单独启动的网页客户端使用。

## 准备 Python 3.11 环境

首次使用或换机器时，在仓库根目录运行。`$python311` 填本机 Python 3.11 解释器的实际位置，以下示例使用 Python.org 的默认用户安装路径。

```powershell
$python311 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
& $python311 --version
& $python311 -m venv .venv-clean
$py = '.\.venv-clean\Scripts\python.exe'
& $py -m pip install --index-url https://pypi.org/simple -r apps/api/requirements.lock -r apps/api/requirements-whisper.txt -c apps/api/constraints-python311.txt
& $py -m pip check
```

推荐使用 `.venv-clean`，它的第三方包独立安装。已有的 `.venv` 可作本机回退，使用时将 `$py` 改为 `'.\.venv\Scripts\python.exe'`。旧环境继承本机全局包，换机器时用上面的命令重建环境。后端和文字 CLI 只需要安装 `requirements.lock`，其中已包含检查工具。

离线安装时，在可联网且 Python 版本、系统和架构相同的机器上，用 `python -m pip wheel --wheel-dir <wheel目录>` 加上同样的 `-r` 和 `-c` 参数备齐 wheel，其中包括从固定源码版本构建的 Whisper wheel。将目录复制到目标机器，用 `& $py -m pip install --no-index --find-links <wheel目录>` 加上同样的 `-r` 和 `-c` 参数安装。语音权重和 FFmpeg 按下文单独放置。

## 在本机启动

以下命令在本目录运行，使用前面创建的 Python 3.11 环境。

```powershell
$py = '.\.venv-clean\Scripts\python.exe'
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

## 文本与本地音频面试

```powershell
& $py scripts/test_chat.py --fake
& $py scripts/voice_interviewer.py --fake
```

输入 `yes` 同意后开始，输入 `/exit` 退出。每轮最多 4000 字。语音脚本也接受本地音频路径，使用 `STT_MODEL_PATH` 指定已有 `base.pt`。其他音频编码可用 `FFMPEG_PATH` 指定现有 FFmpeg。可选语音依赖见 `apps/api/requirements-whisper.txt`；Python 3.11 额外应用 `apps/api/constraints-python311.txt`。`STT_INITIAL_PROMPT` 可以提示模型偏向简体。`--real` 仅用于明确获准的模型端点，模型参数见 `.env.example`。

### 本机练习 API

开发模式下，`GET /api/interview/chat` 返回知情说明和版本。客户端生成 32 字节随机值并编码为小写十六进制，作为 `Authorization: Bearer <值>`。使用该凭证向 `PUT /api/interview/session` 提交 `{"accepted":true,"consent_version":"<当前版本>"}`。后续请求使用同一凭证。

`POST /api/interview/chat` 接受 `multipart/form-data`。每次提供 `text` 或 `file`，并可带 `Idempotency-Key`。返回 `user_text` 与 `ai_reply`。文字最多 4000 字。音频需启用本地 Whisper，上传上限 16 MiB，解码后最多 120 秒。`GET /api/interview/session` 读取已保存的历史，`DELETE /api/interview/session` 删除会话。浏览器来源限定为 `http://localhost:5173`。

### 本地语音资产

音频模式需要可用的本地 Whisper 环境和权重。权重与 FFmpeg 都放在本仓库内，仓库外不需要任何文件。按下列目录放置（两者都被 Git 忽略，不会提交）：

| 文件 | 位置 | 来源 |
| --- | --- | --- |
| Whisper 权重 | `.data/models/whisper/base.pt` | 复用已有 `base.pt`，或按 openai-whisper 官方说明离线获取 |
| FFmpeg | `.data/tools/ffmpeg.exe` | 复用已有 `ffmpeg.exe`，或把任意 FFmpeg 放进该路径 |

```powershell
New-Item -ItemType Directory -Force -Path .data\models\whisper, .data\tools | Out-Null
Copy-Item <已有 base.pt> .data\models\whisper\base.pt
Copy-Item <已有 ffmpeg.exe> .data\tools\ffmpeg.exe
```

首次配置时从 `.env.example` 创建 `.env`。两个语音资产的相对路径均按仓库根解析，也可填写绝对路径或用 `~` 指向用户主目录。从其他目录启动时，将 `PYTHONPATH` 指向本仓库 `apps/api` 的绝对路径。

```dotenv
STT_PROVIDER=whisper
STT_MODEL=base
STT_DEVICE=cpu
STT_LANGUAGE=zh
STT_MODEL_PATH=.data/models/whisper/base.pt
STT_MODEL_SHA256=ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e
FFMPEG_PATH=.data/tools/ffmpeg.exe
```

`STT_MODEL_SHA256` 可选，配置后启动时校验权重；不匹配会拒绝加载而不是自动下载。不需要本地语音时设 `STT_PROVIDER=auto` 并留空这两个路径即可，其余功能不受影响。`.env` 由 Git 忽略。注入 `STT_MODEL_PATH` 和 `FFMPEG_PATH` 后的本地 Whisper 转写实测见 [R-python-01](docs/acceptance/R-python-01.md)。

### 网页语音联调

在独立仓库启动 FastAPI，在原仓库启动 Next.js 网页。后端的 `APP_BASE_URL` 填浏览器实际访问的 origin，网页服务端的 `PYTHON_API_URL` 指向 FastAPI。使用 `LLM_PROVIDER=fake`、`STT_PROVIDER=whisper` 和 `TTS_PROVIDER=local`，从演示工作台创建语音邀请。候选页同意并授权麦克风后，点击开始和结束语音输入，核对草稿后再发送。题目播报需要浏览器可用的本地中文音色。

已用本机 Python 3.11.9、Chromium 合成设备轨道和真实 Whisper base 跑通录音、转写、确认后提交、刷新恢复、评分报告及人工复核。物理麦克风、摄像头和实际播报声音需在使用设备上复测。详见 [D52](DECISIONS.md#d52-独立后端的网页语音联调)。

## Python 验证

```powershell
& $py -m ruff check --config apps/api/pyproject.toml apps/api scripts
& $py -m mypy --config-file apps/api/pyproject.toml apps/api/interviewer scripts
& $py -m pytest -c apps/api/pyproject.toml apps/api/tests
& $py -m interviewer.cli evals
```

PostgreSQL 测试需要明确指定可丢弃的 `TEST_DATABASE_URL`。Python 服务镜像配置位于 `apps/api/Dockerfile`，本机运行可直接使用上述 Uvicorn 命令。
