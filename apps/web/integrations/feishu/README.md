# Frontend Feishu access points

Next.js 侧占位模块，路径别名：`@/integrations/feishu`。

| 文件 | 预留能力 |
| --- | --- |
| `status.ts` | `getFeishuStatus()` → 同源 `/api/feishu/status` |
| `jsapi.ts` | `initFeishuJsapi` / `requestFeishuAccess`（接收 status） |
| `auth.ts` | 免登开始 / 完成 / 用户资料（接收 status） |
| `api.ts` | 与自家后端桥接（接收 status；永不直连 open.feishu.cn） |
| `server.ts` | `import "server-only"`；密钥辅助，不从 `index.ts` 导出 |

配置唯一来源为 Python Settings + 运行时接口。浏览器不读 `process.env` 飞书变量。
