# 变更 Spec 索引

[产品 SPEC](../SPEC.md) 定义长期边界；本目录记录每次变更的可实现契约。流程见 [DEVELOPMENT](../DEVELOPMENT.md)，新建使用 [TEMPLATE](TEMPLATE.md)。

| 编号 | 主题 | 状态（以正文为准） | 范围 |
|---|---|---|---|
| [0001](0001-agent-workflow.md) | Agent 规则与架构流程 | done | 规则、架构、评审、检查与 CI |
| [0002](0002-raw-versioning.md) | Raw 版本完整性 | done | 作为获准本机平台的前置修复 |
| [0003](0003-local-product-platform.md) | 本机产品平台 | done | 负责人确认后建设；本机已运行 |
| [0004](0004-evidence-intelligence-roadmap.md) | 证据智能平台技术路线 | draft | 已完成设计；新增架构与阶段实施待确认 |

状态：`draft → approved → implementing → done`；`superseded` 必须链接替代 spec。`done` 只表示该次验收已完成，不能覆盖全项目遗留问题。

后续建议顺序（不是开工授权）：

总体设计见 [技术路线](../TECHNICAL_ROADMAP.md)，以 SPEC-0004 的 S0 + S1 为下一项实施候选。下列问题继续保留，并纳入阶段验收。

1. R2：raw envelope + raw-only replay/export，先确认恢复契约；当前已有 DB+raw 备份恢复。
2. R4：增量 cursor、删除同步、Calendar 错误契约，以及真实 Notion/OSS 联调。
3. R8：固定测试时钟、扩充真实工作检索集与全仓 lint 整理。
4. 中文检索规模化性能、pack 信任/信号排序，有代表性评测后再扩展。

问题编号见 [整体评审](../reviews/2026-10-28-project-review.md)。每项实施前建立对应 spec；不要因为进入此列表就视为已批准。
