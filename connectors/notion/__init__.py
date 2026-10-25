"""Notion connector: official Notion REST API → PullRecord[]."""

from connectors.notion.adapter import NotionConnector, NotionConfigError

__all__ = ["NotionConnector", "NotionConfigError"]
