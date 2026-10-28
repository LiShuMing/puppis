# SPEC-0003：本机可用的 Evidplane 产品平台

- 状态：done
- 日期：2026-10-28（Asia/Shanghai）
- 需求来源：用户要求重新 review，并在当前机器上构造可以使用的产品平台。
- 关联：SPEC-0001、SPEC-0002、整体评审；本 spec 扩展原 L0 的本地操作界面，不扩展为公网 SaaS。

## 问题与目标

当前仓库提供 ingest 脚本和 MCP，但没有让用户在浏览器中接入、浏览和检查证据的产品入口。目标是在当前机器以一个命令启动单用户工作台，完成“导入自己的资料 → 搜索 → 阅读证据/回源 → 生成带引用的工作上下文 → MCP 复用同一数据”的闭环。

## 建议交付范围

1. **本地 Web 工作台**：默认 `http://127.0.0.1:8765`，中文界面，自适应桌面/窄屏；启动、停止、健康检查有明确命令。
2. **概览**：真实证据数量、来源分布、最近导入、空库引导；演示数据必须显式导入并有清晰标识。
3. **证据库**：全文搜索、来源筛选、时间窗口、列表与详情；展示正文、来源、采集时间、provenance，提供原文链接。
4. **上下文工作台**：work 模板、天数、预算；展示 pack 正文与逐条引用，引用可在平台内打开原证据，支持复制正文。
5. **接入**：支持粘贴/导入用户的文本资料、本地 JSON fixture、Notion 已配置授权源的手动同步。token 由服务端环境读取，浏览器不接收或保存 token。无真实源凭据也能通过自己的文本资料完成闭环。
6. **MCP**：现有 search/get/pack 继续复用同一 DB；空库不自动混入假证据，演示通过明确操作导入。
7. **本地运行文档**：启动脚本、数据位置、备份和恢复限制、MCP 配置、重启后数据保留的验证。

非目标：公网发布、远程访问、登录/多租户、后台自主同步、OAuth 授权页面、向量/LLM 生成、云部署和完整 raw-only 灾难恢复。暂不提供删除/改写历史证据的 UI。

## 架构方案

- 保留现有 connectors / lake / serve 三层；MCP Serve 继续是查询适配器。
- 新增 `console/` 作为本地产品入口：HTTP routes + 静态 HTML/CSS/JS + `service.py`。service 负责调用 connector 与 Lake 编排导入，HTTP 层不直接操作 SQL/源 token。新增这一包的理由是让需要写入的产品操作有独立归属，不迫使 MCP Serve 承担导入职责。
- Lake 扩展受控的来源/统计查询和文本入库入口；所有持久化仍由 Lake 负责。console 不拥有第二套数据库。
- 采用已安装 MCP 环境中的 Starlette/Uvicorn 能力，并将应用直接使用的依赖显式声明；前端采用无构建步骤的原生 HTML/CSS/JS，减少本机运行依赖。
- 更新架构检查，约束 routes → service → connector/lake，禁止源适配器依赖 console/serve，禁止 Lake 调用平台接口。

## 数据与契约

- 新用户资料默认存于仓库忽略的数据目录，DB/raw 路径通过环境配置；所有测试使用独立临时目录。
- 手动资料得到稳定内部 item_id、`connector_id=manual`、`source=export`；只有用户提供 URL 时才显示回源链接，不伪造平台来源。
- 真实源接入保留平台 item_id/URL 和 provenance；有效期与人工审核标志必须保真。
- 原始内容更新需保证旧版本 hash/URI 可校验。SPEC-0002 的内容寻址方案作为前置，具体路径编码/原子保证需在实施前解决并纳入确认。
- 导入有大小/数量上限与明确错误；Notion 同步展示成功/失败数和部分成功，不把失败显示为完整同步。
- API 使用结构化 JSON 和适当状态码。输入边界包括空查询、未知 ID、无效预算/天数、无凭据和损坏文件。
- 仅监听 loopback；写操作校验同源与请求格式；源正文按文本显示，不能执行 HTML/脚本。界面不暴露密钥或服务器 traceback。

## 兼容、迁移与回滚

保留现有 MCP 工具名及主要返回字段、DB 环境变量别名。需要 schema 新字段时采用幂等迁移并保留旧数据。启动前不覆盖现有 DB；演示与测试永不清空用户库。

原始对象追加保存；回滚应用不删除历史 raw。提供 DB/raw 本地备份说明与实际验证；完整 raw 重建另列 spec，不能声称已经完成。

## 验收标准

| AC | 可观察结果 | 验证 |
|---|---|---|
| AC-1 | 一条命令启动，健康检查通过，返回本机可访问地址 | 实际启动 + HTTP 检查 |
| AC-2 | 空库呈现空状态，不自动写入演示证据 | 空 DB API/UI 测试 |
| AC-3 | 导入自己的文本后可搜索、阅读，重启后仍存在 | HTTP 端到端 + 重启验证 |
| AC-4 | 搜索/筛选/详情一致；错误输入有可理解的提示 | API 测试与浏览器交互 |
| AC-5 | pack 满足估算预算，每个 cite 可打开对应 item | API + 浏览器交互 + MCP smoke |
| AC-6 | 原始版本/provenance 不丢失；更新幂等 | local/fake S3 + ingest 回归 |
| AC-7 | 接入状态不泄露 token；未配置 Notion 明确引导 | 无凭据/mock 测试 |
| AC-8 | 运行时仅监听本机，写请求同源限制，正文无 HTML 执行 | 启动参数与安全边界测试 |
| AC-9 | 原项目单元、L0 smoke、架构检查通过；已有产品能力不回归 | 完整离线验证 |
| AC-10 | 提供可重复启动、备份、MCP 使用说明，平台实际保持运行 | 当前机器现场验证与交接 |

## 实施顺序

先完成二次评审与治理检查 → 确认本 spec 与 raw 前置决策 → 数据完整性/显式 demo → service/API → 界面 → 端到端和重启/备份验证 → 在本机启动并交付地址。

## 未决问题

负责人确认上述本地单用户范围后，实施期间可自主决定页面布局、内部函数与局部实现。若需要公网访问、多用户或其他真实数据源，应先补充 spec。

## 确认记录

2026-10-28，负责人通过本会话确认：“按此 spec 实施，技术细节自主处理”。确认覆盖本机单用户 Web 平台、raw 完整性前置、显式演示、共享 MCP 与上述验收；允许在该范围内自主处理技术细节。

实施决策：新 raw 对象键使用完整 item_id SHA-256 与内容 SHA-256，消除路径别名与长度问题；Local 以临时文件 + 原子 hard-link 发布；OpenDAL 使用 `if_not_exists=True`，冲突时读回校验，不支持时失败，不退化为覆盖。数据库采用增量字段迁移，保留旧 URI。全文过滤按 SQLite julianday 比较，避免混合时区字符串排序错误。依赖收紧到当前实测的 MCP 2.x 及已安装 Web 运行时；包显式携带 schema、fixture 与静态资源。

## 交付与验证记录

2026-10-28 完成。本机平台运行于 `http://127.0.0.1:8765`，正式库保持空库；所有验收写入临时数据，未导入用户私人资料。

| AC | 实际验证结果 |
|---|---|
| AC-1 | `scripts/workspace.py start/status`：启动与健康检查通过 |
| AC-2 | HTTP/MCP 单元 + 浏览器空库检查通过，无自动 seed |
| AC-3 | 浏览器手动导入、检索、实际终止/重启服务后条数保持；临时数据 |
| AC-4 | HTTP 边界、来源过滤、时区排序/分页、中文子串；桌面/390px手机四页面无横向溢出 |
| AC-5 | 预算/cite/get 单元与 L0 MCP registry smoke；浏览器打开引用通过 |
| AC-6 | SPEC-0002 验证；完整 provenance/有效期、旧库升级、raw hash/URI 保真通过 |
| AC-7 | Notion 无配置/密钥不泄漏/部分同步结果与错误记录 mock 验证通过；真实源未联调 |
| AC-8 | loopback 启动、Host/Origin/JSON/2MB限制、CSP；浏览器恶意 HTML 文本不执行、零外部请求/JS错误 |
| AC-9 | `pytest -q`：42 passed；L0 9组通过；AST检查19文件通过 |
| AC-10 | LOCAL_PLATFORM.md；DB+raw备份/校验/恢复到新目录测试通过；本机后台服务保持运行 |

补充：使用锁定运行依赖在全新临时 venv 安装 wheel，从仓库外运行，完成手动/演示导入与查询，schema/fixture/static 资源有效。运行版本：Python3.12.3、MCP2.3.0、OpenDAL0.47.12、Starlette1.10.0、Uvicorn0.54.0；浏览器验收使用 Playwright1.58.0 / Chromium145。

验证命令：`.venv/bin/python -m pytest -q`、`python3 scripts/check_architecture.py`、`EVIDPLANE_RAW_BACKEND=local .venv/bin/python scripts/smoke_l0_quality.py`、`python3 scripts/smoke_console_browser.py --screenshots <临时目录>`、`node --check console/static/app.js`、`git diff --check`。

限制：Notion/OSS 真实联调、raw-only replay、系统开机自启未执行/实现。后台进程已启动；机器重启后使用 start 命令恢复服务。产品范围变动继续走新的 spec 确认。
