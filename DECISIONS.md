# Python 版整理记录

- 从 `ai_interviewer` 的 `3c2c873` 提取独立副本。保留 FastAPI、全部 Python 测试、语音 CLI、OpenAPI 生成命令、SQLite/PostgreSQL 迁移和 Python Dockerfile。
- PostgreSQL 迁移归到 `apps/api/migrations/postgres`。沿用每个 SQL 的文件名与字节内容，校验和及迁移记录兼容。
- 独立版默认直接访问 `http://127.0.0.1:8000`，通过 Python 启动。保留 OpenAPI JSON，关闭默认依赖 CDN 的 Swagger 页面。
- Web、Node 工具、TypeScript 包及其浏览器测试保留在原仓库。复制清单限定为源码和配置模板。现有 `.env`、密钥、权重、音频、数据库和虚拟环境由使用者保管，可在本机按需引用。
