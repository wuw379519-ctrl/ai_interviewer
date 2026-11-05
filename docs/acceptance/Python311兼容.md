# Python 3.11兼容记录（2026-11-05）

## 变化

- `provider.py`将Python3.12的`class Generation[T: Contract]`改为3.11可解析的`Generic[T]`，类型约束与评分行为保持。
- `pyproject.toml`最低版本>=3.11，Ruff py311、mypy3.11；新增一项在线源码3.11语法契约测试。
- `scripts/python.mjs`校验实际解释器；优先Shell配置、.venv311、.venv，再PATH，最低3.11；隔离生产脚本同样优先.venv311。
- CI两处Python配置与API Dockerfile改为3.11。AGENTS/README/.env.example更新当前使用要求，历史3.12验收不改写。
- `constraints-python311.txt`固定语音传递依赖NetworkX3.6.1；`requirements-python311-overlay.lock`记录本机补充依赖的版本和哈希。没有改变业务数据库或API契约。

## 实际环境与授权

用户指定的解释器实测`Python 3.11.9`；旧仓库.venv实测3.12.14。原3.11全量测试首次在conftest导入失败，原始错误为`ModuleNotFoundError: No module named 'cryptography'`。没有将其当成语法成功或通过，也没有跳过既有断言。

仅查询PyPI元数据后列出补充包体积，用户明确允许后下载11个wheel共29,324,820字节，全部SHA-256验证。新建`.venv311 --system-site-packages`，使用`--no-index --no-deps --require-hashes`只向新环境安装；全局Python和旧.venv不改，没有重装torch或下载模型。清单与体积见[evidence/python311-package-plan.json](evidence/python311-package-plan.json)。

复用原3.11包时，Pydantic为2.14.1、pytest9.1.1，不是完整锁文件2.14.2/9.2.0的重建环境；本次明确验证该真实组合。新机仍需完整、匹配CPython3.11 ABI的离线wheel集合。`.venv311`及所有安装包/权重不进Git。

## 验证命令

```powershell
node scripts/python.mjs --version
node scripts/python.mjs -c "import sys; print(sys.executable)"
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm test:e2e
pnpm test:production --skip-build --stop
```

默认实际输出`Python 3.11.9`，解释器为仓库`.venv311/Scripts/python.exe`。最终四项全部通过；显式fake/禁用真实STT与Edge，Next遥测关闭，使用缓存pnpm11.25.0，没有下载包管理器。生产构建NEXT_DIST_DIR=.next-build，隔离验收使用--skip-build --stop，不修改开发资料。

```text
Python 3.11.9
All checks passed!
Success: no issues found in 25 source files
Test Files 18 passed (18)
Tests 243 passed (243)
collected 142 items
134 passed, 8 skipped, 1 warning in 46.57s
Compiled successfully in 4.6s
Generating static pages (5/5)
16 passed (5.3m)
```

Python测试相对上轮实跑133→134通过、收集141→142，新增最低版本语法契约1项；TS243→243，E2E16→16。没有删减/放宽断言或新增跳过。8项跳过仍因未配置可丢弃PG16；警告为pytest缓存目录WinError5权限问题，保留并如实报告。

E2E后端进程实际ExecutablePath为用户的Python311安装，验证原生3.11；不是仅改变显示文本。隔离生产也走新.venv311优先级，在独立SQLite完成13题、8道评分题、4维原话证据、token5642、身份/报告/会话重启恢复与测试候选人删除，退出后停止自建服务。私有记录`.data/production-ed86d82d-4c94-4967-8cc5-37d437026c57/result.json`不入Git；无真实设备/模型/云ASR依赖。

首次3.11全量测试实际为132通过/8跳过/4个setup/teardown错误；已停止流水线，没有继续构建。单独复现保存在`.data/acceptance/python311-first-error.log`，定位到pytest.runner._update_current_test_var写入超大参数名称时的`ValueError: the environment variable is longer than 32767 characters`。仅给test_speech_provider/test_stt_service中的两组字节参数加短ids，不改变输入、数量、断言或音频边界，没有升级pytest来隐藏问题。随后重跑全量检查。

此前还在原3.12环境执行四项检查全部通过：Vitest243、pytest收集142/通过134/8个PG跳过，mypy25文件；这是保留向上兼容的附加结果，不代替3.11实跑。

## 真实Whisper手工复核

与CI分离，复用此前本地Huihui合成固定句的WAV、MP3，Python连接被阻断，不调用任何远程服务。原生3.11环境真实加载已有base.pt，初始化19,231ms；WAV转写4,921ms、MP3转写16,872ms，均返回`你好,我負責研究項目的核心實現,通過實驗驗證結果。`。不是两份独立真实面试样本，也未声明CER达标。OMP_NUM_THREADS=4仅用于此手工进程，未改应用全局线程参数。

私有结果在`.data/acceptance/python311-stt-0902ae5dbf7c4d9d85d314ed70c39c4a/result.json`，合成资料不入库/不入Git。Edge仍关闭，无实际微软请求。

## 限制

Docker/PG16和托管CI未运行，不因配置变为3.11而称其通过。ASR十段样本/CER、持久续传、离线LLM校准等原任务仍待后续验收。
