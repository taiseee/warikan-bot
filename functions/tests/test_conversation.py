"""Tests for Conversation — OpenAI API integration with mocked client."""

import json
import pytest
from unittest.mock import MagicMock

from src.conversation import Conversation


class TestConversationCreate:
    """Tests for Conversation.create and send_message."""

    def test_create_returns_conversation_id(self):
        """新しい会話を作成 → conversation_id が返る"""
        conv = Conversation()
        conv._client = MagicMock()
        conv._client.conversations.create.return_value = MagicMock(id="conv_123")

        result = conv.create()
        assert result == "conv_123"

    def test_send_message_uses_conversation_id(self):
        """既存の会話にメッセージ送信 → conversation_id を使って継続"""
        conv = Conversation()
        conv._client = MagicMock()

        conv.send_message("conv_123", "こんにちは")
        call_kwargs = conv._client.responses.create.call_args
        assert call_kwargs.kwargs["conversation"] == "conv_123"

    def test_send_message_includes_extra_instructions(self):
        """メッセージ送信時にメンバー情報がインストラクションに含まれる"""
        conv = Conversation()
        conv._client = MagicMock()

        extra = "\n\n## グループメンバー\n- U1: Alice"
        conv.send_message("conv_123", "テスト", extra_instructions=extra)
        call_kwargs = conv._client.responses.create.call_args
        assert "Alice" in call_kwargs.kwargs["instructions"]


class TestHandleToolCalls:
    """Tests for Conversation.handle_tool_calls."""

    def _make_tool_call(self, name="add_payment", args=None, call_id="call_1"):
        tc = MagicMock()
        tc.type = "function_call"
        tc.name = name
        tc.arguments = json.dumps(args or {})
        tc.call_id = call_id
        return tc

    def test_no_tool_calls(self):
        """ツール呼び出しなし → (response, False, [], {})"""
        conv = Conversation()
        conv._client = MagicMock()

        mock_response = MagicMock()
        mock_response.output = [MagicMock(type="message")]

        mock_executor = MagicMock()
        result, settled, tools_called, tool_outputs = conv.handle_tool_calls(
            mock_response, "conv_1", tool_executor=mock_executor
        )
        assert result == mock_response
        assert settled is False
        assert tools_called == []
        assert tool_outputs == {}
        mock_executor.assert_not_called()

    def test_tool_call_executed(self):
        """ツール呼び出し1件 → tool_executor が呼ばれる"""
        conv = Conversation()
        conv._client = MagicMock()

        tc = self._make_tool_call("add_payment", {"payer_id": "U1", "amount": 1000, "item": "test"})
        mock_response = MagicMock()
        mock_response.output = [tc]

        mock_executor = MagicMock(return_value={"status": "success"})

        # 2回目のレスポンスにはツール呼び出しなし（ループ終了）
        final_response = MagicMock()
        final_response.output = [MagicMock(type="message")]
        conv._client.responses.create.return_value = final_response

        conv.handle_tool_calls(mock_response, "conv_1", tool_executor=mock_executor)
        mock_executor.assert_called_once_with("add_payment", {"payer_id": "U1", "amount": 1000, "item": "test"})

    def test_settle_success_returns_settled_true(self):
        """settle 成功 → settled=True"""
        conv = Conversation()
        conv._client = MagicMock()

        tc = self._make_tool_call("settle", {})
        mock_response = MagicMock()
        mock_response.output = [tc]

        mock_executor = MagicMock(return_value={"status": "success"})

        final_response = MagicMock()
        final_response.output = [MagicMock(type="message")]
        conv._client.responses.create.return_value = final_response

        _, settled, tools_called, _ = conv.handle_tool_calls(
            mock_response, "conv_1", tool_executor=mock_executor
        )
        assert settled is True
        assert "settle" in tools_called

    def test_multiple_tool_calls(self):
        """複数のツール呼び出し → 全て実行される"""
        conv = Conversation()
        conv._client = MagicMock()

        tc1 = self._make_tool_call("add_payment", {"payer_id": "U1", "amount": 500, "item": "a"}, "call_1")
        tc2 = self._make_tool_call("add_payment", {"payer_id": "U2", "amount": 300, "item": "b"}, "call_2")
        mock_response = MagicMock()
        mock_response.output = [tc1, tc2]

        mock_executor = MagicMock(return_value={"status": "success"})

        final_response = MagicMock()
        final_response.output = [MagicMock(type="message")]
        conv._client.responses.create.return_value = final_response

        conv.handle_tool_calls(mock_response, "conv_1", tool_executor=mock_executor)
        assert mock_executor.call_count == 2


class TestGetTextResponse:
    """Tests for Conversation.get_text_response."""

    def test_extract_text(self):
        """テキスト応答の抽出"""
        conv = Conversation()

        content = MagicMock()
        content.type = "output_text"
        content.text = "精算しました！"

        message = MagicMock()
        message.type = "message"
        message.content = [content]

        response = MagicMock()
        response.output = [message]

        result = conv.get_text_response(response)
        assert result == "精算しました！"

    def test_no_text_response_fallback(self):
        """テキスト応答なし → フォールバックメッセージ"""
        conv = Conversation()

        response = MagicMock()
        response.output = []

        result = conv.get_text_response(response)
        assert result == "応答を取得できませんでした。"
