import Link from "next/link";
export function Brand() {
  return <Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">见</span><span>见微<span className="brand-sub">INTERVIEW</span></span></Link>;
}
export function Shell({ children, section = "招聘工作台" }: { children: React.ReactNode; section?: string }) {
  return <div className="app-shell"><aside className="sidebar"><Brand /><p className="nav-label">工作空间</p><nav aria-label="主导航"><Link href="/" className={section === "招聘工作台" ? "nav-item active" : "nav-item"}><span aria-hidden="true">◫</span> 招聘工作台</Link><Link href="/recruiter/new" className={section === "创建面试" ? "nav-item active" : "nav-item"}><span aria-hidden="true">＋</span> 创建面试</Link><Link href="/admin" className={section === "数据治理" ? "nav-item active" : "nav-item"}><span aria-hidden="true">◇</span> 数据治理</Link></nav><div className="sidebar-note"><span className="status-dot" /> 人类始终拥有决定权<p>以行为证据支持招聘判断。<br />AI 不自动录用或淘汰。</p></div></aside><div className="app-main"><header className="topbar"><span>工作空间 <span className="muted">/ {section}</span></span><span className="topbar-tag">结构化 · 可追溯</span></header>{children}</div></div>;
}
