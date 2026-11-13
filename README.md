# 研究生校招 AI 面试官 · 视频语音多模态防作弊版

本仓库包含 Next.js 招聘工作台、FastAPI 后端和终端面试工具。FastAPI 负责结构化面试、实时视频/语音通道、证据评分、报告、人工改分、审计、数据删除，以及**视频语音多模态防作弊**（过程信号 + 轻量人脸检测 → `riskItems`，仅供人工复核）。默认用 SQLite 和 fake 模型；API 与 CLI 也可独立运行。

## 功能特性

- **结构化面试**：知情同意、固定/生成题单、追问与收尾、刷新可恢复当前题。
- **证据评分与报告**：逐题原话证据、人工改分与审计；AI 建议不自动录用/淘汰。
- **实时通道（WS）**：文字 / 音频分片 / 视频帧（JPEG≈5fps）→ ASR → 编排 → TTS；VAD 打断；断线重连顶替。
- **视频通话（Task 9a）**：`VideoInterviewRoom` 本机预览 + AI 主展示占位；摄像头权限拒绝 / 拔出有 UI 降级；约 10s 无帧服务端 `camera_stall` 通知。
- **多模态防作弊闭环（Task 9b）**：切屏/失焦/`camera_lost` + 音频静音/音量 + `VisionDetector` 人脸观察（`no_face` / `multi_face`）写入 `proctor_logs`，融合为报告 `riskItems`（`affectsScore=false`）。CI 用 `FakeVisionDetector`，不引入重度 DL，不长期存原始帧。
- **多租户与运维**：Postgres RLS、Celery 清理、Compose（postgres/redis/api/worker）、飞书接入骨架。

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
- 网页通过 `POST /api/auth/login` 提交 `username` 与 `password`。本地合成演示会话在显式启用演示模式后可用空 JSON 对象建立。候选人 API 接受邀请返回的 `inviteToken` 作为 Bearer 令牌，回答前仍须明确同意。
- 已有 PostgreSQL 16 时，填入 `DB_DRIVER=postgres` 和 `DATABASE_URL`，然后用同一迁移命令。已有脱敏快照可通过 `python -m interviewer.cli import-snapshot --file <文件>` 导入空库。
- **部署红线（RLS）**：生产 `DATABASE_URL` **必须**使用 `NOSUPERUSER NOBYPASSRLS` 角色，否则 Postgres RLS 静默失效（超级用户即便 `FORCE ROW LEVEL SECURITY` 也会绕过）。启动时会校验：`environment=production` 遇不安全角色 **拒绝启动**；非生产则 `/api/ready` 返回 `NOT_READY`（`POSTGRES_RLS_ROLE_BYPASS`）。Task 6 WebSocket 长连接前必须满足本条。详见 [D72](DECISIONS.md#d72-多租户与-rls)。
- 迁移双链：Postgres 为 `apps/api/migrations/postgres/0000`–`0016`；SQLite 为 `0001`–`0009`（含 `tenants` / `users` / `role_bindings`、业务表 `tenant_id`、`interview_events`、`ai_usage`、`proctor_logs`；PG `0014` 启用 RLS，`0015` 建 `proctor_logs`，`0016` 扩展视觉防作弊 `signal_type`；SQLite `0009` 同步重建 CHECK）。空库执行 `python -m interviewer.cli migrate` 一次即可建出与 PG 对齐的业务表、索引与同意/证据/枚举门禁。结构对等由 `apps/api/tests/test_schema_parity.py` 断言（有 `TEST_DATABASE_URL` 时同时跑 PG16；无则该用例 skip）。本机无可用 PG 时，降级验收为 SQLite 空库 migrate + 迁移 SQL 语法/清单检查 + PRAGMA 列与门禁比对；可复现的 disposable PG `initdb`/`pg_ctl` 命令见 [D70](DECISIONS.md#d70-事件溯源-interview_eventstask-3) / [D72](DECISIONS.md#d72-多租户与-rls)。

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

## 网页工作台

准备 Python 3.11+、Node 20.11+ 和 pnpm 10.34.9 后，在仓库根目录运行。

```powershell
pnpm install
pnpm dev
```

打开 [账号登录页](http://127.0.0.1:3000/login)。首次联合启动生成管理员 `admin` 和招聘者 `recruiter` 的随机密码，保存在 Git 忽略的 `.data/workspace-accounts.json`。在本机分别运行 `node scripts/dev.mjs --show-admin` 或 `node scripts/dev.mjs --show-recruiter` 查看账号与密码。管理员登录一次即可使用面试发起和管理功能。

FastAPI 默认使用 `127.0.0.1:8000`。端口已被占用时可运行 `node scripts/dev.mjs --web-port 3010 --api-port 8010`，打开 `http://127.0.0.1:3010/login`。按 `Ctrl+C` 停止两个进程。

浏览器通过同源 `/api/*` 调用 Next，Next 通过 `PYTHON_API_URL` 转发给 FastAPI。联合启动脚本自动设置转发目标和默认 `APP_BASE_URL`。如果自行指定 `APP_BASE_URL`，请让它与浏览器实际访问的 origin 一致。

### 飞书应用接入（骨架）

飞书凭证只写入 Python Settings（见 `.env.example` 中 `FEISHU_*`）。前端通过同源 `/api/feishu/status` 读取公开状态，**不在构建期读环境变量**，也不直连 `open.feishu.cn`。

| 路径 | 说明 |
| --- | --- |
| `apps/api/interviewer/feishu.py` | 飞书出网端口（Live/Fake）与 OAuth state / 事件解密 |
| `apps/web/integrations/feishu/` | 前端 JSAPI / 免登 / 后端桥接占位，可从 `@/integrations/feishu` 引用 |

### 后端目录（FastAPI）

- `apps/api/interviewer/main.py`：应用装配（lifespan、中间件、admit、异常处理、`include_router`、OpenAPI 元信息）
- `apps/api/interviewer/modules/`：按领域拆分的 HTTP 路由（纯装配，不改契约）
  - `operations/` 健康检查 · `auth/` 账号登录 · `feishu/` 飞书身份 · `jobs/` 岗位
  - `candidates/` 候选人录入 · `interviews/` 邀约与候选人作答 · `assessment/` 评分报告
  - `admin/` 治理与管理员记录 · `practice/` 本机练习对话（挂载 `PracticeChat`）
- 业务写入、评分与持久化仍在 `service.py` / `assessment.py` / `governance.py` 等既有模块；事件追加在 `events.py`；AI 出站统一经 `ai/gateway.py`；`modules/*/schemas.py` 仅再导出 `contracts`
- `interview_events`：append-only 事件表，唯一索引 `(interview_id, seq)`；应用层 `MAX(seq)+1` 单调递增，DB 唯一约束兜底
- `ai_usage`：AI 计量表（`tenant` 对齐 `tenants.id`；`kind` = `llm_tokens` / `asr_seconds` / `tts_chars`）；fake 模式也会写入估算量
- 多租户：`tenants` + `users` + `role_bindings`；业务表带可空 `tenant_id`（迁移回填 default）。租户由服务端鉴权解析（`get_current_tenant` / `Actor.tenant_id`），**不**由客户端传入。应用层查询强制按当前租户过滤，跨租户 → 404。Postgres 另以 RLS（`tenant_id = current_setting('app.tenant_id')`）双保险；`Database.transaction`（`apps/api/interviewer/database.py`）在每笔事务开始 `set_config('app.tenant_id', …, true)`（SET LOCAL）。生产角色红线见上文「部署红线（RLS）」。SQLite 无 RLS，依赖应用层过滤。详见 [D72](DECISIONS.md#d72-多租户与-rls)。
- 实时网关（Task 6b / 9a / 9b）：`WS /ws/interview/{session_id}`。`auth` → `avatar_ready` → 心跳 → `text_input`/`audio_chunk`/`video_chunk`+`end_turn` → ASR（Gateway）→ `service.turn`（幂等键写入 `idempotency_keys`，scope=`WS /turns`）→ `question` + `tts_chunk`。能量 VAD（`onset_ms=80` / `cooldown_ms=300`）打断：`interrupted(reason=vad_barge_in)`。`video_chunk`（JPEG/WebP base64，默认约 5fps）走独立背压环（元数据环长 8、丢最旧），**不**阻塞 ASR/TTS，观察后立即丢弃帧字节。连续约 10s 无帧 → `camera_stall` + `state_changed`。重连顶替 close `4000`，`resumeFromSeq` 重放，前端可重新初始化摄像头。推荐客户端音频分片 **100–200ms**（协议上限 1s）。**多 worker**：需 sticky session 或 Redis 外置 `SessionStore`（见 D76）。延迟边界见 [docs/acceptance/task6b-realtime-latency.md](docs/acceptance/task6b-realtime-latency.md)。前端 `VideoInterviewRoom`：本机预览 + AI 主展示占位；权限拒绝/拔摄像头有 UI 降级。决策 [D73](DECISIONS.md#d73-task-6a-gateway-protocol-保持双轨-casync-表面--sync-实现)/[D74](DECISIONS.md#d74-task-6a-每面试仅一个活动写-ws重连顶替旧连接)/[D75](DECISIONS.md#d75-task-6b-协议字段补齐text_input--audio_chunk)/[D76](DECISIONS.md#d76-task-6b实时-pipeline--vad--打断)/[D80](DECISIONS.md#d80-task-9a视频语音面试帧传输与前端渲染)/[D81](DECISIONS.md#d81-task-9b多模态防作弊与状态协同)。WS **不**进入 OpenAPI。
- 防作弊信号（Task 7 / 9b）：候选人端经 WS `proctor_signal` 上报切屏/失焦/答题延迟/`camera_lost`；服务端在**每题作答缓冲**上聚合派生静音比例与音量突变（非每 chunk），并在最新视频帧上做轻量人脸检测（`VisionDetector` / CI 用 `FakeVisionDetector`），写入 `proctor_logs`（含 `no_face`/`multi_face`/`camera_stall`/`camera_lost`；租户隔离 + PG RLS）。规则打分器产出报告 `riskItems`（`hint`/`review`，`affectsScore=false`），**不**进入评分证据链、**不**自动录用/淘汰。报告页「过程信号提示」仅供人工复核。详见 [D77](DECISIONS.md#d77-task-7-防作弊信号与-riskitems)/[D81](DECISIONS.md#d81-task-9b多模态防作弊与状态协同)。
- 运维栈（Task 8a/8b）：`infra/docker-compose.yml` 起 `postgres` + `redis` + `api` + `worker`（兼 beat）。API **healthcheck 走 `/api/ready`**。运行时 `DATABASE_URL` 用 `aii_app`（NOSUPERUSER NOBYPASSRLS）；迁移走 `MIGRATE_DATABASE_URL`（postgres）。Celery：`generate_report_task`（HTTP `/score` 仍同步为默认）；`run_retention_cleanup` **每小时**（UTC `minute=17`），默认 dry-run，`CELERY_CLEANUP_EXECUTE=true` 才删；清理覆盖到期面试及 `proctor_logs`。WS 多副本用 sticky（`infra/nginx/nginx.conf` `ip_hash`；**生产 sticky 方案待定**）；Redis SessionStore 为后续。故障演练见 [docs/ops/failover-drill.md](docs/ops/failover-drill.md)。决策 [D78](DECISIONS.md#d78-task-8a运维基础设施compose--celery--sticky-ws)/[D79](DECISIONS.md#d79-task-8b收尾备忘结论与索引)。

```powershell
# 结构门禁（无 Docker 也可）
python infra/compose.validate.py
# 在仓库根实起；勿提交真实 .env
docker compose -f infra/docker-compose.yml up --build -d
docker compose -f infra/docker-compose.yml ps
# 期望 api healthy（ready）；worker 运行中
```

**Compose 实起证据（已解决）**：GitHub Actions workflow **`Compose smoke`** 持续全绿（例：`271a7a1` 起、Task 9b `a718d60` 等）——migrate、`/api/ready`、worker 进程均通过。本地无 Docker 时仍以 `compose.validate.py` + 该 CI 工作流为验收依据。

**已知限制（Task 8a/8b / 9）**：Sticky 失效靠 `event_replay` 续场（可能丢未落库 turn）；跨 worker 双活靠 DB seq 唯一约束兜底（防撞号，不保证跨进程 turn 顺序）。`data_policies` 非 default 租户未做。能量 VAD 可能误触发。熔断为进程内。生产 sticky 方案待定。视频非 WebRTC、人脸检测为轻量/可打桩。详见 [D79](DECISIONS.md#d79-task-8b收尾备忘结论与索引)/[D81](DECISIONS.md#d81-task-9b多模态防作弊架构与-visiondetector-抽象)。

### 项目收尾摘要（Task 1–9）

**端点 / 协议（节选）**
- Task 3：`GET /api/admin/interviews/{id}/events`（`interview_events` 回放）
- Task 6 / 9a：`WS /ws/interview/{session_id}`（含 `video_chunk` / `avatar_ready`；**不进 OpenAPI**；paths 仍以 REST 计）
- Task 7 / 9b：报告 `riskItems`；WS `proctor_signal`（切屏 + `camera_lost` 等；无新 REST 端点）
- OpenAPI：`pnpm api:openapi` → `docs/openapi.json`（约 **44** paths）

**本地启动（摘要）**
```powershell
$py = '.\.venv-clean\Scripts\python.exe'
$env:PYTHONPATH = 'apps/api'
$env:LLM_PROVIDER = 'fake'
& $py -m interviewer.cli migrate
& $py -m interviewer.cli seed
# API  alone：
& $py -m uvicorn interviewer.main:app --host 127.0.0.1 --port 8000
# 或联合启动工作台：
$env:PYTHON_EXECUTABLE = (Resolve-Path '.\.venv-clean\Scripts\python.exe').Path
pnpm install
pnpm dev   # → http://127.0.0.1:3000/login
```

**测试 / 构建**
```powershell
$py = '.\.venv-clean\Scripts\python.exe'
$env:PYTHONPATH = 'apps/api'
$env:LLM_PROVIDER = 'fake'
$env:PYTHON_EXECUTABLE = (Resolve-Path '.\.venv-clean\Scripts\python.exe').Path
# Python 三门禁
& $py -m ruff check --config apps/api/pyproject.toml apps/api scripts
& $py -m mypy --config-file apps/api/pyproject.toml apps/api/interviewer scripts
& $py -m pytest -c apps/api/pyproject.toml apps/api/tests
# 前端 + 联合（含 vitest 与上述 pytest）
pnpm lint
pnpm typecheck
pnpm test
pnpm build
# 或一次跑齐：pnpm verify
pnpm api:openapi   # 覆盖 docs/openapi.json
```

**Docker Compose**
```powershell
python infra/compose.validate.py
docker compose -f infra/docker-compose.yml up --build -d
docker compose -f infra/docker-compose.yml ps
# 期望 api healthy（/api/ready）；worker 运行中
$env:CELERY_TASK_ALWAYS_EAGER='true'; $env:PYTHONPATH='apps/api'
& .\.venv-clean\Scripts\python.exe -c "from interviewer.workers.tasks_cleanup import run_retention_cleanup; print(run_retention_cleanup(dry_run=True))"
# failover：pytest apps/api/tests/test_failover_drill.py；说明见 docs/ops/failover-drill.md
```

**配置（新增/关键）**：`REDIS_URL`、`CELERY_TASK_ALWAYS_EAGER`、`CELERY_CLEANUP_EXECUTE`、`LLM_PROVIDER`（CI=`fake`）、`FEISHU_*` 占位、生产 `DATABASE_URL` 角色 **NOSUPERUSER NOBYPASSRLS**。

**迁移总览**：Postgres `0000`–`0016`；SQLite `0001`–`0009`（含 tenants、events、ai_usage、proctor_logs、视觉 signal_type、RLS）。

**决策索引**：文首全量 **D1–D81** 与交付阶段 **D67–D81** 见 [DECISIONS.md](DECISIONS.md)（Task 8b=D79，Task 9a=D80，Task 9b=D81 VisionDetector）。

### AI Gateway（配置）

| 环境变量 | 说明 |
| --- | --- |
| `LLM_PROVIDER` | 主 LLM 路由，测试/CI 必须为 `fake`；可选 `internal` 等（经 Gateway，业务不直连 SDK） |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | 非 fake 时的 OpenAI 兼容端点 |
| `STT_PROVIDER` | `auto` / `http` / `whisper`；失败时现有行为为返回 `SPEECH_UNAVAILABLE` 并建议改用文字（Gateway 纳入同一路径） |
| `TTS_PROVIDER` | `local`（不播报）/ `edge`（需 `TTS_ALLOW_EXTERNAL` + `TTS_VOICE`）；失败保留「请阅读题目文字」 |

LLM 决策超时阈值默认 3s：Gateway `decide_next_question` 在超时/熔断/错误时按题单 `seq` 顺序规则兜底，测试注入 `elapsed_sec`，不依赖真实 sleep。熔断为进程内失败计数 + 冷却窗口，见 [D71](DECISIONS.md#d71-ai-gateway-路由熔断降级与计量)。

### 飞书免登（后端骨架）

未配置时相关接口返回 `FEISHU_NOT_CONFIGURED`。`GET /api/feishu/status` 只返回公开字段；`POST /api/feishu/oauth/callback` 校验一次性 state 后按 open_id 白名单签发 `aii_recruiter` / `aii_admin` cookie。`POST /api/feishu/events` 支持 url_verification 与可选 Encrypt Key 解密。登录页本轮未接线，账号密码登录不变。

Python 解释器按 `.venv`、`.venv-clean`、`.venv311`、PATH 的顺序查找。可在终端设置 `$env:PYTHON_EXECUTABLE = (Resolve-Path '.\.venv-clean\Scripts\python.exe').Path` 显式使用隔离环境。`pnpm verify` 一次运行 TS 和 Python 门禁。Playwright 浏览器就绪后可用 `pnpm test:e2e` 单独运行浏览器套件。

### 正式文字面试

在仓库根目录启动正式面试网页。以下环境变量让本次运行使用 Python 3.11、fake 模型和文字流程。联合启动器会启动 FastAPI 和 Next.js。

```powershell
$env:PYTHON_EXECUTABLE = (Resolve-Path '.\.venv-clean\Scripts\python.exe').Path
$env:LLM_PROVIDER = 'fake'
$env:DEMO_MODE = 'false'
$env:STT_PROVIDER = 'auto'
$env:STT_BASE_URL = ''
$env:STT_MODEL = ''
$env:TTS_PROVIDER = 'local'
node scripts/dev.mjs
```

1. 打开 [正式面试发起页](http://127.0.0.1:3000/recruiter/formal)，登录招聘工作台，填写岗位和候选人信息、岗位 JD 与简历。系统自动使用固定题单。复制生成的候选人链接。
2. 用链接进入候选人页，阅读并明确同意后逐题作答。已提交的回答和当前题号会保存在服务端，刷新可继续。
3. 用管理员账号打开 [管理员面试记录](http://127.0.0.1:3000/admin/interviews)。已结束场次可点击「生成面试评价」，按四级成绩报告和完整研究生成绩单核验资格，并查看能力分和对应原话。

fake 模型生成确定性演示评价，请使用合成资料。正式使用时沿用仓库内的模型配置及独立管理员凭证。已有面试记录由当前数据库配置决定。

#### API

招聘者用 `POST /api/formal-interviews` 一次录入岗位、候选人、JD 和简历。后端依次询问自我介绍、英语四级、项目经验、研究生课程、求职动机、期望收入、职业规划、自我评价和岗位工作安排，再补充 3 道围绕岗位和简历的问题。薪资题涵盖期望月薪、年薪及可接受最低薪资。岗位工作安排自愿回答。

英语四级须达到 425 分，研究生期间曾挂科门数须为 0，补考或重修后通过仍计入。两道资格题须作答，暂不确定可填写待核验。若面试计时结束，系统先补问尚未完成的资格题。资格以人工核验证明为准，已核验不达标会单独标为不满足硬性资格，能力评分继续展示。末题提交后进入待评价。

独立管理员通过 `GET /api/admin/interviews` 分页查阅保留期内各状态的场次，通过 `GET /api/admin/interviews/{id}` 查看详情，通过 `GET /api/admin/interviews/{id}/events` 按 `seq` 升序回放该场 `interview_events`（同意、开场、作答、暂停、打断、完结、评分与报告等），通过 `POST /api/admin/interviews/{id}/score` 为已结束面试生成证据评价。撤回后只展示场次状态和基本信息。评价复用现有证据校验和人工复核机制。业务写入与事件写入同一事务；`payload` 在 Postgres 为 `jsonb`，在 SQLite 为 JSON 文本。

历史网页语音联调的环境和范围见 [D52](DECISIONS.md#d52-独立后端的网页语音联调)。

## 公网访问

公网模式使用现有数据库和模型配置，运行 FastAPI 与 Next.js 的生产入口。它要求一个固定的 HTTPS 网址，关闭演示登录和服务端语音识别。候选人邀请链接使用招聘者打开页面时的 HTTPS 网址。

在本机 PowerShell 执行。把 `interview.example.com` 换成你配置的域名。

```powershell
# 在仓库根目录执行
$env:PYTHON_EXECUTABLE = (Resolve-Path '.\.venv-clean\Scripts\python.exe').Path
node scripts/dev.mjs --show-admin
pnpm build
node scripts/dev.mjs --public-url https://interview.example.com
```

公网前端监听 `127.0.0.1:3100`，与开发前端的 `3000` 分开。FastAPI 监听 `127.0.0.1:8000`。将公网 HTTPS 入口的所有路径转发到 `http://127.0.0.1:3100`，并让代理保留浏览器的 `Origin`、`Cookie`、`Set-Cookie` 和 SSE 响应流。按网络条件配置以下一种入口。

- 有域名和可达的公网 IP 时，可将 DNS 指向主机，放行 TCP 80/443 后运行 `caddy reverse-proxy --from interview.example.com --to 127.0.0.1:3100`。主机经过路由器时将这两个端口转发到 Caddy。[Caddy 反向代理文档](https://caddyserver.com/docs/quick-starts/reverse-proxy)
- 位于内网时，可在同一台电脑运行已配置的 Cloudflare Tunnel，将固定域名的 Published application route 指向 `http://127.0.0.1:3100`。面试答题使用 SSE，因此使用固定域名的隧道，临时 Quick Tunnel 缺少 SSE 支持。[Cloudflare Tunnel 配置](https://developers.cloudflare.com/tunnel/get-started/) · [Quick Tunnel 限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/#limitations)

公网入口可从另一张网络打开 `https://<你的域名>/api/ready` 检查。网页从 `/login` 登录，管理员进入面试记录，招聘者进入发起面试页。公网模式使用同一份本机账号配置。通过密钥管理器注入时，同时设置 `RECRUITER_PASSWORD`、`ADMIN_PASSWORD` 和 `AUTH_SECRET` 三个进程环境变量，可另设 `RECRUITER_USERNAME` 和 `ADMIN_USERNAME`。

## 启动轻量练习网页

页面在 `apps/practice`，使用原生 HTML、CSS 和 Fetch API。以下两组命令在各自的 PowerShell 终端运行，使用本仓库的 `.venv-clean`，直接打开 `http://localhost:5173`。

终端一启动后端。

```powershell
# 在仓库根目录执行
$py = '.\.venv-clean\Scripts\python.exe'
$env:PYTHONPATH = 'apps/api'
$env:APP_ENV = 'development'
$env:LLM_PROVIDER = 'fake'
$env:DB_DRIVER = 'sqlite'
$env:SQLITE_PATH = '.data/python/web-practice.sqlite3'
$env:STT_PROVIDER = 'whisper'
$env:STT_MODEL = 'base'
$env:STT_MODEL_PATH = '.data/models/whisper/base.pt'
$env:FFMPEG_PATH = '.data/tools/ffmpeg.exe'
$env:TTS_PROVIDER = 'local'
& $py -m uvicorn interviewer.main:app --host 127.0.0.1 --port 8010
```

终端二启动静态页面。

```powershell
# 在仓库根目录执行
& .\.venv-clean\Scripts\python.exe -m http.server 5173 --bind 127.0.0.1 --directory apps/practice
```

在网页确认知情说明后，填写文字或选择一个音频文件，然后发送。音频先经本机 Whisper 转写，候选人和面试官的文字随后分别显示在聊天区两侧。当前标签页刷新可继续，侧栏可删除会话。两个终端各按 `Ctrl+C` 停止服务。

`fake` 模式用于本地演示。连接已获准的内网 OpenAI 兼容模型时，将终端一的 `LLM_PROVIDER` 改为 `internal`，在后端 `.env` 配置 `LLM_BASE_URL`、`LLM_MODEL` 及网关所需的 `LLM_API_KEY`。可选 `LLM_MODEL_NAME` 覆盖对话模型名。模型密钥只由后端读取。使用 `STT_PROVIDER=auto` 可运行纯文字版。

## Python / 全仓验证

```powershell
$py = '.\.venv-clean\Scripts\python.exe'
$env:PYTHONPATH = 'apps/api'
$env:LLM_PROVIDER = 'fake'
$env:PYTHON_EXECUTABLE = (Resolve-Path '.\.venv-clean\Scripts\python.exe').Path
& $py -m ruff check --config apps/api/pyproject.toml apps/api scripts
& $py -m mypy --config-file apps/api/pyproject.toml apps/api/interviewer scripts
& $py -m pytest -c apps/api/pyproject.toml apps/api/tests
& $py -m interviewer.cli evals
pnpm lint
pnpm typecheck
pnpm test
pnpm build
# 等价一次门禁：pnpm verify
```

PostgreSQL 测试需要明确指定可丢弃的 `TEST_DATABASE_URL`。Python 服务镜像配置位于 `apps/api/Dockerfile`，本机运行可直接使用上文「在本机启动」中的 Uvicorn 命令。Compose 见「项目收尾摘要」中的 Docker Compose 小节。
