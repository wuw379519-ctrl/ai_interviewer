# 面试官LLM封装与CLI闭环（2026-11-05）

## 变化

- `apps/api/interviewer/llm_service.py`：ChatConfig、通用SYSTEM_PROMPT、OpenAI兼容请求、chat_with_interviewer、内存InterviewConversation。
- `scripts/test_chat.py`：input()循环，知情确认、固定开场、逐轮消息、空输入/退出/EOF/Ctrl+C、明确fake/real模式。
- `apps/api/tests/test_llm_service.py`、`test_chat_cli.py`：45项新增离线测试。
- `.env.example`、README、DECISIONS：配置、用法、边界；本机.env只追加缺失字段，不覆盖原有Key/地址/LLM_MODEL，未提交。

使用已有httpx0.28.1，没有新增或下载SDK/框架。[官方Chat Completions参考](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)用于核对POST路径、model/messages和choices格式；实现通过Pydantic验证输入、响应和问题输出。真实模型是否接受这些参数需单独手工验证，不能据此假定所有代理完全兼容。

## 配置与执行

LLM_MODEL_NAME优先于旧LLM_MODEL；均为空才默认用户指定的gpt-4o-mini。Key已填写时保留，无鉴权本地端点可空。地址、模型、75秒默认超时、并发1、输出512 token、温度0.2与历史字符上限24000均可配置。top_p显式0.9。候选人回答过长/历史超限会显式拒绝，不静默遗忘。

```powershell
node scripts/python.mjs scripts/test_chat.py --fake
# 仅在用户完成配置并获准后手工调用；本轮没有执行真实模式
node scripts/python.mjs scripts/test_chat.py --real
```

默认fake不发请求。real在CLI内覆写provider，不修改网页的模型/评分配置；本机/私有IP以外的域名或公网端点须LLM_ALLOW_EXTERNAL=true及组织网络许可。只验证URL字面含义，不发DNS/探活猜测授权，信任环境代理和重定向均关闭。初始化只做配置校验，真实可用性在首个chat请求验证，未宣称完成原阶段3的启动探活/校准/模型指纹验收。

知情文本cli-chat-v1明确AI、服务端文字处理/保留政策、本地只在内存保存与/exit撤回；yes前不接收候选人回答。完整messages保存system、user、assistant，成功后一次追加本轮双方，失败不污染重试上下文。候选人输入以JSON字符串转义分隔并去联系方式后发送，不接受用户伪造system。输出需为一个短问题，禁止受保护属性/系统标记泄露/联系方式；失败仅修复一次后明确报错。没有打分、默认分、招聘建议或自动淘汰逻辑。

STT接口使用方式为`conversation.answer(final_text)`；在生产接入时仍须沿用已有知情同意、确认final文本、持久会话和固定核心题门禁。这个CLI不是生产面试会话替代品。

## 实际执行

明确fake模式，以授权合成文字输入yes、两条回答与/exit，退出码0。终端实际输出：

```text
当前模式：fake 本地演示（没有调用真实模型）
面试官：你好，我是本次AI技术面试官。我们先从实践经历聊起：你最近亲自负责的一个技术项目是什么？
面试官：这项实现中，你个人做出的关键技术决策是什么？
面试官：你用什么测试或指标验证这个方案的效果？
```

这只证明闭环接线，不表示fake理解候选人语义。真实模型没有被调用、未产生模型请求费用，未将已有Key放入工具输出。

## 回归

精确命令：

```powershell
node scripts/python.mjs -m ruff check --config apps/api/pyproject.toml scripts/test_chat.py
node scripts/python.mjs -m mypy --config-file apps/api/pyproject.toml scripts/test_chat.py
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

环境显式fake LLM、STT auto且清空HTTP地址/模型、TTS local、禁用Edge和Next遥测，缓存pnpm11.25.0，Python3.11.9。所有非fake客户端测试均注入MockTransport，原conftest继续阻断真实httpx传输。

```text
All checks passed!
Success: no issues found in 26 source files
Test Files 18 passed (18)
Tests 243 passed (243)
collected 187 items
179 passed, 8 skipped, 1 warning in 27.31s
Compiled successfully in 3.9s
Generating static pages (5/5)
```

旧→新：pytest收集142→187、通过134→179、PG跳过8→8；TS243→243。没有删除、放宽断言或增加skip。警告仍是pytest缓存WinError5，未隐藏。脚本单独mypy检查1文件通过；应用mypy26文件。本轮无前端/线上API变化，不宣称重新跑过E2E、Docker或托管CI。

## 限制与下一步

真实模型握手、问答质量、计费、完整模型指纹/上下文上限、真实提示注入鲁棒性与离线评分校准均未验收。10条攻击用例验证编码/角色边界与响应检查，不是实际模型免疫结论。后续用户配置并明确调用real CLI后，再以获授权合成对话检查端点；网页接入与原PG16/Docker/校准任务未因此完成或取消。
