import type { ReportDocument } from "@aii/core";
export function ReportRadar({ dimensions }: { dimensions: ReportDocument["dimensions"] }) {
  const cx = 180, cy = 145, radius = 94, count = dimensions.length;
  const point = (index: number, distance: number) => { const angle = (index / count) * 2 * Math.PI - Math.PI / 2; return [cx + Math.cos(angle) * distance, cy + Math.sin(angle) * distance] as const; };
  const points = (scale: number) => dimensions.map((_, index) => point(index, radius * scale).join(",")).join(" ");
  const complete = dimensions.every((row) => row.score !== "insufficient_evidence");
  return <figure className="report-radar"><svg viewBox="0 0 360 285" role="img" aria-label="胜任力雷达图：分数详见同页表格；证据不足维度不绘点">
    {[0.2, 0.4, 0.6, 0.8, 1].map((scale) => <polygon key={scale} points={points(scale)} fill="none" stroke="#cbd7d1" strokeWidth="1" />)}
    {dimensions.map((row, index) => { const end = point(index, radius), label = point(index, radius + 27); return <g key={row.competencyId}>
      <line x1={cx} y1={cy} x2={end[0]} y2={end[1]} stroke="#d7e1da" />
      <text x={label[0]} y={label[1]} textAnchor="middle" dominantBaseline="middle" fill="#24463c" fontSize="11">{row.competencyName.slice(0, 10)}{row.competencyName.length > 10 ? "…" : ""}</text>
    </g>; })}
    {complete && <polygon points={dimensions.map((row, index) => point(index, radius * Number(row.score) / 5).join(",")).join(" ")} fill="#b9d8c9" fillOpacity="0.65" stroke="#225d51" strokeWidth="2" />}
    {dimensions.map((row, index) => { if (row.score === "insufficient_evidence") return null; const xy = point(index, radius * Number(row.score) / 5); return <circle key={row.competencyId} cx={xy[0]} cy={xy[1]} r="4" fill="#225d51"><title>{row.competencyName}：{row.score}/5</title></circle>; })}
  </svg><figcaption>1-5级行为锚点 · 缺证据维度不绘点</figcaption></figure>;
}
