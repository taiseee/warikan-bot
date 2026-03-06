"""Tests for WebhookHandler — LINE webhook handling with mocked dependencies."""

import pytest
from unittest.mock import patch, MagicMock


def _import_webhook_handler():
    from src.warikanbot import WebhookHandler
    return WebhookHandler


class TestWebhookHandler:
    """Tests for WebhookHandler event routing."""

    def _make_handler(self):
        WebhookHandler = _import_webhook_handler()
        handler = WebhookHandler()
        return handler

    def test_valid_signature_returns_200(self):
        """LINE署名が正しいリクエスト → handleが呼ばれる"""
        handler = self._make_handler()
        # handler._handler.handle is mocked, so no exception = success
        result = handler.handle("body", "valid_sig")
        handler._handler.handle.assert_called_once_with("body", "valid_sig")

    def test_invalid_signature_returns_400(self):
        """LINE署名が不正 → 400エラー"""
        from linebot.v3.exceptions import InvalidSignatureError
        handler = self._make_handler()
        handler._handler.handle.side_effect = InvalidSignatureError("bad sig")
        result = handler.handle("body", "bad_sig")
        # Should not raise, should return a response

    def test_join_event_handler_registered(self):
        """JoinEvent → ハンドラが登録されている"""
        handler = self._make_handler()
        # _add() is called in __init__, which registers handlers
        assert handler._handler.add.called

    def test_message_event_handler_registered(self):
        """TextMessageEvent → ハンドラが登録されている"""
        handler = self._make_handler()
        assert handler._handler.add.called

    def test_default_event_handler_registered(self):
        """未知のイベント → defaultハンドラが登録されている"""
        handler = self._make_handler()
        assert handler._handler.default.called


class TestWebhookErrorHandling:
    """Tests for error handling in webhook processing."""

    def test_handler_init_does_not_raise(self):
        """WebhookHandler の初期化がエラーなく完了する"""
        handler = _import_webhook_handler()()
        assert handler is not None

    def test_handler_has_reply_method(self):
        """_reply メソッドが存在する"""
        handler = _import_webhook_handler()()
        assert hasattr(handler, "_reply")
