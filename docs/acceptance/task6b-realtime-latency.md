# Task 6b 实时延迟与打断验收

测量入口：`scripts/measure_realtime_latency.py`（转调 `test_realtime_latency_measure.py`）。  
证据 JSON：`docs/acceptance/evidence/task6b-realtime-latency.json`。  
Provider：Fake ASR / Fake TTS / fake LLM（`LLM_PROVIDER=fake`），无外网。

## 打点位置

| 指标 | 打点 | 预算 |
| --- | --- | --- |
| ASR 首字 | `pipeline._run_turn`：`T_asr` 在 `gateway.transcribe` 返回后；fake 一次返回全文，首字=终稿 | &lt;300ms |
| LLM 首 token | `service.turn` 返回 utterance 的墙钟 | &lt;800ms |
| TTS 首字节 | 首个 `tts_chunk` 发出时刻 | &lt;400ms |
| 端到端 P95 | 首个 `tts_chunk` − turn 起点 `T0` | &lt;1.5s |
| 打断静音 | `EnergyVad.just_started` → `interrupted` 已发送且 TTS 队列清空 | ≤200ms |

样本量：每指标 **n=8**（每样本独立面试）；打断样本 **n=1**。

## 本机实测（摘要）

来自证据 JSON（fake 路径）：

- ASR 首字 P95 ≈ **9.6ms**（预算 300）
- LLM 首 token P95 ≈ **27.5ms**（预算 800）
- TTS 首字节 P95 ≈ **0.15ms**（预算 400；fake 合成几乎即时）
- 端到端 P95 ≈ **37.2ms**（预算 1500）
- 打断静音 ≈ **10.4ms**（预算 200）

全部 **pass**。完整数值见证据文件。

## 说明

- 本验收证明 **管道与打点正确、预算在 fake 路径下可达**；真实 Whisper/Edge/云 LLM 延迟需另开人工试验。
- base64 JSON 分片在 fake 下不是瓶颈；若真实 PCM 吞吐不够再评估二进制帧（D75）。
