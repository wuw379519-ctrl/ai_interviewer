# AI 面试官 —— 架构设计与项目目录设计

> 场景：B 端企业招聘（多租户 SaaS）
> 交互：实时语音对话（流式 ASR / LLM / TTS，支持打断）
> 技术栈：Python (FastAPI) + React (Next.js) + PostgreSQL + Redis

---

## 一、设计原则

| 原则 | 落法 |
|---|---|
| 业务与模型解耦 | ASR/LLM/TTS 全部收敛到 `AI Gateway`，业务层只调抽象接口，换供应商不改业务代码 |
| 面试过程可回放可审计 | 事件溯源式存储（`interview_events`），任何一次面试都能逐帧重放 |
| 编排逻辑可测 | 面试状态机是纯函数：`(state, input) -> (state, actions)`，不依赖网络，单测覆盖 |
| 长任务不阻塞 | 报告生成、批量转写、简历解析走 Celery，接口立即返回 task_id |
| 多租户隔离在底层 | PostgreSQL RLS + 应用层 tenant 校验双保险，杜绝"忘了加 where" |

---

## 二、整体架构

```
┌──────────────────────────── 接入层 ────────────────────────────┐
│  候选人端 (Next.js)    HR 控制台 (Next.js)    BFF / API Gateway  │
└───────────────────────────────┬───────────────────────────────┘
                                │ HTTPS + WSS
┌───────────────────────────────▼───────────────────────────────┐
│                      应用服务层 (FastAPI)                       │
│                                                                │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────┐  │
│  │ 面试编排引擎  │ │ 实时对话网关  │ │   AI 能力编排网关      │  │
│  │ StateMachine │ │ WS / WebRTC  │ │  ASR / LLM / TTS 抽象 │  │
│  └──────────────┘ └──────────────┘ └───────────────────────┘  │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────┐  │
│  │ 题库岗位服务  │ │ 评估报告服务  │ │  租户权限服务          │  │
│  └──────────────┘ └──────────────┘ └───────────────────────┘  │
└───────────────────────────────┬───────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────┐
│   PostgreSQL(+pgvector) │ Redis │ 对象存储 │ Celery Worker     │
└───────────────────────────────────────────────────────────────┘
```

### 为什么不一开始拆微服务

B 端招聘的并发峰值是"同一时刻进入面试的人数"，中小客户通常 < 100 并发。先用**模块化单体**（一个 FastAPI 应用，内部按业务模块分包），把边界划在包级别。等单模块 QPS 或团队人数撑不住时，按包拆服务，成本最低。唯一例外：**实时对话网关**因长连接和水平扩容诉求独立，从第一天起就要能单独部署。

---

## 三、核心模块设计

### 3.1 面试编排引擎（系统大脑）

面试不是"一问一答直到问完"，而是带时间预算和目标覆盖的策略过程。

**状态机**

```
         ┌──────────┐
         │  PENDING │  简历解析 / 题目预生成
         └────┬─────┘
              ▼
         ┌──────────┐
    ┌───▶│INTRO     │  自我介绍、规则说明
    │    └────┬─────┘
    │         ▼
    │    ┌──────────┐   ┌─────────────┐
    │    │ASKING    │──▶│LISTENING    │
    │    └────┬─────┘   └──────┬──────┘
    │         │                │ 回答结束
    │         │                ▼
    │         │         ┌─────────────┐
    │         │         │EVALUATING   │ 打分 + 决定下一步
    │         │         └──────┬──────┘
    │         │                │
    │         │     ┌──────────┼──────────┬──────────┐
    │         │     ▼          ▼          ▼          ▼
    │         │  追问(PROBE) 换题(NEXT) 澄清 收尾(WRAP)
    │         └─────┘          │                      │
    │                          └──────────────────────┤
    │                                                 ▼
    │                                          ┌────────────┐
    └──────────────────────────────────────────│  FINISHED  │
                                               └─────┬──────┘
                                                     ▼
                                              ┌────────────┐
                                              │  REPORTING │
                                              └────────────┘
```

**每次决策的输入输出**

```python
@dataclass(frozen=True)
class TurnContext:
    state: InterviewState
    last_answer: str
    asr_confidence: float
    elapsed_ratio: float        # 已用时间 / 总预算
    coverage: dict[str, float]  # 能力项覆盖度
    probe_depth: int            # 当前题目已追问层级

@dataclass(frozen=True)
class Decision:
    action: Literal["probe", "next", "clarify", "wrap"]
    utterance: str
    next_question_id: str | None
    reason: str                 # 落库，便于复盘为什么这么问
```

**关键策略（可配置，不是写死）**

- 时间守卫：`elapsed_ratio > 0.85` 时强制进入收尾，不再开新题
- 追问深度：单题最多 2 层，避免陷入死循环
- 话题收敛：候选人连续 2 次答偏则换题并记 `off_topic`
- 兜底：LLM 决策超时（>3s）走规则兜底（按题库顺序下一题），绝不卡住对话

### 3.2 实时对话网关

- 传输：候选人端 `WebSocket`（浏览器原生采集 16k PCM），服务端与 AI 供应商之间可走 `WebRTC` 或纯 WS
- 会话粘性：`Redis` 存 `session_id -> worker_id` + 状态快照，断线重连恢复到最近事件
- 打断处理：候选人开口（VAD 触发）→ 立刻 `tts.cancel()` + 清空客户端播放队列 → 记录 `interrupted_at`
- 延迟预算：ASR 首字 < 300ms，LLM 首 token < 800ms，TTS 首字节 < 400ms，端到端 P95 < 1.5s

### 3.3 AI 能力网关

统一抽象，所有供应商实现同一协议：

```python
class ASRProvider(Protocol):
    async def stream(self, audio: AsyncIterator[bytes]) -> AsyncIterator[ASRChunk]: ...

class LLMProvider(Protocol):
    async def stream(self, messages: list[Msg], **kw) -> AsyncIterator[str]: ...

class TTSProvider(Protocol):
    async def stream(self, text: AsyncIterator[str]) -> AsyncIterator[bytes]: ...
```

能力：多供应商路由（按租户配置）、熔断降级、成本计量（token/秒数记账到租户）、Prompt 版本管理。

### 3.4 评估与报告

- **四维评分**：专业能力（题目维度）、表达逻辑（STAR 结构识别）、深度（追问应答一致性）、风险项（矛盾点、含糊表述）
- **防作弊**：唇动与音频一致性（可选视觉）、回答延迟异常（过快=念稿）、声纹切换、第二人声检测、页面切屏记录
- **报告**：总分 + 雷达图 + 逐题回放（音频片段 + 转写 + 点评）+ 推荐结论（强烈推荐/推荐/待定/不推荐）
- **异步**：面试结束后 Celery 生成，HR 端轮询或 WS 推送

---

## 四、数据模型（核心表）

```
tenants ─┬─ users ──── role_bindings
         ├─ jobs ───── job_versions ──── competency_models
         │                                   │
         │                                   ▼
         ├─ questions ──────────── question_competency (M:N)
         │      └─ embeddings (pgvector)
         │
         ├─ candidates ──── resumes
         │
         └─ interviews ─┬─ interview_events   ← 事件溯源，核心表
                        ├─ turn_records       ← 单轮问答（转写+音频指针）
                        ├─ evaluations        ← 每轮评分
                        └─ reports            ← 最终报告

invites     ── 面试邀请（token、有效期、一次性）
proctor_logs── 防作弊日志
ai_usage    ── 供应商调用计量
audit_logs  ── 操作审计
```

**`interview_events` 设计要点**（一切可回放的根基）

| 字段 | 说明 |
|---|---|
| `id` / `interview_id` / `seq` | `seq` 单调递增，唯一索引 `(interview_id, seq)` |
| `event_type` | `state_changed` / `question_asked` / `answer_received` / `interrupted` / `score_computed` |
| `payload` (jsonb) | 事件完整数据 |
| `ts` | 服务端时间戳，毫秒精度 |

好处：崩溃恢复 = 重放事件；调试 = 看事件流；数据挖掘 = 直接查 jsonb。

---

## 五、项目目录设计

```
ai-interviewer/
├── apps/
│   ├── api/                              # FastAPI 后端
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── Dockerfile
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   ├── src/
│   │   │   ├── main.py                   # 应用装配入口
│   │   │   ├── core/                     # 与业务无关的横切能力
│   │   │   │   ├── config.py             # Pydantic Settings，读 .env
│   │   │   │   ├── security.py           # JWT / 密码哈希 / 邀请 token
│   │   │   │   ├── deps.py               # 依赖注入：db session / 当前租户 / 当前用户
│   │   │   │   ├── tenancy.py            # 租户上下文 + RLS 变量注入
│   │   │   │   ├── errors.py             # 统一异常与错误码
│   │   │   │   ├── logging.py            # 结构化日志 + trace_id
│   │   │   │   └── pagination.py
│   │   │   ├── db/
│   │   │   │   ├── base.py               # SQLAlchemy Base / 公共字段 mixin
│   │   │   │   ├── session.py            # async engine + session factory
│   │   │   │   └── models/               # 按领域拆文件
│   │   │   │       ├── tenant.py
│   │   │   │       ├── user.py
│   │   │   │       ├── job.py
│   │   │   │       ├── question.py
│   │   │   │       ├── candidate.py
│   │   │   │       ├── interview.py
│   │   │   │       ├── evaluation.py
│   │   │   │       ├── report.py
│   │   │   │       └── audit.py
│   │   │   ├── ai/                       # AI 能力网关（唯一出模型调用的地方）
│   │   │   │   ├── gateway.py            # 路由 / 熔断 / 计量
│   │   │   │   ├── base.py               # Provider Protocol 定义
│   │   │   │   ├── asr/
│   │   │   │   │   ├── volcengine.py
│   │   │   │   │   ├── aliyun.py
│   │   │   │   │   └── whisper_local.py
│   │   │   │   ├── llm/
│   │   │   │   │   ├── openai_compat.py
│   │   │   │   │   ├── anthropic.py
│   │   │   │   │   └── qwen.py
│   │   │   │   ├── tts/
│   │   │   │   │   ├── azure.py
│   │   │   │   │   └── minimax.py
│   │   │   │   ├── prompts/              # 模板 + 版本号，不写死在代码里
│   │   │   │   │   ├── question_gen.md
│   │   │   │   │   ├── probe_decide.md
│   │   │   │   │   ├── evaluate_answer.md
│   │   │   │   │   └── gen_report.md
│   │   │   │   └── schemas.py            # LLM 结构化输出的 Pydantic 模型
│   │   │   ├── modules/                  # 业务模块（未来拆服务的边界）
│   │   │   │   ├── auth/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   └── schemas.py
│   │   │   │   ├── tenants/
│   │   │   │   ├── jobs/
│   │   │   │   ├── questions/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── service.py      # CRUD + 向量检索
│   │   │   │   │   ├── generator.py    # 岗位JD → 题目生成
│   │   │   │   │   └── schemas.py
│   │   │   │   ├── candidates/
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── resume_parser.py
│   │   │   │   │   └── schemas.py
│   │   │   │   ├── interviews/         # 面试生命周期 CRUD
│   │   │   │   │   ├── router.py
│   │   │   │   │   ├── service.py
│   │   │   │   │   ├── invite.py       # 邀请链接、校验、限流
│   │   │   │   │   └── schemas.py
│   │   │   │   ├── evaluations/
│   │   │   │   ├── reports/
│   │   │   │   └── billing/
│   │   │   ├── interview_runtime/        # ★ 面试运行时（本系统最核心）
│   │   │   │   ├── machine.py            # 状态机纯逻辑，零 IO
│   │   │   │   ├── policy.py             # 追问/换题/收尾策略
│   │   │   │   ├── state.py              # InterviewState 不可变数据结构
│   │   │   │   ├── events.py             # 事件定义 + 序列化
│   │   │   │   ├── orchestrator.py       # 状态机 + IO 的粘合层
│   │   │   │   ├── session_store.py      # Redis 会话快照存取
│   │   │   │   ├── timing.py             # 时间预算守卫
│   │   │   │   └── tests/
│   │   │   │       ├── test_machine.py
│   │   │   │       └── test_policy.py
│   │   │   ├── realtime/                 # ★ 实时链路
│   │   │   │   ├── ws_router.py          # /ws/interview/{session_id}
│   │   │   │   ├── connection.py         # 连接生命周期、心跳、重连
│   │   │   │   ├── pipeline.py           # 音频 → ASR → 编排 → TTS → 音频
│   │   │   │   ├── vad.py                # 断句检测
│   │   │   │   ├── tts_player.py         # 分片下发 + 打断控制
│   │   │   │   └── protocol.py           # 前后端消息协议（双向）
│   │   │   ├── proctoring/               # 防作弊
│   │   │   │   ├── signals.py            # 各类信号采集
│   │   │   │   ├── scorer.py             # 风险打分
│   │   │   │   └── report.py
│   │   │   └── workers/                  # Celery
│   │   │       ├── celery_app.py
│   │   │       ├── tasks_report.py
│   │   │       ├── tasks_resume.py
│   │   │       ├── tasks_question_gen.py
│   │   │       └── tasks_cleanup.py      # 录音过期清理（合规）
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── api/
│   │       └── integration/
│   │
│   ├── web-candidate/                    # 候选人端 Next.js
│   │   ├── package.json
│   │   ├── next.config.ts
│   │   └── src/
│   │       ├── app/
│   │       │   ├── layout.tsx
│   │       │   ├── page.tsx              # 邀请落地页
│   │       │   ├── (interview)/
│   │       │   │   ├── device-check/page.tsx   # 设备检测（麦克风/网络/浏览器）
│   │       │   │   ├── lobby/page.tsx          # 候场须知
│   │       │   │   ├── live/page.tsx           # 面试主界面
│   │       │   │   └── done/page.tsx
│   │       │   └── api/health/route.ts
│   │       ├── components/
│   │       │   ├── interview/
│   │       │   │   ├── InterviewRoom.tsx
│   │       │   │   ├── AvatarSpeaker.tsx       # 数字人口型/动画
│   │       │   │   ├── LiveTranscript.tsx
│   │       │   │   ├── MicIndicator.tsx        # 音量波形、打断提示
│   │       │   │   ├── QuestionCard.tsx
│   │       │   │   └── Timer.tsx
│   │       │   └── ui/                          # 基础组件
│   │       ├── lib/
│   │       │   ├── audio/
│   │       │   │   ├── recorder.ts       # AudioWorklet 采集 16k PCM
│   │       │   │   ├── player.ts         # 流式播放 + 立即截断
│   │       │   │   └── worklet/pcm-processor.js
│   │       │   ├── ws/
│   │       │   │   ├── client.ts         # 重连、心跳、消息队列
│   │       │   │   └── protocol.ts       # 与后端 protocol.py 对应
│   │       │   └── proctor/
│   │       │       └── visibility.ts     # 切屏/失焦检测
│   │       └── styles/
│   │
│   ├── web-recruiter/                    # HR 控制台 Next.js
│   │   └── src/
│   │       ├── app/
│   │       │   ├── (auth)/login
│   │       │   └── (dashboard)/
│   │       │       ├── jobs/             # 岗位管理
│   │       │       │   ├── page.tsx
│   │       │       │   └── [id]/page.tsx
│   │       │       ├── questions/        # 题库
│   │       │       ├── candidates/
│   │       │       ├── interviews/
│   │       │       │   ├── page.tsx
│   │       │       │   └── [id]/page.tsx # 回放 + 报告
│   │       │       ├── analytics/        # 漏斗、对比
│   │       │       └── settings/
│   │       ├── components/
│   │       │   ├── interview-replay/
│   │       │   │   ├── TimelinePlayer.tsx
│   │       │   │   ├── TranscriptPanel.tsx
│   │       │   │   └── RadarChart.tsx
│   │       │   └── charts/
│   │       └── lib/api/                   # 生成的 OpenAPI client
│   │
│   └── web-admin/                        # 平台管理后台（租户、配额、审计）
│
├── packages/
│   ├── api-client/                       # OpenAPI → TS 客户端，两端共用
│   ├── shared-types/                     # 枚举、状态码常量（前后端单一真源）
│   └── eslint-config/
│
├── infra/
│   ├── docker-compose.yml                # 本地：pg + redis + minio + api + worker
│   ├── docker-compose.prod.yml
│   ├── k8s/
│   │   ├── api-deployment.yaml
│   │   ├── realtime-hpa.yaml             # 长连接服务独立扩缩容
│   │   └── worker-deployment.yaml
│   └── nginx/
│       └── nginx.conf                    # WSS 转发、超时配置
│
├── docs/
│   ├── architecture.md
│   ├── interview-protocol.md             # WS 消息协议文档
│   ├── scoring-rubric.md                 # 评分标准（业务方共同维护）
│   └── adr/                              # 架构决策记录
│       ├── 0001-modular-monolith.md
│       └── 0002-event-sourcing-interview.md
│
├── scripts/
│   ├── seed_demo_data.py
│   ├── gen_api_client.sh
│   └── migrate.sh
│
├── .env.example
├── Makefile                              # make dev / test / lint / migrate
└── README.md
```

---

## 六、目录设计的三条依据

**1. `modules/` 与 `interview_runtime/` 分开**
`modules/` 是常规 CRUD 业务（岗位、题库、候选人），`interview_runtime/` 是面试过程的有状态逻辑。前者好写，后者才是难点，单独拎出来才能高密度写单测——`machine.py` 零 IO，可以毫秒级跑完整场面试的模拟。

**2. `ai/` 是唯一能出现模型 SDK 的地方**
任何业务模块禁止 `import openai`。这样换模型、加供应商、做成本核算、做 A/B 测试都只改一个目录。

**3. `packages/shared-types` 保证协议不漂移**
WS 消息协议在 `realtime/protocol.py` 定义，导出为 TS 类型。前后端对不上是这类项目最常见的线上事故。

---

## 七、关键技术选型说明

| 需求 | 选型 | 理由 |
|---|---|---|
| 后端框架 | FastAPI | 原生 async，WS 支持好，Pydantic 做 LLM 结构化输出校验天然契合 |
| ORM | SQLAlchemy 2.0 async + Alembic | 成熟，异步生态完整 |
| 向量检索 | pgvector | 避免额外引入向量库，题库规模（万级）完全够用 |
| 队列 | Celery + Redis | 报告生成等长任务，简单可靠 |
| 对象存储 | S3 / MinIO | 本地用 MinIO，生产用云 OSS/S3，接口兼容 |
| 前端 | Next.js 15 App Router | 候选人端/H R 端共用组件，SSR 利于邀请页首屏 |
| 状态管理 | TanStack Query + Zustand | 服务端状态与本地状态分离 |
| 实时 | 原生 WebSocket + AudioWorklet | 比 WebRTC 更易控，服务端可做加工；视觉需求再叠加 WebRTC |
| 可观测 | OpenTelemetry + Langfuse | 链路追踪 + LLM 调用可视化 |

---

## 八、实施路线

| 阶段 | 交付 | 验收标准 |
|---|---|---|
| M1 骨架 | 目录搭建、docker-compose、租户/用户/岗位/题库 CRUD、登录 | 本地一条命令起服务，HR 能建岗位和题目 |
| M2 文本面试 | 编排引擎 + 纯文字对话面试 + 报告生成 | 状态机单测覆盖，能完整跑完一场文字面试出报告 |
| M3 语音链路 | WS + ASR/TTS 流式 + 打断 | 端到端 P95 < 1.5s，打断后 200ms 内静音 |
| M4 评估体系 | 四维评分、雷达图、回放播放 | 3 位 HR 盲评与 AI 评分相关性 > 0.7 |
| M5 防作弊与合规 | 唇动校验、切屏记录、录音留存策略 | 通过法务数据合规评审 |
| M6 规模化 | K8s、HPA、多供应商降级演练 | 200 并发不断线，单供应商故障自动切换 |

**建议从 M2 开始做**：先用文字把编排引擎和评估体系跑通，这两块决定产品价值；语音只是通道，可以晚 2-3 周接入，风险更低。

---

## 九、需要提前决策的点

1. **数字人形象**：是否需要视频数字人？如果需要，增加 `realtime/avatar.py` 与口型驱动（wav2lip 类），延迟预算要重算
2. **模型合规**：候选人录音是否允许出境？决定 ASR/TTS 只能用国内供应商还是可用海外 API
3. **评分责任**：AI 评分是否直接参与淘汰决策？涉及算法解释义务，报告需给出逐条依据
4. **数据留存**：录音保留多久、候选人如何行使删除权，直接影响 `tasks_cleanup.py` 与表结构
