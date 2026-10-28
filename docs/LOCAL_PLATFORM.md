# 本机使用 Evidplane

工作台默认地址：[http://127.0.0.1:8765](http://127.0.0.1:8765)。只接受当前机器连接；空库不自动导入任何演示或私人资料。

## 安装与启动

当前机器已准备 `.venv`。在仓库目录运行：

```bash
.venv/bin/python scripts/workspace.py start
.venv/bin/python scripts/workspace.py status
.venv/bin/python scripts/workspace.py stop
```

前台运行：`.venv/bin/evidplane`；自定义端口：`scripts/workspace.py start --port 8766`。start 重复执行不会启动第二份进程。后台进程可跨终端保留，**机器重启后需再次 start**；本次未注册系统开机服务。

新环境从锁定依赖安装：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python scripts/workspace.py start
```

仅运行产品可把 `requirements-dev.lock` 换成 `requirements.lock`。锁文件是当前 Linux/Python3.12 的验证组合，不代表跨平台完整矩阵。

## 使用顺序

1. 在“数据接入”写入标题、正文和可选来源链接，保存后进入证据库；也可选择“导入演示资料”体验明确标记的示例。
2. 在“证据库”搜索、按来源/时间筛选，打开详情和外部来源。中文支持子串检索，英文使用 FTS 多词 AND；不使用向量/LLM。
3. 在“上下文工作台”设置天数和预算，生成 work 包、打开引用、复制正文。token 数按字符估算，不是模型实际 tokenizer 计费量。
4. 使用 MCP 调用相同资料库的 search/get/pack。

文件导入接受 `{ "pages": [...] }`（Notion 原始 page + blocks）或 `{ "events": [...] }`（日历事件）。每条需稳定 id，最多100条、2MB；文件来源标记为 export，并与 live ID 分隔，避免覆盖真实平台记录。相同手动资料和相同文件内容会去重。UI 暂无删除和编辑历史资料功能。

## 数据位置与环境

`workspace.py start` 默认：

| 内容 | 路径 |
|---|---|
| SQLite | `data/puppis.db` |
| 原始内容 | `data/platform/raw/` |
| 服务状态与日志 | `data/platform/server.json`、`server.log` |

上述路径均不入 Git。可在启动前设置 `EVIDPLANE_DB`（兼容 `PUPPIS_DB`）、`EVIDPLANE_RAW_ROOT`、`EVIDPLANE_RAW_BACKEND`。直接运行 `evidplane` 时 raw 默认仍是历史约定 `~/.evidplane`，建议与启动脚本一样显式配置；DB 默认相同。不要混用未记录的多个 raw 根目录。

新 raw 布局：`sources/<connector>/raw/<yyyy>/<mm>/<sha256(item_id)>/<sha256(bytes)>.json`。旧数据库/URI 不自动改写；历史已被覆盖的原文不能自动补回。

## 接入 Notion

在 Notion 创建 Integration，把指定页面/数据库分享给它。在服务启动的 shell 中设置 `NOTION_TOKEN` 和 `NOTION_PAGE_IDS` 或 `NOTION_DATABASE_ID`，然后 stop/start。在工作台点击“同步已授权页面”。密钥只留服务端，不通过网页填写，不写日志或提交。

没有凭据时可直接使用手动资料或 JSON，不影响工作台主流程。真实 Notion/OSS 尚未进行现场联调；mock 通过不表示账号授权、API 配额和云服务已验证。

## MCP 共用资料

客户端配置示例（把仓库绝对路径改成自己的）：

```json
{
  "mcpServers": {
    "evidplane": {
      "command": "/home/lism/work/puppis/.venv/bin/puppis-mcp",
      "env": {"EVIDPLANE_DB": "/home/lism/work/puppis/data/puppis.db"}
    }
  }
}
```

若使用自定义 DB，Web 与 MCP 的 `EVIDPLANE_DB` 必须相同。`list_connectors` 返回实际入库来源。第一次调用空库查询返回空结果。

## 备份与恢复

本地存储可在服务运行时制作 SQLite 一致快照，再复制不可变 raw。备份会校验所有 DB 引用的 raw hash；缺失/损坏/其他 raw 根目录导致失败，不冒充成功。

```bash
.venv/bin/python scripts/workspace.py backup --output /path/to/new-backup-directory
.venv/bin/python scripts/workspace.py restore --backup /path/to/new-backup-directory --output /path/to/new-restored-directory
```

目标必须尚不存在。restore 将 file:// 引用映射到新目录并再次校验；不会替换当前库。验证后要切换到恢复数据时，先 stop，设置 `EVIDPLANE_DB=/path/to/new-restored-directory/evidplane.db` 与 `EVIDPLANE_RAW_ROOT=/path/to/new-restored-directory/raw`，再 start；MCP 同步切换 DB。

这是 **DB + raw** 备份，不是仅 raw 重建索引。S3/OSS 对象备份另行处理；当前脚本明确拒绝把 S3 配置当作本地完整备份。

## 验证与排错

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_architecture.py
EVIDPLANE_RAW_BACKEND=local .venv/bin/python scripts/smoke_l0_quality.py
```

可选浏览器验收：安装 `.[browser]` 与 Playwright Chromium，然后运行 `python scripts/smoke_console_browser.py`。该脚本自启临时端口与临时数据，覆盖导入、中文搜索、引用、惰性 HTML、文件/演示和四个手机页面，不写入个人库。

端口冲突或启动失败查看 `data/platform/server.log`，不要结束不属于本平台的进程。状态不正常时先 stop，再 start；不会清空 DB。所有 API 错误都以可理解提示返回，敏感的源错误不会直接展示在浏览器中。
