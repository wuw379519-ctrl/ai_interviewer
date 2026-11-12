# Task 6b 实时延迟与打断验收

测量入口：`scripts/measure_realtime_latency.py`（转调 `test_realtime_latency_measure.py`）。  
证据 JSON：`docs/acceptance/evidence/task6b-realtime-latency.json`。  
Provider：Fake ASR / Fake TTS / fake LLM（`LLM_PROVIDER=fake`），无外网。

## 打点位置（代码）

均在 `apps/api/interviewer/realtime/pipeline.py` 的 `_run_turn` / `barge_in`：

| 指标 | 起点 | 终点 | 预算 |
| --- | --- | --- | --- |
| ASR 首字 | `t0 = perf_counter()`（turn 开始） | `transcribe` 返回后记 `asr_first_ms`（fake 全文一次返回，首字=终稿） | &lt;300ms |
| LLM 首 token | `t_llm0`（ASR/文本就绪后） | `service.turn` / `write_with_key` 返回后记 `llm_first_ms` | &lt;800ms |
| TTS 首字节 | `t_tts0`（开始 `synthesize` 前） | **服务端发出首个** `tts_chunk` 时记 `tts_first_ms` | &lt;400ms |
| 端到端 | `t0` | **服务端发出首个** `tts_chunk`（`e2e_ms`） | P95 &lt;1.5s |
| 打断静音 | `onset_mono`（`EnergyVad.just_started` 当帧） | `interrupted` **消息已 send** + TTS 队列已 `cancel`（`InterruptTiming.silence_ms`） | ≤200ms |

样本量：每指标 **n=8**（每样本独立面试）；打断样本 **n=1**。

## 测量边界与局限

- **端到端不含客户端播放**：只统计到服务端发出首个 `tts_chunk`，不含浏览器解码/AudioContext 排队/扬声器起振。
- **打断静音 10ms 级数字**：是「VAD onset → 服务端 `interrupted` 已发出且服务端 TTS 队列清空」，**不是**「客户端播放队列已空」。客户端收到 `interrupted` 后自行 `stop()`/`flush` 播放队列（ws-client / 播放器职责）。
- **fake provider 测的是 pipeline 开销**（调度、幂等写库、分片发送），**不代表**真实 Whisper ASR / Edge TTS / 云 LLM 延迟。真实 provider 延迟须另开人工或有密钥的隔离试验后再写验收。
- base64 JSON 分片在 fake 下不是瓶颈；若真实 PCM 吞吐不够再评估二进制帧（D75）。

## audio_chunk 分片粒度（客户端约定）

- 协议上限：单片 PCM ≤ **32000 字节 ≈ 1s**（16 kHz s16le mono）；`seq` 严格递增。
- **推荐客户端分片：100–200ms**（3200–6400 字节），兼顾 VAD 反应与 JSON/base64 开销；不要按 1s 大包送（拖慢打断）。
- 允许缺省 `pcmBase64` 的空片（仅推进/心跳语义时）；空片不喂 VAD。

## 本机实测（摘要）

来自证据 JSON（fake 路径）：

- ASR 首字 P95 ≈ **9.6ms**（预算 300）
- LLM 首 token P95 ≈ **27.5ms**（预算 800）
- TTS 首字节 P95 ≈ **0.15ms**（预算 400；fake 合成几乎即时）
- 端到端 P95 ≈ **37.2ms**（预算 1500）
- 打断静音 ≈ **10.4ms**（预算 200）

全部 **pass**。完整数值见证据文件。
