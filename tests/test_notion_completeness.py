import httpx

from connectors.notion.adapter import NotionConnector


def test_nested_block_failure_cannot_be_reported_as_complete_page():
    page_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def handler(request):
        if "/pages/" in request.url.path:
            return httpx.Response(200, json={
                "id": page_id, "object": "page", "last_edited_time": "2026-10-28T00:00:00Z",
                "properties": {}, "url": "https://www.notion.so/page",
            })
        if "/blocks/child/" in request.url.path:
            return httpx.Response(403, json={"message": "forbidden"})
        return httpx.Response(200, json={
            "results": [{"id": "child", "has_children": True, "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "partial"}]}}],
            "has_more": False,
        })

    connector = NotionConnector(
        token="test-token", page_ids=[page_id], database_id="",
        max_retries=0, transport=httpx.MockTransport(handler),
    )
    assert connector.pull() == []
    assert len(connector.last_errors) == 1
    assert connector.last_errors[0]["stage"] == "list_blocks"
    assert connector.last_errors[0]["status"] == 403
