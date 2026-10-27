# Connector 环境变量（Notion + Calendar）

密钥与 token **只进环境 / secret 管理，不上仓、不写日志、不进 health 返回值**。

## 共用（Lake raw）

| 变量 | 默认 | 说明 |
|---|---|---|
| `EVIDPLANE_RAW_BACKEND` | `local` | `local` 或 `s3`（S3 兼容：OSS / MinIO） |
| `EVIDPLANE_RAW_ROOT` | `~/.evidplane` | 仅 local |
| `EVIDPLANE_S3_*` / `AWS_*` | — | 见 `deploy-ecs-oss.md` |
| `EVIDPLANE_DB`（别名 `PUPPIS_DB`） | `data/puppis.db` | SQLite 路径；或 Lake API 的 `db_path` 参数 |

## Notion（`connectors/notion`）

| 变量 | 必需 | 说明 |
|---|---|---|
| `NOTION_TOKEN` | API 模式 | Internal integration secret |
| `NOTION_DATABASE_ID` | API（与 PAGE_IDS 二选一） | 指定库 |
| `NOTION_PAGE_IDS` | API（可选） | 逗号分隔 page id（多页：逐页拉取，单页失败进 `last_errors` / raw `errors/`，不拖垮整批） |
| `NOTION_HTTP_MAX_RETRIES` | 否 | 429/5xx 在首次之后的重试次数（默认 `4`；总尝试 = 1+该值） |
| `NOTION_HTTP_RETRY_BASE_SECONDS` | 否 | 指数退避基数秒（默认 `0.5`） |
| `NOTION_HTTP_RETRY_MAX_SECONDS` | 否 | 退避上限秒（默认 `8`）；若响应带 `Retry-After` 则优先生效 |

离线：

```bash
python scripts/ingest_notion.py --fixture --smoke-pack
```

## Calendar（`connectors/calendar`，`connector_id=google_calendar`）

| 变量 | 必需 | 说明 |
|---|---|---|
| `CALENDAR_ICS_PATH` | ICS 模式 | 本地 `.ics` |
| `CALENDAR_ICS_URL` | ICS 模式 | 公开/授权 ICS URL |
| `GOOGLE_CALENDAR_ICS_PATH` | 同上别名 | — |
| `GOOGLE_CALENDAR_CREDENTIALS` | API（**未实现**） | OAuth client JSON 路径；TODO |
| `GOOGLE_APPLICATION_CREDENTIALS` | API（**未实现**） | 服务账号；TODO |
| `GOOGLE_CALENDAR_ID` | API（**未实现**） | 日历 id；TODO |

离线 fixture：

```bash
python scripts/ingest_calendar.py --fixture --smoke-pack
```

API 模式目前会 `CalendarConfigError` 并提示用 fixture/ICS；OAuth 留待有 Google 凭据后补。

## 狗粮最短路径（无云凭证）

```bash
cd /workspace/puppis
.venv/bin/python scripts/smoke_lake.py
.venv/bin/python scripts/ingest_notion.py --fixture --smoke-pack
.venv/bin/python scripts/ingest_calendar.py --fixture --smoke-pack
.venv/bin/python scripts/smoke_l0_quality.py   # 幂等/错误路径/pack 预算/MCP 质量门（独立临时 DB，不碰 EVIDPLANE_DB）
```
