import type { Metadata } from "next";
import "./globals.css";
import "./report.css";
import "./formal.css";

export const metadata: Metadata = {
  title: "AI 面试官 · 结构化面试与证据化评分",
  description: "录入岗位与简历，由 AI 面试官完成结构化面试，输出每个维度都有原文证据支撑的评分报告。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
