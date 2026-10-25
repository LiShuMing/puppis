# Evidplane (repo: puppis) — MVP SPEC（开工版）

| 字段 | 内容 |
|---|---|
| 产品名 | **Evidplane**（Evidence + Plane）；仓暂名 `puppis`，域名拟 `evidplane.com` |
| 版本 | SPEC v0.1 · 2026-10-25 Asia/Shanghai |
| 楔子 | 工程师工作上下文（L0：Notion **或** 日历 1 源 → OSS Evidence → `pack(work)` → Cursor） |
| 非目标 | 聊天壳、Mem0 克隆、代发、全网爬、与 Topic Plane 共桶/共队列 |

相关：`PRD`/`UI`/`TECH` 合稿见全员讨论；本 SPEC 只钉**可实现边界与复用清单**。

---

## 1. 产品一句话

自持 Evidence 湖 + MCP：授权源原文进 OSS，派生可重建，Agent 只调 `search` / `get` / `pack`，每条可回源。

---

## 2. 三模块硬解耦（禁止跨层直连）

```
┌─────────────┐     Evidence[]      ┌──────────────────┐     只读查询      ┌─────────────┐
│  connectors │ ──────────────────► │  lake (+compile) │ ───────────────► │   serve     │
│  pull(since)│                     │  raw 不可变       │                  │ MCP stdio/  │
│  auth/health│                     │  derived 可重建   │                  │ HTTP        │
└─────────────┘                     │  pack(template)  │                  └─────────────┘
       ▲                            └──────────────────┘                         ▲
       │ Policy：授权/断源/复制 endpoint（薄站）                                    │
       └────────────────────────── 不进数据面 ────────────────────────────────────┘
```

| 模块 | 契约 | 可换实现 | 禁止 |
|---|---|---|---|
| **connectors** | `pull(since) → Evidence[]`；失败写 `errors/` | 每源一插件包 | 直写 MCP；互调平台 |
| **lake** | 消费 Evidence；`item_id`+源链+hash；FTS；`pack(work)` | SQLite↔PG；本地盘↔OSS | 调平台 API |
| **serve** | MCP：`search` / `get(item_id)` / `pack(work)` | stdio↔HTTP | 直读 connector / 扫桶实现细节 |

扩展点仅两处：**新 connector 适配器**、**新 pack 模板**。

---

## 3. L0 验收（端到端狗粮）

1. 接 **Notion 指定库** 或 **Google Calendar**（二选一先通，不抢第二源）。
2. raw 落自有 OSS（阿里云 OSS 或本地 `file://` 兼容 S3 API）；失败进 `errors/`，不静默丢。
3. Lake 建 `items` + FTS；`pack(work)` 产出近 N 天未决/高信号片段 + token 估计 + cites。
4. Cursor 挂本仓 MCP，一次会话能 `pack(work)` 并 `get` 回源。
5. 导出包可在空机器还原索引（raw 为真相）。

**不做（L0）：** 向量检索、AgentsView、GitHub 第二源、薄站 UI 精修、公域部署给外人。

---

## 4. Evidence 最小 schema

```json
{
  "item_id": "cal_evt_20261025_abc",
  "connector_id": "google_calendar",
  "kind": "event",
  "title": "...",
  "url": "https://...",
  "captured_at": "2026-10-25T12:00:00+08:00",
  "valid_from": null,
  "valid_to": null,
  "content_sha256": "...",
  "raw_uri": "s3://.../raw/.../....json",
  "text": "optional excerpt for FTS",
  "provenance": { "source": "platform", "human_reviewed": false }
}
```

- `source=agent` / `connector_id=agentsview`：**Phase 1.5**，不当第一手事实；默认降权，升格走人审。
- 冲突：写新 derived，不改 raw。

OSS 布局：

```
s3://<bucket>/evidplane/
  sources/<connector_id>/
    raw/<yyyy>/<mm>/<item_id>.json
    errors/<yyyy>/<mm>/...
  derived/
    episodes/  facts/   # 可删可重建
  export/latest.tar
```

---

## 5. MCP 工具面（Serve）

| 工具 | 参数 | 返回 |
|---|---|---|
| `search` | `q?`, `source?`, `since_days?`, `limit?` | metadata-first items[] |
| `get` | `item_id` | 正文/摘要 + `source_url` + provenance |
| `pack` | `template=work`, `budget_tokens?` | Pack 正文 + cites[] + token 估计 |

Agent **不**持有平台 token；不读桶。

---

## 6. 复用清单（少造轮子）

| 能力 | 选用 | 备注 |
|---|---|---|
| MCP SDK | `@modelcontextprotocol/sdk`（TS）或 `mcp`（Python） | Serve 主路径；优先 TS 若 Cursor 配置更熟，Python 若要快接现有脚本 |
| 对象存储 | `@aws-sdk/client-s3` + 阿里云 OSS S3 兼容 / 本地 MinIO | Lake raw；密钥不上仓 |
| 索引 | **SQLite + FTS5**（L0）；可选 `sqlite-vec` 后置 | 检索落 Lake 内 |
| Calendar connector | Google Calendar API（已有 Grok Bot / 用户 OAuth 可参考）或 ICS 导出 | L0 候选 A |
| Notion connector | Notion API 官方 SDK | L0 候选 B |
| Pack 装配 | 自研薄层（模板+预算截断）；不引 Mem0 | 规则优先于 LLM |
| 参考勿 fork 成核 | AgentsView（session 浏览）、mnemon/local-memory-mcp（FTS 模式参考） | 学接口，不吞产品定位 |

语言：**Python 3.12+** 优先（ingest 快、与现有脚本一致）；Serve 可用同一进程暴露 MCP stdio。

---


## 6.1 选型决策与版本钉（L0）

| 层 | 选择 | 版本钉（下限） | 备注 |
|---|---|---|---|
| 语言 | Python | ≥3.12 | 单仓三包；热点后再换 Go/Rust 同契约 |
| MCP | `mcp` | ≥1.0 | stdio 先；HTTP 后置 |
| 校验 | Pydantic | ≥2.0 | Evidence 契约 |
| HTTP | httpx | ≥0.27 | connectors |
| 对象存储 | boto3 | ≥1.34 | OSS S3 兼容 / MinIO |
| 索引 | SQLite FTS5 | 标准库 `sqlite3` | 向量/`sqlite-vec` 后置 |
| Notion | `notion-client` | 最新稳定 | L0 候选 |
| Calendar | Google API 或 ICS | — | L0 候选；先通一个 |

**明确不做：** 双语言栈、Mem0 fork、L0 上向量主路径、Serve 直调平台 API。


## 6.2 开源候选与评测门槛（可换 Lake 内核）

原则：**契约自有、内核可换**。OSS raw + `item_id` / MCP `search|get|pack`  equip；评测达标则适配进 Lake，不达标再自研薄层。

| 候选 | 评什么 | 过线门槛（L0 后） |
|---|---|---|
| mnemon / local-memory-mcp 等 FTS MCP | 延迟、许可（MIT 优先）、能否只作检索后端 | p95 search <200ms @1万条；可剥离其「记忆写入」叙事 |
| sqlite-vec / pgvector | 召回@10 vs 纯 FTS | 相对 FTS 有可测增益再上；L0 不挡 |
| AgentsView（只读） | session 源 connector，非 Lake 核 | 能 `pull(since)` 进 raw；不当第一手事实 |
| 抽取/Pack 库 | 是否绑死模型供应商 | 必须可换模型；输出挂 `item_id` |

评测集：本人近 14 天 Notion|日历（+可选假 GitHub）固定 query 20 条；记录命中、漏报、延迟、许可证。L0 狗粮不等人；评测并行。

## 7. 仓内目录

```
puppis/
  docs/SPEC.md          # 本文件
  docs/PRD.md           # 链到合稿或摘录
  connectors/           # 每源一包：notion/ calendar/ (later github agentsview)
  lake/                 # schema、ingest worker、FTS、pack compiler
  serve/                # MCP server
  scripts/              # dogfood：sync → pack → curl/mcp 冒烟
  deploy/               # 阿里云：OSS bucket、最小 ECS/函数（附录）
```

---

## 8. 两周里程碑

| 日 | 产出 |
|---|---|
| D1–2 | 本仓骨架 + schema + 假数据 `pack(work)` MCP 通 Cursor |
| D3–5 | 1 源 connector（Notion **或** 日历）→ raw → FTS |
| D6–8 | OSS 真写 + export；错误路径 |
| D9–10 | 本人狗粮；修 cite/预算；记 kill 信号 |
| 并行 | @阿里云：域名候选 + OSS/ECS 报价与账号边界（与 Topic Plane 隔离） |

---

## 9. 品牌与域名（已拍板）

| 项 | 值 |
|---|---|
| 品牌 | **Evidplane** |
| 域名 | `evidplane.com`（先 1 年；@阿里云 万网下单） |
| 仓名 | 暂 `puppis`，域名落地后再 rename |

历史候选（已弃）：Mneme / Citepack / Evidora / Puppis 作品牌名。

---

## 10. 分工建议

| 角色 | L0 |
|---|---|
| @技术 | SPEC、仓、Lake schema/FTS、MCP Serve、假数据通 Cursor |
| @阿里云 | OSS 布局落地、域名/机器调研、隔离 Topic Plane |
| @Noa | PRD/UI 收口、验收话术、kill 标准 |
| 其他 | Phase 2 源（X/投资/社交）契约对齐，不挡 L0 |

---

*变更：只改本 SPEC；实现 PR 对这一节做 diff 说明。*
