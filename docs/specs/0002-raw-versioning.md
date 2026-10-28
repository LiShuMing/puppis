# SPEC-0002：Raw 版本完整性

- 状态：done
- 日期：2026-10-28（Asia/Shanghai）
- 需求来源：整体评审 R1
- 关联：产品 SPEC §2/§4；ARCHITECTURE §4

## 问题与证据

同一 connector、item_id、年月下，内容更新覆盖同一 raw URI。`raw_objects` 保留不同 hash，但旧行的 URI 读出新字节。隔离复现：两个版本、一个 URI、一个 hash 校验失败。现有单元和 smoke 还把相同 URI 覆盖作为预期。

## 目标与非目标

相同内容重拉幂等，不同内容保留独立可读取、可校验的版本；local 和 S3 语义一致；新写入的 raw_objects 必须引用对应内容。

本次不承诺完整重建 DB，不开发 export/replay，不补回已经被覆盖的历史内容，不改变 MCP schema，也不改变 connector 的平台 ID。

## 方案与架构

使用内容寻址：`sources/<connector>/raw/<yyyy>/<mm>/<sha256(item_id)>/<sha256(bytes)>.json`。SHA 对应当前 canonical serializer 产出的实际字节；同月同内容重复写返回相同 URI，不同内容返回不同 URI。跨年月重复内容可有不同 URI，不在本次引入全局去重。完整 ID hash 避免别名、Unicode 和长键问题，不改变对外 item_id。

保留 `RawStore.write(...) -> (sha256, uri)` 接口。Local 用同目录临时文件、fsync 与原子 hard-link 发布，不替换已存在对象。OpenDAL 0.47.12 Python 写接口支持 `if_not_exists=True`；S3 使用该条件写，已存在/条件冲突时读取字节校验，不支持则失败，绝不回退为覆盖。已用 fake operator 和真实 OpenDAL memory 后端验证，真实 OSS 服务能力尚未联调。

备选是对象存储 version_id，但 local 无对应能力且 OSS 行为更依赖服务配置，因此不作为建议主方案。

## 契约与失败语义

- 同月、同 item、同 payload：hash 与 URI 相同，无新增 raw_objects 记录。
- 同月、同 item、payload 更新：hash 与 URI 都不同，两个版本均校验通过，items 更新到最新正文。
- 已存在内容寻址对象字节/hash 不符：显式失败，记录错误，不覆盖证据。
- DB upsert 失败：raw 可保留为未引用对象，不能删除此前成功版本；不宣称跨对象存储与 SQLite 原子提交。
- item_id 用完整 SHA-256 编码，避免 `a/b` 与 `a_b` 碰撞，不改变对外 item_id。

## 兼容、迁移与回滚

已有 DB/raw URI 原样保留，不自动重命名。新 ingest 产生新布局；历史丢失内容无法从旧 hash 逆推恢复，迁移报告必须区分可验证/已损坏/缺失，不生成伪修复。

回滚代码不能删除新版本对象。旧查询可继续读取增量迁移后的原字段，旧 URI 保持不变；不能回滚到旧覆盖写实现后继续写入并声称不可变仍受保证。仓外固定路径依赖未调查，不承诺不受影响。

## 验收标准与验证计划

| AC | 可观察结果 | 验证 |
|---|---|---|
| AC-1 | 相同内容不增加 DB/raw 版本 | local + fake S3 重复 ingest |
| AC-2 | 更新后旧/新 hash 均匹配各自 URI，旧字节不变 | 保存两个 URI 并逐一读取校验 |
| AC-3 | 别名化 item_id 不碰撞，MCP ID 不变 | 包含 `/`、`_`、Unicode 和长 ID 的边界测试 |
| AC-4 | 并发/损坏对象不导致静默覆盖 | 故障注入/并发测试；S3 能力证据 |
| AC-5 | 旧数据可继续查询，更新不破坏旧可用 raw | 旧布局 fixture + DB 升级/回退验证 |
| AC-6 | 单元与 L0 smoke 不再要求覆盖同一路径 | 修改行为断言并运行完整离线验证 |

## 实施计划

先确认路径/并发/兼容决策 → local 与 S3 实现 → ingest 一致性测试 → 更新旧测试与布局文档 → 完整离线验证。真实 OSS 验证单独列明授权与结果。

## 决策收口与验证边界

内容寻址、完整 ID hash、Local 原子发布与 S3 失败关闭均按 SPEC-0003 的授权定案。没有阻塞本机 Local 产品的未决问题。真实 OSS 条件写与仓外调用方属于尚未验证的兼容边界，不以本地测试冒充通过。

## 确认记录

2026-10-28，负责人在 SPEC-0003 范围确认中明确同意优先修复 raw 版本完整性，并授权“技术细节自主处理”。本 spec 作为该平台前置实施；技术取舍见 SPEC-0003 确认记录。

## 交付与验证记录

2026-10-28 完成。AC-1/2：Local/fake S3 幂等与旧字节/hash 校验通过；AC-3：`a/b`/`a_b`、Unicode、长 ID 通过；AC-4：30次/8线程 Local 并发、已有损坏对象、S3 权限/不支持条件写拒绝降级通过，真实 OpenDAL memory 条件写验证通过；AC-5：旧布局 URI/字节保留、旧 schema 增量迁移/旧字段读取通过；AC-6：L0 smoke 的覆盖路径断言已替换为版本校验，并完整通过。

整体 `pytest -q` 42 passed；真实 OSS 未验证，失败关闭策略保持。历史被覆盖的内容无法恢复，完整 raw-only replay 不在本次范围。
