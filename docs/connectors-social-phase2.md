# Evidplane Phase 2 — 社交连接器草约

| 字段 | 内容 |
|---|---|
| 产品 | Evidplane（仓 `puppis`） |
| 阶段 | Phase 2（不挡 L0） |
| 状态 | 草约 v0.1 · 2026-10-25 Asia/Shanghai |
| 负责人 | 社交（ToS/只读边界）+ X（X 字段表） |
| 契约对齐 | SPEC §4 Evidence、§6.2 连接器门槛、`pull(since)` |

---

## 1. 目标与非目标

**目标：** 把用户**已授权**的社交只读数据变成可回源 Evidence，供 Lake/`pack(social)` 使用。

**非目标（硬禁）：**
- 代发、点赞、评论、转发、关注/取关
- 私信 / DM / 消息请求
- 全站爬赞、爬粉、非官方客户端、绕过 ToS 的抓取
- 与 L0 工作楔子抢主闸（本文件只定契约，实现后置）

---

## 2. 共通契约（所有社交源）

每个 connector 必须实现：

| 项 | 要求 |
|---|---|
| 入口 | `pull(since) → Evidence[]`；失败写 `errors/`，不静默丢 |
| 鉴权 | 官方 OAuth / 平台 token；**Agent 不持有平台 token** |
| API | **仅官方只读 API**（含配额）；ToS 禁止的实现直接剔除短名单 |
| 回源 | 必有 `source_url`（或等价 permalink）+ 稳定 `item_id` |
| 落盘 | `raw_uri` → 自持 OSS；许可须允许嵌自持 OSS |
| 增量 | `since` 游标（时间或平台 cursor）；支持断点续拉 |
| health | `auth/health`：token 失效、429、权限被撤可观测 |

Evidence 字段映射到 SPEC §4 最小 schema：

| Evidence 字段 | 社交侧来源 |
|---|---|
| `item_id` | 见各源表（全局唯一、稳定） |
| `connector_id` | `x` / `jike` / `linkedin` |
| `kind` | `post` / `bookmark` / `like` / `update` … |
| `title` | 短摘要或截断正文首行 |
| `url` | `source_url` permalink |
| `captured_at` | 拉取时刻 |
| `valid_from` / `valid_to` | 可选；点赞撤销等可写 tombstone derived |
| `content_sha256` | raw 正文 hash |
| `raw_uri` | OSS 路径 |
| `text` | FTS 用摘录 |
| `provenance` | `{ "source": "platform", "api": "...", "license_ok": true }` |

---

## 3. 源表（一套 schema）

### 3.1 X（来自 @X，已对齐）

| X 对象 | `source` / kind | `item_id` | 关键元数据 | 非目标 |
|---|---|---|---|---|
| 本人帖 | `x_post` | `x:post:{id}` | text、created_at、url、metrics | 代发 |
| 书签 | `x_bookmark` | `x:bookmark:{id}` | 同上 + bookmarked_at | — |
| 点赞 | `x_like` | `x:like:{post_id}` | 被赞帖摘要 + url | 全站爬赞 |

共通：官方只读 API、`pull(since)`、`raw_uri`、`source_url`、许可可嵌自持 OSS。  
**L0–P2 不做：** 私信、关注列表、主页推荐流。

### 3.2 即刻（Jike）

| 即刻对象 | `source` / kind | `item_id` | 关键元数据 | 非目标 |
|---|---|---|---|---|
| 本人动态 | `jike_post` | `jike:post:{id}` | text、created_at、url、圈子 | 代发 |
| 收藏/稍后读* | `jike_bookmark` | `jike:bookmark:{id}` | 原帖摘要 + url + saved_at | 无官方能力则整行剔除 |
| 赞过* | `jike_like` | `jike:like:{post_id}` | 被赞摘要 + url | 无官方只读 API 则不做 |

\* 以**官方 API 是否暴露**为准；Web 抓取不算过线。通知铃铛可作 health/信号，默认不进 Lake 正文。

### 3.3 LinkedIn

| LinkedIn 对象 | `source` / kind | `item_id` | 关键元数据 | 非目标 |
|---|---|---|---|---|
| 本人帖/分享 | `li_post` | `li:post:{urn}` | text、created_at、url | 代发、自动互动 |
| 已保存职缺/帖* | `li_saved` | `li:saved:{urn}` | 标题、公司/作者、url、saved_at | 无官方 scope 则剔除 |
| 动态评论* | `li_comment` | `li:comment:{urn}` | 正文、父帖 url | 全量爬他人 feed |

\* LinkedIn Marketing / Community Management 等官方 scope 变化快：实现前用 §6.2 门槛复核；**禁止**浏览器会话刮首页。  
**L0–P2 不做：** InMail、连接请求、通讯录导出滥用。

---

## 4. 评测 / 准入门槛（挂 SPEC §6.2）

候选实现进短名单前必须全部通过：

1. **官方只读 API**（文档可引用）+ OAuth/配额路径清晰  
2. 能保住 `item_id` + `source_url` 回源  
3. 许可允许 raw 写入自持 OSS  
4. 可实现 `pull(since)`，429/撤权可观测  
5. 不引入代发、私信、关注图

不过线 → 该源延后或仅人工导出（用户自助 zip）再 ingest，**不**用非官方客户端顶上。

---

## 5. 与 Lake / Serve

- Connectors 只产出 Evidence；不调 MCP、不互调平台  
- Lake 按 `connector_id` 隔离索引；社交默认权重可低于工作源（pack 模板决定）  
- Serve：后续 `pack(social)` 模板；L0 仍只钉 `pack(work)`  
- 撤销授权：停 `pull`、保留已落 raw（或按用户请求删 raw——Policy 另文）

---

## 6. 落地顺序（建议）

| 序 | 产出 | 谁 |
|---|---|---|
| 1 | 本文 + X 字段表合稿（本文件） | 社交 + X |
| 2 | X connector 适配器骨架（mock `pull(since)`） | X / 技术，L0 通后 |
| 3 | 即刻/LinkedIn API 可行性复核（过线再开包） | 社交 |
| 4 | `pack(social)` 模板 | 技术 |

**不挡** L0 假数据 → FTS → MCP 竖切。

---

## 7. 待决

- 即刻是否有稳定官方只读「赞/收藏」API（2026-10 需再核）  
- LinkedIn 个人帖读取所需产品 API / 开发者准入是否对个人开发者开放  
- 社交 raw 的保留期与一键删除（Policy）

