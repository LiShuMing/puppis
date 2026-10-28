# 架构决策记录

只记录已存在的基线选择或经负责人确认的决定。探索方案放入变更 spec，替代决定时保留旧记录和替代链接。

| ID | 决定 | 原因与代价 | 依据 |
|---|---|---|---|
| D001 | Python 3.12+，connectors / lake / serve 单仓三包 | 快速完成个人 Evidence + MCP；保持边界，不提前拆服务 | `docs/SPEC.md` §2、§6.1；`pyproject.toml` |
| D002 | SQLite + FTS5 为 L0 派生索引 | 单机简单；向量/其他内核须有评测收益 | `docs/SPEC.md` §6.2；`lake/schema.sql` |
| D003 | 本地 raw + OpenDAL S3 后端 | 复用对象存储抽象，兼容现有环境变量；当前 raw 版本完整性仍有缺口 | `b69f82f`；`lake/raw_store.py` |
| D004 | stdio MCP，查询公共入口 `lake.query` | Serve 保持薄适配；`lake.api` 留作兼容；db/seed 导入已移除 | `lake/api.py`；SPEC-0003 |
| D005 | 先确认单次 spec，再实施，再按验收验证 | 避免 Agent 自行扩展产品决策；通过 AGENTS、模板、PR review 与检查配合执行 | 用户 2026-10-28 请求；SPEC-0001 |
| D006 | 完整 item_id hash + 内容 hash 寻址 raw，条件发布 | 旧版本不会被更新覆盖；不支持条件写则失败。旧 URI 保留，已丢字节不能恢复 | SPEC-0002/0003；负责人确认并授权技术细节 |
| D007 | 本机 Console + 应用 service；原生前端、Starlette/Uvicorn | 复用现有 Python 数据面；routes 不直接组合平台与 SQL；只监听 loopback | SPEC-0003；负责人确认 |

未来记录至少包含：决定、理由、替代方案、兼容/迁移代价、确认依据、对应 spec。替代方案与数据迁移细节见各 spec。
