"""Loopback-only HTTP application for the local Evidence workspace."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import uvicorn
from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from console.service import Service, UserError

ASSETS = Path(__file__).with_name("static")
MAX_BODY = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


class ResponseHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                ]
            await send(message)

        await self.app(scope, receive, with_headers)


class TextImport(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)
    url: str | None = Field(default=None, max_length=2000)


def integer(value, default, minimum, maximum):
    result = int(value) if value is not None else default
    if not minimum <= result <= maximum:
        raise ValueError(f"参数须介于 {minimum}–{maximum}")
    return result


def create_app(service: Service | None = None):
    service = service or Service()

    async def index(request):
        return FileResponse(ASSETS / "index.html")

    async def api(request: Request):
        try:
            action = request.path_params["action"]
            if request.method == "GET":
                args = request.query_params
                if action == "health":
                    await run_in_threadpool(service.status)
                    return JSONResponse({"status": "ok", "app": "Evidplane"})
                if action == "status":
                    result = await run_in_threadpool(service.status)
                elif action == "search":
                    q = args.get("q", "")
                    if len(q) > 500:
                        raise ValueError("搜索内容过长")
                    result = await run_in_threadpool(
                        service.search,
                        q=q,
                        source=args.get("source") or None,
                        since_days=integer(args.get("days"), 30, 1, 3650)
                        if args.get("days")
                        else None,
                        limit=integer(args.get("limit"), 30, 1, 100),
                        offset=integer(args.get("offset"), 0, 0, 1_000_000),
                    )
                elif action == "item":
                    item_id = args.get("id", "")
                    if not item_id or len(item_id) > 512:
                        raise ValueError("证据 ID 无效")
                    result = await run_in_threadpool(service.get, item_id)
                    if "error" in result:
                        return JSONResponse(
                            {"error": "未找到这条证据"}, status_code=404
                        )
                elif action == "pack":
                    result = await run_in_threadpool(
                        service.pack,
                        budget_tokens=integer(args.get("budget"), 3000, 50, 12000),
                        since_days=integer(args.get("days"), 7, 1, 3650),
                    )
                else:
                    return JSONResponse({"error": "接口不存在"}, status_code=404)
            else:
                # JSON-only + exact-origin checks prevent cross-site writes to a
                # local service. TrustedHost also protects against DNS rebinding.
                origin = request.headers.get("origin")
                expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
                if origin != expected or request.headers.get(
                    "sec-fetch-site", "same-origin"
                ) not in {"same-origin", "none"}:
                    return JSONResponse(
                        {"error": "仅允许本机工作台发起写入"}, status_code=403
                    )
                if (
                    request.headers.get("content-type", "").split(";", 1)[0]
                    != "application/json"
                ):
                    return JSONResponse(
                        {"error": "需要 application/json"}, status_code=415
                    )
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        return JSONResponse(
                            {"error": "文件超过 2 MB 限制"}, status_code=413
                        )
                payload = json.loads(body or b"{}")
                if action == "import-text":
                    record = TextImport.model_validate(payload)
                    result = await run_in_threadpool(
                        service.import_text, **record.model_dump()
                    )
                elif action == "import-file":
                    result = await run_in_threadpool(service.import_fixture, payload)
                elif action == "import-demo":
                    result = await run_in_threadpool(service.import_demo)
                elif action == "sync-notion":
                    result = await run_in_threadpool(service.sync_notion)
                else:
                    return JSONResponse({"error": "接口不存在"}, status_code=404)
            return JSONResponse(result)
        except UserError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except ValidationError:
            return JSONResponse(
                {
                    "error": "资料格式无效：标题 1–200 字，正文 1–100000 字，链接最多 2000 字"
                },
                status_code=400,
            )
        except (ValueError, TypeError, KeyError):
            return JSONResponse(
                {"error": "输入或源配置无效，请检查填写内容、JSON 格式与接入设置"},
                status_code=400,
            )
        except Exception as exc:  # noqa: BLE001 — sanitize provider/storage errors at the HTTP boundary
            logger.error("console operation failed: %s", type(exc).__name__)
            return JSONResponse(
                {"error": "操作未完成；数据未被静默丢弃，请检查服务状态后重试"},
                status_code=503,
            )

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/api/{action}", api, methods=["GET", "POST"]),
            Mount("/static", StaticFiles(directory=ASSETS), name="static"),
        ]
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"]
    )

    app.add_middleware(ResponseHeaders)
    return app


def main():
    parser = argparse.ArgumentParser(description="Evidplane 本机工作台")
    parser.add_argument(
        "--host", default="127.0.0.1", choices=["127.0.0.1", "localhost", "::1"]
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    print(f"Evidplane workspace: http://{args.host}:{args.port}", flush=True)
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
