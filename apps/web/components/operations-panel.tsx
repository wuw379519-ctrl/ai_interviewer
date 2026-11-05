"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { api } from "@/lib/client-api";
import { operationsSchema, type Operations } from "@/lib/operations-schema";
const readinessSchema = z.object({ ok: z.literal(true), database: z.literal("ready"), mode: z.string(), speech: z.enum(["server_configured", "device_local"]) });
const labels = { candidate_write: "同意、开始及设备写入", turn: "回答与SSE", state: "恢复状态", score: "离线评分", transcribe: "企业转写", plan: "创建计划" };
export function OperationsPanel() {
  const [data, setData] = useState<Operations>(), [ready, setReady] = useState<z.infer<typeof readinessSchema>>(), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true); setError("");
    try { const [metrics, readiness] = await Promise.all([api("/api/admin/operations", operationsSchema), api("/api/ready", readinessSchema)]); setData(metrics); setReady(readiness); }
    catch (error) { setError(error instanceof Error ? error.message : "运行状态暂不可用"); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return <section className="panel form-panel" aria-label="服务运行状态"><div className="section-heading"><h2>服务运行状态</h2><button className="button secondary" disabled={busy} onClick={() => void load()}>刷新运行指标</button></div>
    {error && <p role="alert" className="error-banner">{error}</p>}{ready && <p data-testid="deployment-readiness">应用与数据库已就绪 · {ready.mode} · {ready.speech === "server_configured" ? "已配置企业转写（连通性需联调）" : "设备端中文识别（需本机语音包）"}</p>}
    <p className="small muted">当前进程自启动以来的内存累计值，重启归零、多实例不汇总。耗时到响应头生成，不含SSE发送完成；4xx计入客户端错误，5xx计入服务失败。不包含回答、音频、身份、URL或设备明细。</p>
    {data && <><p className="small muted">启动：{new Date(data.startedAt).toLocaleString("zh-CN")} · 采样：{new Date(data.sampledAt).toLocaleString("zh-CN")}</p><div className="table-wrap"><table><thead><tr><th>操作</th><th>请求</th><th>4xx / 5xx</th><th>平均 / 最长耗时</th></tr></thead><tbody>{data.items.map((row) => <tr key={row.operation}><td>{labels[row.operation]}</td><td>{row.requests}</td><td>{row.clientErrors} / {row.failures}</td><td>{Math.round(row.totalMs / Math.max(1, row.requests))} / {row.maxMs} ms</td></tr>)}</tbody></table></div>{!data.items.length && <p>尚无已采样的面试请求。</p>}</>}
    <Link className="text-button" href="/diagnostics/voice" target="_blank" rel="noopener noreferrer">打开本机语音与摄像头联调页</Link>
  </section>;
}
