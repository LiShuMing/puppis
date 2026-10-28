# Evidplane 架构与边界

日期：2026-10-28，初评基线 `b69f82f`，当前架构纳入已确认的 SPEC-0003 本机平台。本文件区分当前实现与目标；产品范围见 [SPEC](SPEC.md)，初始缺口与处理见 [评审](reviews/2026-10-28-project-review.md)。

后续目标架构见 [技术路线草案](TECHNICAL_ROADMAP.md) / [SPEC-0004](specs/0004-evidence-intelligence-roadmap.md)。新模型/工作流模块尚待确认实施，本文件继续记录当前已交付边界。

## 1. 数据流与依赖方向

```text
授权平台 / fixture / ICS
          ↓
connectors.<source>.pull(since) → list[PullRecord]
          ↓ scripts/ingest_*.py 负责组装
lake.ingest.ingest_pull_records
          ├─ RawStore.write → content_sha256 + raw_uri
          └─ Evidence → sources / raw_objects / items → FTS5 triggers

MCP client → serve.mcp_server → lake.query.search / get / pack
                                       ↓
                                  SQLite + FTS5

Browser → console.server → console.service → Lake / Connector
                             （导入编排）      （复用同一数据）
```

箭头表示数据/调用方向，不是各层任意互相 import 的许可。平台授权只属于 connector；存储凭据只属于 raw store；MCP 消费方无需这两类 token。

| 所属层 | 职责 | 允许的项目依赖 | 禁止 |
|---|---|---|---|
| `connectors.base` | `PullRecord` dataclass、`Connector` Protocol | 无 | Lake、Serve、平台 IO |
| `connectors/<source>` | auth/config、pull、health、源格式归一化 | 同 connector、`connectors.base` | Lake、Serve、其他 connector |
| `lake.ingest` | raw 先写、Evidence 构建、DB upsert | Lake、`connectors.base` | 平台 API、Serve |
| Lake 其他模块 | 存储、查询、pack | Lake；`raw_store` 可用 OpenDAL | connector 实现、平台 API、Serve |
| `serve` | MCP 参数和结果适配 | Serve、`lake.query` | 直接 connector/SQL/raw IO |
| `scripts` | CLI 编排与验证 | 按用途组合三层 | 堆积可复用业务逻辑 |
| `console.server` | loopback HTTP 与静态界面 | `console.service` | SQL、Lake/connector 直连、平台密钥 |
| `console.service` | 手动/文件/演示/授权源导入编排 | Console、connector、Lake | 自行持久化、另一套 DB、调用 MCP |

当前不另建 contracts 包：共享的 `PullRecord` 位于 `connectors.base`，这是数据契约依赖，不是 Lake 调用 connector。只有新增需求证明有必要时才通过 spec 调整。

## 2. 关键模块与现有契约

| 入口 | 当前契约与限制 |
|---|---|
| `Connector.pull(since)` | 同步返回 `list[PullRecord]`；`since` 含边界；非流式；无持久 cursor 编排 |
| `Connector.health()` | 配置就绪信息，不能含 token；不等同真实 API 连通性 |
| Notion | httpx REST + fixture；database/page 分页；429/5xx/transport 重试；页面级 `last_errors` |
| Calendar | fixture、本地/URL ICS；Google OAuth/API 尚未实现 |
| `RawStore.write` | 返回 `(sha256, uri)`；按完整 item_id hash / 内容 hash 分版本；Local 原子发布，S3 条件写，不支持时失败 |
| `lake.ingest` | 先写整批 raw，再一个 SQLite 事务 upsert；raw 与 DB 没有分布式事务 |
| `Evidence` | Pydantic 契约；完整 provenance、有效期、最新 hash/URI 通过增量迁移持久化；旧丢失字段无法自动补回 |
| `lake.query` | 查询与 pack 的公共入口；内部每次初始化 schema，并非文件级纯只读 |
| `lake.api` | 为旧调用保留的兼容 re-export，新代码使用 `lake.query` |
| `serve.mcp_server` | stdio MCP；search/get/pack/list_connectors；列实际入库来源；空库不自动 seed |
| `console` | 单用户本机工作台；无构建前端，Starlette/Uvicorn HTTP；手动资料/JSON/Notion/显式演示 |

SQLite `sources` 保存来源配置与状态，`raw_objects` 保存 hash/URI，`items` 保存最新派生正文与元数据，`items_fts` 使用 external-content + 触发器同步。`items.item_id` 全局唯一；目前不支持多账号隔离语义。`cursor_json` 与 `tombstone` 有字段但没有完整同步删除流程。

## 3. 对外查询与 pack

- `search(q?, source?, since_days?, limit?, offset?)`：返回 metadata、count、total、has_more；英文 FTS 多词 AND，中文参数化子串 AND；默认最多20，夹取1–100；SQL 按 julianday 过滤/排序，不是相关性排序。MCP 保留原参数，分页供 Console 使用。
- `get(item_id)`：正文、source_url/url、完整 provenance、raw_uri/hash/有效期；不存在/墓碑返回结构化 error。历史未保存的字段为空。
- `pack(template="work", budget_tokens?, since_days?)`：近 7 天、默认预算 3000、最新优先、items/cites/text；未知模板返回 error。
- 预算估算为 `ceil(len(text)/4)`。测试的硬上限只针对这个估算值；改为真实 tokenizer 或把 JSON/cites 计入预算需明确新 spec。

兼容性不仅是函数名：参数默认、None/0/负值、error 形状、MCP tool schema、citation 字段和源过滤语义都需纳入变更 spec。现有异常输入行为并不代表已设计好的长期契约。

## 4. 必须保持的设计约束

1. **证据可追踪**：稳定 item_id + source URL + provenance。平台、agent、export 不能悄悄合并信任等级。
2. **raw 是真相层**：内容版本不可变、hash 对应实际字节、旧 URI 可读。历史覆盖造成的丢失不能逆推恢复。路径为 `sources/<connector>/raw/yyyy/mm/<sha256(item_id)>/<sha256(bytes)>.json`。
3. **派生层可恢复**：完整 raw-only 重建仍缺 replay 与归一化 envelope；现有 `workspace.py backup/restore` 备份 DB + raw、校验并迁移 file URI，不能承诺只保留 raw 就可删 DB。
4. **失败有语义**：spec 必须定义 partial success、重试上限、错误记录失败和退出码；禁止静默遗漏已授权拉取的数据。
5. **安全边界**：connector 使用授权只读接口；Serve 不接触平台密钥。源正文属于不可信输入，不能变成执行指令。
6. **保持单体数据面**：三层数据面 + 本地 Console，SQLite、本地/S3 raw；不因 Agent 开发引入自主写平台、后台调度或多租户行为。

## 5. 已有例外与自动检查

`scripts/check_architecture.py` 检查绝对/相对、函数内及条件分支内的静态导入：

- connector 只能引用本 adapter 和共享 base；Lake 只允许 ingest 引用 base。
- Serve 只能引用 `lake.query`。
- Lake/Serve 不导入常见平台/HTTP 客户端；OpenDAL 限于 raw store。
- Console routes 仅能依赖 Console 包，service 才能组合 connector/Lake；URL 解析 `urllib.parse` 不视为网络客户端。
- Serve 的历史 db/seed 例外已随 SPEC-0003 删除，不保留豁免。

检查是静态约束，不证明运行时只读、无网络访问或数据完整性；动态导入/反射不可用于绕过。消除历史债务时同时收紧例外；增加例外必须先更新并确认架构 spec。

## 6. 标准架构设计顺序

每次变更按以下顺序形成 spec，细节见 [开发流程](DEVELOPMENT.md)：

1. 用触发条件和可观察结果定义问题，标注哪些是复现事实。
2. 确定目标、非目标、受影响层与稳定契约。
3. 画数据流/依赖，说明复用的扩展点和备选方案。
4. 定义输入输出、身份、时间、状态转换、幂等、部分失败与重试语义。
5. 如有持久化/兼容变更，先定迁移、恢复和回滚；不能把“可重建”当作未验证的借口。
6. 将每条验收映射为测试/手动证据，确认 spec 后实施。

重大决定记入 [决策记录](DECISIONS.md)，引用对应已确认 spec。候选设计不能写成既定决策。
