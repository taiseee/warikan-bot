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

    def test_start_session(self, mock_svc):
        """start_session → create_session が呼ばれる"""
        mock_svc.create_session.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "start_session", {"name": "飲み会"})
        result = tool.exec()
        mock_svc.create_session.assert_called_once_with("G1", name="飲み会")
        assert result["status"] == "success"

    def test_add_payment(self, mock_svc):
        """add_payment → 正しい引数で呼ばれる"""
        mock_svc.add_payment.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "add_payment", {
            "payer_id": "U1", "amount": 1000, "item": "ランチ"
        })
        result = tool.exec()
        mock_svc.add_payment.assert_called_once_with(
            "G1", payer_id="U1", amount=1000, item="ランチ"
        )

    def test_cancel_payment(self, mock_svc):
        """cancel_payment → 正しい引数で呼ばれる"""
        mock_svc.cancel_payment.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "cancel_payment", {"payment_id": "p1"})
        result = tool.exec()
        mock_svc.cancel_payment.assert_called_once_with("G1", payment_id="p1")

    def test_list_payments(self, mock_svc):
        """list_payments → 呼ばれる"""
        mock_svc.list_payments.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "list_payments")
        result = tool.exec()
        mock_svc.list_payments.assert_called_once_with("G1")

    def test_settle_with_div_num(self, mock_svc):
        """settle (div_numあり) → 正しい引数で呼ばれる"""
        mock_svc.settle.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "settle", {"div_num": 4})
        result = tool.exec()
        mock_svc.settle.assert_called_once_with("G1", div_num=4)

    def test_settle_without_div_num(self, mock_svc):
        """settle (div_numなし) → div_num=None で呼ばれる"""
        mock_svc.settle.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "settle", {})
        result = tool.exec()
        mock_svc.settle.assert_called_once_with("G1", div_num=None)

    def test_list_sessions(self, mock_svc):
        """list_sessions → is_settled が渡される"""
        mock_svc.list_sessions.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "list_sessions", {"is_settled": True})
        result = tool.exec()
        mock_svc.list_sessions.assert_called_once_with("G1", is_settled=True)

    def test_get_session_detail(self, mock_svc):
        """get_session_detail → session_id が渡される"""
        mock_svc.get_session_detail.return_value = {"status": "success"}
        tool = self._make_tool(mock_svc, "get_session_detail", {"session_id": "s1"})
        result = tool.exec()
        mock_svc.get_session_detail.assert_called_once_with("G1", session_id="s1")

    def test_unknown_tool_returns_error(self, mock_svc):
        """未知のツール名 → error"""
        tool = self._make_tool(mock_svc, "nonexistent_tool")
        result = tool.exec()
        assert result["status"] == "error"
        assert "Tool not found" in result["message"]
