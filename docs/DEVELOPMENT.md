# 开发流程：Spec → 确认 → 构建 → 验证

适用于人和 Agent。入口规则见 [AGENTS.md](../AGENTS.md)；产品范围见 [SPEC](SPEC.md)。

## 1. 阶段与产出

| 阶段 | 必要产出 | 进入下一阶段的条件 |
|---|---|---|
| 发现 | 需求/复现、相关代码、影响和基线 | 问题可描述，未知项已列出 |
| Spec | `docs/specs/NNNN-name.md`，含范围、设计、验收、验证与回滚 | 可供负责人评审；阻塞决策已明确 |
| 确认 | `approved`，记录谁在何时以何种会话/PR 表述同意哪个范围 | 确认真实存在，不能由 Agent 自行填写“已同意” |
| 构建 | `implementing`；小步实现与行为测试 | 变更落在已确认范围；新增范围返回 Spec |
| 验证 | AC 到实际命令/证据的映射，兼容/迁移结果 | 相关检查通过，阻塞均解决 |
| 交付 | `done`；同步架构/操作文档，交接剩余风险 | 按任务要求交付 diff/PR；部署遵循已有授权 |

已确认 spec 内的普通实现选择不需要反复询问。负责人在会话中已经清楚给出范围、行为和验收时，可以先把这些要求记入 spec 并引用确认依据，再继续执行；如 Agent 增加影响数据/兼容/产品行为的选择，仍需对新增选择确认。

spec 草案不是开工许可。等待确认期间可继续审阅和隔离验证，不能先改产品实现。紧急修复也可使用精简 spec，但必须包含触发条件、预期行为、验证与确认依据。

## 2. 编写与审查 Spec

从 [模板](specs/TEMPLATE.md) 复制，以索引下一个编号命名；修改已有能力时先查原 spec，避免冲突。产品级目标变更同步 `docs/SPEC.md`；单次设计不必不断重写整份产品规格。

架构审查顺序：

1. **问题**：谁在什么输入下得到什么错误结果？用复现支持，别把猜测写成事实。
2. **范围**：目标、非目标、涉及层；哪些行为和契约会改变？
3. **方案**：复用哪一扩展点？数据流、依赖方向、备选方案和取舍是什么？
4. **数据**：身份、源链、hash、时间/时区、provenance、状态和幂等如何保持？
5. **失败**：部分成功、重试、超时、错误记录失败、退出码和恢复如何处理？
6. **兼容**：旧参数/环境变量/DB/raw/引用如何兼容？如何迁移、校验、回滚？
7. **验收**：用 `AC-1` 等编号描述可观察结果，每项对应验证证据。

只涉及内部局部修复时可简写；不适用的部分写明原因，无需虚构复杂设计。新增框架、外部服务、依赖升级或边界例外必须说明必要性与维护成本。

## 3. 本地环境与安全验证

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
python3 scripts/check_architecture.py
.venv/bin/python -m pytest -q
```

完整离线 L0 smoke 使用独立进程与临时环境，避免继承本机 S3 配置或写入个人库：

```bash
EVIDPLANE_RAW_BACKEND=local .venv/bin/python scripts/smoke_l0_quality.py
```

`smoke_l0_quality.py` 自己创建临时 DB/raw；其中 fixture 的时间窗口依赖执行日期，若过期应通过单独 spec 修复测试时钟，不能直接把回归当作通过。

`smoke_pack.py` / `smoke_lake.py` 会 force seed。MCP 不再自动 seed；开发 smoke 仍应显式隔离：

```bash
scratch_dir=$(mktemp -d)
EVIDPLANE_DB="$scratch_dir/lake.db" EVIDPLANE_RAW_ROOT="$scratch_dir/raw" EVIDPLANE_RAW_BACKEND=local .venv/bin/python scripts/smoke_lake.py
EVIDPLANE_DB="$scratch_dir/lake.db" EVIDPLANE_RAW_ROOT="$scratch_dir/raw" EVIDPLANE_RAW_BACKEND=local .venv/bin/python scripts/smoke_mcp.py
```

此目录仅为临时验证，完成后可删除。不要将其替换为用户已有数据库。离线默认不需要 Notion、Google 或云凭据。

召回相关变更使用同一 frozen corpus/query，与历史结果比较；输出到临时目录，避免无意覆盖已提交基线：

```bash
.venv/bin/python scripts/eval_recall_baseline.py --db "$scratch_dir/eval.db" --raw-root "$scratch_dir/eval-raw" --results-dir "$scratch_dir/results" --force-ingest
```

最后运行 `git diff --check` 并审查 `git diff` / `git status --short`。运行/开发依赖已锁定；变更依赖需更新锁文件并验证。范围安装成功不代表所有下限版本都兼容。

## 4. 按影响选择验证

| 变更 | 必要验证 |
|---|---|
| 纯文档 | 链接/描述与事实一致，diff 检查；不新增措辞测试 |
| 架构规则/检查 | 当前树通过；跨层违规、相对导入、例外越界负例失败 |
| Connector | fixture + mock；分页、since、429/5xx、失败隔离与完整性；不连真实平台 |
| Raw/ingest/schema | 幂等、内容更新后旧 hash/URI、事务失败与恢复、兼容/迁移、local/fake S3 一致性 |
| Search/pack | 过滤/时区/空库/异常参数、预算与 cite/get、固定召回集对照 |
| MCP/依赖/打包 | 单元 + 离线 L0 + MCP smoke；干净安装；涉及 wheel 时检查包资源和非源码目录启动 |

CI 运行架构检查、pytest 与离线 L0 smoke；失败阻止该工作流通过。CI 不证明负责人已确认 spec，也不等价于云端集成验证。PR 模板承载 spec/确认/验收的人工审查；仓库管理员若要强制合并门槛，需要将该工作流设为 required check。本次不更改远端保护设置。

Ruff 当前全仓有历史告警，见评审。新 Python 检查代码要 lint；不要通过全局 ignore 隐藏历史问题。若修改旧文件，局部问题在 spec 范围内解决，批量整治单列变更。

## 5. PR 与交接

PR/最终交接给出：问题与新行为、spec 链接和确认依据、AC 验证证据、兼容/数据影响、剩余限制。使用 [.github/pull_request_template.md](../.github/pull_request_template.md)。不得宣称 mock 已验证真实 OSS、工具注册已验证 Cursor，或 pytest 已验证全部端到端行为。

没有要求发布时，完成本地可审查改动即可。遗留问题更新评审/索引，不以顺手修复扩大本次任务。
