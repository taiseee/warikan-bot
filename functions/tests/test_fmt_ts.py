"""Tests for _fmt_ts — timestamp formatting utility."""

from datetime import datetime, timezone
from src.payment_service import _fmt_ts


class TestFmtTs:
    """Tests for _fmt_ts utility function."""

    def test_datetime_object(self):
        """datetime オブジェクトを渡すと ISO形式文字列が返る"""
        dt = datetime(2024, 3, 6, 12, 0, 0, tzinfo=timezone.utc)
        result = _fmt_ts(dt)
        assert result == dt.isoformat()

    def test_object_without_isoformat(self):
        """isoformat を持たないオブジェクトは str() で変換される"""
        result = _fmt_ts(12345)
        assert result == "12345"

    def test_none_returns_none(self):
        """None を渡すと None が返る"""
        assert _fmt_ts(None) is None
