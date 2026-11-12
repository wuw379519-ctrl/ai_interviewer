import type { ReportDocument } from "@aii/core";

type RiskItem = NonNullable<ReportDocument["riskItems"]>[number];

/** Presentational proctor risk block — never drives hire/reject. Lives on report page 2 for A4 fit. */
export function ReportProctorRisks({ items }: { items: RiskItem[] | undefined }) {
  const rows = items ?? [];
  if (rows.length === 0) {
    return (
      <p className="report-proctor-empty" data-testid="report-proctor-risks">
        过程信号提示：本场未触发规则化信号（不参与评分，不自动录用/淘汰）。
      </p>
    );
  }
  return (
    <section className="report-proctor" data-testid="report-proctor-risks">
      <h2>过程信号提示（不参与评分）</h2>
      <p className="small muted">以下信号建议人工关注或复核；AI 不据此录用或淘汰。不进入评分证据链。</p>
      <ul>
        {rows.map((item) => (
          <li key={item.code} data-testid={`proctor-risk-${item.code}`} data-severity={item.severity}>
            <strong>{item.severity === "review" ? "建议人工关注" : "仅提示"}</strong>
            {" · "}
            {item.message}
            {item.affectsScore ? null : <span className="small muted"> · 不打分</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
