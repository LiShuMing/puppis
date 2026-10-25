# Evidplane — ECS + OSS 部署草图（L0）

| 项 | 值 |
|---|---|
| 用途 | 自持 Evidence raw（真相层）+ 单机 Lake/MCP |
| 隔离 | **禁止**与 Topic Plane / dbradar 共用 bucket、账号 RAM 策略或 `/srv` 目录 |
| 默认路径 | ECS 应用根：`/srv/evidplane` |

## 1. OSS bucket（S3 兼容）

建议新建独立 bucket，例如 `evidplane-raw-<region>`（名称以控制台可用为准）。

- **API**：S3 兼容；客户端用 `boto3` + `endpoint_url`（阿里云 OSS）。
- **区域**：与 ECS 同区，减少出网；endpoint 形如 `https://oss-cn-hangzhou.aliyuncs.com`（按实际地域改）。
- **密钥**：RAM 子用户，仅本 bucket 的 `GetObject` / `PutObject` / `HeadObject` / `ListBucket`（前缀限定更好）。密钥只进 ECS 环境变量或实例角色，**不上仓**。
- **与 dbradar 隔离**：单独 bucket + 单独 RAM 用户/角色；不要复用 Topic Plane 的 AK。

对象键布局（与 `lake/raw_store.py` 一致）：

```
s3://<bucket>/evidplane/
  sources/<connector_id>/
    raw/<yyyy>/<mm>/<item_id>.json
    errors/<yyyy>/<mm>/<name>.json
  derived/          # 可删可重建（后置）
  export/           # 后置
```

环境开关：

| 变量 | 说明 |
|---|---|
| `EVIDPLANE_RAW_BACKEND=s3` | 启用 S3/OSS；默认 `local` |
| `EVIDPLANE_S3_BUCKET` | bucket 名（或 `AWS_S3_BUCKET`） |
| `EVIDPLANE_S3_ENDPOINT` | OSS S3 endpoint（或 `AWS_ENDPOINT_URL`） |
| `EVIDPLANE_S3_ACCESS_KEY` / `EVIDPLANE_S3_SECRET_KEY` | 或 `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| `EVIDPLANE_S3_REGION` | 默认 `cn-hangzhou`（或 `AWS_DEFAULT_REGION`） |
| `EVIDPLANE_S3_PREFIX` | 默认 `evidplane` |

本地狗粮不设上述变量；raw 落 `~/.evidplane` 或 `EVIDPLANE_RAW_ROOT`。

## 2. ECS 目录

```
/srv/evidplane/
  app/                 # git clone / rsync 的 puppis
  data/                # SQLite：puppis.db（可重建；raw 在 OSS）
  logs/
  .venv/               # Python 3.12+
```

建议 systemd 单元（草）：工作目录 `/srv/evidplane/app`，`EnvironmentFile=/srv/evidplane/env`（chmod 600），ExecStart 跑 `puppis-mcp`（stdio）或后置 HTTP。

本机开发等价：`EVIDPLANE_RAW_ROOT` + `data/puppis.db`，无需 ECS。

## 3. 上线顺序（L0）

1. 建独立 OSS bucket + RAM；记下 endpoint / bucket（不提交密钥）。
2. ECS 装 Python ≥3.12，代码放到 `/srv/evidplane/app`，`pip install -e .`。
3. 写 `/srv/evidplane/env`：`EVIDPLANE_RAW_BACKEND=s3` + S3 变量 + Notion/日历变量（见 `connector-env.md`）。
4. 先 `--fixture` 冒烟，再切真源；Cursor 挂 MCP 指到该机或本机隧道。

## 4. 非目标（本文件不覆盖）

公网暴露 MCP、多租户、与 dbradar 共 VPC 安全组细调、CDN。
