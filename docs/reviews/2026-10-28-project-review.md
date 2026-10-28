# 项目整体评审与本机产品复评

日期：2026-10-28（Asia/Shanghai）。初始基线 `b69f82f`；范围覆盖全部 Python 模块、schema、入口脚本、测试、产品/部署文档和冻结召回集。没有连接真实 Notion/Google/OSS，没有验证远端部署状态。

## 结论与建设方向

项目已具备 connector → raw/SQLite → search/get/pack → MCP 的离线主链路，适合继续建设个人工作上下文平台。现阶段应先补证据完整性、显式数据接入和可操作入口，再考虑检索内核/云部署。单元与 smoke 通过并不等于满足“raw 不可变、派生可重建”的产品目标。

按照负责人确认的 SPEC-0003，本次形成 loopback 单用户 Web 工作台，复用现有 Lake/MCP；新增 `console.service` 负责导入编排，HTTP routes 不直接操作 SQL/connector。没有拆微服务或增加第二套前端运行栈。

## 发现与处理状态

以下定位指初始基线文件/行，可用 `git show b69f82f:<path>` 查看；本次修复后行号会改变。

| ID / 优先级 | 触发、影响与证据 | 当前处理 |
|---|---|---|
| R1 / P1 | 同月同 item 内容更新时，local `lake/raw_store.py:103–109`、S3 `:252–267` 覆盖同一 URI。隔离 ingest 两版本得到 2 个 hash、1 个 URI、1 个 hash 校验失败；旧测试还要求覆盖同路径 | 已修：item hash + 内容 hash 分版本；Local 原子发布；S3 条件写；新增旧字节、并发、损坏/冲突和拒绝降级测试。已覆盖的历史字节无法凭 hash 恢复 |
| R2 / P1 | SPEC §3.5 要求 raw/export 可还原，但仓库无 replay/export/restore；raw payload 无完整归一化 envelope，Evidence 的 source_id/派生信息依赖 DB | 部分覆盖：新增 **DB + raw** 备份/校验/迁移恢复。raw-only replay 与完整灾备仍未实现，不宣称索引可以直接删除重建 |
| R3 / P1 | `serve/mcp_server.py:38–45` 在工具调用前对空库自动 seed；`lake/seed.py` 把假数据写成 platform。空库/清空后查询可生成假证据；Serve 同时依赖写库/seed | 已修：移除自动 seed 与跨层导入；演示为显式动作，并在列表/详情/cite 标记；CLI 假 seed 也标为 export/demo。MCP 列来源改为真实入库记录 |
| R4 / P1 | Notion `_list_blocks` 的嵌套子块失败被 `except httpx.HTTPError: pass` 吞掉（`:553–558`），页面仍作为完整成功返回。Calendar CLI 对拉取错误也无统一 errors/ 语义 | 已修嵌套失败传播到页面级隔离；Console 显示部分同步并持久化简化错误。Calendar 全链路错误契约、增量 cursor/删除同步仍待后续 spec |
| R5 / P1 | Evidence 有 valid_from/to 与 provenance dict，`lake/ingest.py:96–131` 只持久化 source 字符串；`lake/query.py:get` 硬编码 human_reviewed=False，trust 总为1。隔离验证审核 True 入库后变 False，有效期消失 | 已修新数据：增量字段迁移、完整 provenance/有效期/hash/URI、agent 未审核降权与 get 回查。历史已丢字段不能自动补回；pack 仍是最新优先，非信任排序 |
| R6 / P2 | `lake/query.py:search/pack_work` 按 ISO 文本排序、LIMIT 后 Python 过滤；混合时区可能排错或漏掉窗口内证据。unicode61 对中文短词无分词支持 | 已修：julianday 过滤/排序、查询分页；中文用参数化子串匹配。不是语义搜索；中文 fallback 大库需后续性能评测 |
| R7 / P2 | `pyproject.toml` 声明 mcp>=1，而 Serve 使用 2.x 的 MCPServer API；依赖未锁定；schema/fixture/static 未显式声明包资源 | 已收紧实测 MCP/Web 依赖范围、生成运行/开发锁文件、声明包资源并检查 wheel。未验证所有 Python/OS 组合；锁文件基于当前 Linux/Python3.12 |
| R8 / P2 | 测试仅 8 项 raw-store；核心行为散落在 smoke；smoke_lake/pack force seed 默认库有误用风险；冻结召回集仅3页面/15查询，不能代表真实效果 | 已扩展 HTTP/完整性/架构/备份与浏览器验收；一键隔离 browser smoke。保留旧 smoke 并要求显式临时目录。fixture 时钟老化与全仓 lint 债务仍需治理 |

## 基线验证

- Python 3.12.3，独立 `.venv` 安装项目；一次下载超时，重试后成功，未修改全局环境。
- 初始单元：8 passed。初始离线 L0 smoke：通过9组检查，含 mocked HTTP，不是真实平台调用。
- 复现 R1：`raw_versions=2, unique_uris=1, hash_mismatches=1`。
- 复现 R5：请求 `human_reviewed=True`，get 返回 False；`valid_from` 不在返回值；agent trust=1.0。
- 原全仓 Ruff 基线有16条问题（包含路径修正后的 E402、unused imports/variables 等）。本次不进行无关批量格式化。
- 对初始提交单独构建 wheel，确认 `lake/schema.sql` 未打包、JSON/ICS fixture 为空；本次声明包资源后检查这些文件与前端资源均存在。
- 冻结 FTS baseline 为3页面、15查询：已有报告 hit@1=1.0 只适用于这组样本，不能外推生产召回。

## 本次产品与规则复评

1. **规则能执行**：根 AGENTS → 架构 → spec 模板/索引 → 负责人确认 → 构建/验收 → PR 交接。确认依据真实记录，不把 Agent 自己写的 approved 当作用户授权。
2. **依赖边界可检查**：静态 AST 覆盖相对/绝对和函数内导入，含违规负例；Serve 的旧 db/seed 例外随修复删除。Console routes 仅能依赖自身包，service 才能编排数据面。
3. **产品有实际闭环**：手动资料/JSON/显式演示 → 搜索/筛选/详情 → pack/cites → MCP 同库；空库是正常状态。Notion 授权通过服务端环境配置。
4. **操作可逆且数据保留**：start/stop/status，DB+raw 备份校验与恢复到新目录；原始版本追加保存。恢复不会覆盖正在使用的库。
5. **本地边界明确**：只绑定 loopback，Host/Origin/JSON 写入校验、输入大小限制、正文按文本渲染、无外部前端资源；这些检查不等价于公网服务安全设计。

最终验证：42项单元通过；9组 L0 smoke 通过；19个运行时 Python 文件架构检查通过；浏览器完整流程与实际进程重启通过；全新 venv 在仓库外运行已安装 wheel 通过；JS 语法、文档链接和 diff 检查通过。CI 仅完成配置，未在远端运行。细项见 SPEC-0001/0002/0003 交付段，后续变更继续遵循 spec 确认门槛。

## 下一阶段

优先为真实个人资料建立更有代表性的检索集，再单列 raw envelope + replay spec、可靠增量/删除同步、测试固定时钟。平台暂不扩展为多用户或公网服务。真实源/OSS端到端验证在有对应配置和任务授权时单独记录，不能用 fake/mock 结果代替。
