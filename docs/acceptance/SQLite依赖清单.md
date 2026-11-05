# SQLite依赖清单（阶段0）

| 项 | 现状、处理与验收状态 |
| --- | --- |
| AUTOINCREMENT | 未使用；UUID4由应用生成，保留。 |
| PRAGMA | database.py连接适配器内foreign_keys=ON和busy_timeout=10000；保留为SQLite实现细节，业务禁止使用。 |
| INSERT OR REPLACE | 未使用，保持禁止，避免隐式删行破坏证据FK。 |
| ON CONFLICT | 当前无业务catch IntegrityError；默认策略是查后插。阶段1用两方言相同冲突契约，不吞掉其他约束错误。 |
| datetime('now')/时区 | 未使用datetime函数；初始迁移CURRENT_TIMESTAMP及julianday('now')用于SQLite门禁。应用now()为UTC，但SQLite读回naive且非UTC偏移绑定存在失真风险，需适配器统一UTC；冻结迁移保留。 |
| JSON1 | 未用json_extract等函数；数据Python校验后存储。PG物理列已经JSONB，SQLAlchemy当前通用JSON映射应对齐JSONB variant并测试嵌套/null/bool语义。 |
| BOOLEAN/DATETIME亲和性 | 初始SQLite迁移使用BOOLEAN/DATETIME；保留物理兼容，应用显式规范，PG对应boolean/timestamptz，禁止依赖SQLite隐式转换。 |
| 事务隔离 | SQLite为单连接StaticPool+RLock；PG事务用advisory lock保守串行。不要声称两者隔离级别相同；需回滚/重复写/可见性契约。 |
| ILIKE/大小写 | 未使用ILIKE/LIKE检索；未来须明确Unicode比较契约，当前不引入查询。 |
| 并发写锁 | SQLite busy_timeout及进程锁，不能推论多实例安全；PG后置真并发测试不可豁免。 |
| 方言触发器 | 初始迁移instr/julianday/RAISE为SQLite专用安全门禁；保留，PG有各自对应触发器；共同契约验证同意/原文证据，而不强行复用DDL。 |
| 离线历史导入 | snapshot.py含BEGIN IMMEDIATE和触发器暂停/恢复；限显式离线空库导入，需收敛到持久适配器，不能进入在线业务。 |

此为勘察状态，不代表阶段1已消除。后续逐项补实测结果，不修改已应用的0001_initial.sql或既有PG迁移。

## 阶段1状态（2026-11-04）

- AUTOINCREMENT/REPLACE/JSON1/ILIKE：原本未使用，继续禁止，无需删除冻结DDL。
- PRAGMA与SQLite写锁：保留在SQLite连接适配器；在线业务不再持有或直接调用驱动连接。
- ON CONFLICT：默认策略改为repository.insert_if_absent，SQLite与PG各编译原生ON CONFLICT DO NOTHING，不catch IntegrityError、不隐式替换；冲突后事务可继续由同套契约断言。
- UTC：新增UTCDateTime绑定时归一UTC，读SQLite的UTC naive值明确标为UTC，PG读值归一UTC；调用方传naive时间显式拒绝。SQLite内存/文件偏移往返已通过，不声称PG已执行。
- JSON：PortableJSON在PG使用JSONB并显式拒绝非有限数字、零字符和非字符串键，嵌套对象、数组、布尔和SQL NULL契约通过SQLite；与现有JSONB/DATETIME/timestamptz物理DDL的编译契约通过。
- 所有在线持久化通过StorageSession与SQLAlchemyRepository/Database.unit_of_work；业务保留可移植SQLAlchemy表达式，未引入另一查询语言，禁止原生SQL字符串/execute由AST契约守护。冻结迁移与显式离线导入使用适配器内原生SQL；snapshot不再执行driver_sql。
- 事务隔离差异保留并公开，不把进程RLock当成跨实例保证。事务回滚、JSON、UTC、唯一冲突为双库同套契约；PG未配置时明确skip，一条命令pnpm test:storage-contract。
- 没有新增或修改物理DDL、现有数据或迁移文件；因此本增量无需新增数据迁移，应用提交可整体回退。既有迁移缺少down仍是阶段4前的未通过项，不被本次类型适配掩盖。
