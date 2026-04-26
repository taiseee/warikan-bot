"""Tests for Tool.exec — tool dispatch routing."""

import pytest
from unittest.mock import MagicMock

from src.warikanbot import Tool
from src.payment_service import PaymentService


@pytest.fixture
def mock_svc():
    return MagicMock(spec=PaymentService)


class TestToolExec:
    """Tests for Tool.exec dispatching to PaymentService methods."""

    def _make_tool(self, mock_svc, name, args=None, group_id="G1"):
        return Tool(name=name, args=args or {}, group_id=group_id, payment_service=mock_svc)

    def test_unknown_tool_returns_error(self, mock_svc):
        """未知のツール名 → error"""
        tool = self._make_tool(mock_svc, "nonexistent_tool")
        result = tool.exec()
        assert result["status"] == "error"
        assert "Tool not found" in result["message"]
