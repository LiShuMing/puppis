import pytest

from scripts.check_architecture import violations


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("connectors/notion/adapter.py", "from connectors.base import PullRecord"),
        ("connectors/notion/adapter.py", "from . import helper"),
        ("lake/ingest.py", "from connectors.base import PullRecord"),
        ("lake/query.py", "from .db import connect"),
        ("lake/raw_store.py", "def f():\n    import opendal"),
        ("serve/mcp_server.py", "from lake.query import pack"),
        ("console/server.py", "from console.service import Service"),
        ("console/service.py", "from connectors.notion import NotionConnector"),
    ],
)
def test_allowed_edges(path, source):
    assert not violations(source, path)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("connectors/notion/adapter.py", "from lake import db"),
        ("connectors/notion/adapter.py", "from ..calendar import CalendarConnector"),
        ("connectors/base.py", "import httpx"),
        ("lake/query.py", "import connectors.base"),
        ("lake/query.py", "from serve import mcp_server"),
        ("lake/query.py", "def f():\n    import httpx"),
        ("serve/mcp_server.py", "from lake.db import connect"),
        ("serve/mcp_server.py", "from lake.seed import seed_fake"),
        ("serve/mcp_server.py", "import connectors.notion"),
        ("console/server.py", "from lake import query"),
        ("console/server.py", "from connectors.notion import NotionConnector"),
    ],
)
def test_forbidden_edges(path, source):
    assert violations(source, path)
