"""Tests for _settle_calc — pure settlement calculation algorithm."""

import pytest
from src.payment_service import PaymentService


@pytest.fixture
def svc():
    """PaymentService with mocked Firestore client."""
    from unittest.mock import patch
    with patch("src.payment_service.firestore"):
        return PaymentService()


# ── 正常系 ──────────────────────────────────────────────


class TestSettleCalcNormal:
    """Normal cases for _settle_calc."""

    def test_two_people_one_paid(self, svc):
        """2人で1人が全額負担: B→A: 500円"""
        payment = [
            {"name": "A", "amount": 500},
            {"name": "B", "amount": -500},
        ]
        result = svc._settle_calc(payment, [])
        assert len(result) == 1
        assert result[0] == {"from_name": "B", "to_name": "A", "amount": 500}

    def test_three_people_one_paid(self, svc):
        """3人で1人が全額負担: B→A:1000, C→A:1000"""
        payment = [
            {"name": "A", "amount": 2000},
            {"name": "B", "amount": -1000},
            {"name": "C", "amount": -1000},
        ]
        result = svc._settle_calc(payment, [])
        assert len(result) == 2
        total_to_a = sum(t["amount"] for t in result if t["to_name"] == "A")
        assert total_to_a == 2000
        from_names = {t["from_name"] for t in result}
        assert from_names == {"B", "C"}

    def test_three_people_two_paid(self, svc):
        """3人で2人が支払い: C→A:1000, C→B:500"""
        payment = [
            {"name": "A", "amount": 1000},
            {"name": "B", "amount": 500},
            {"name": "C", "amount": -1500},
        ]
        result = svc._settle_calc(payment, [])
        assert len(result) == 2
        # Sum of transfers from C should be 1500
        total_from_c = sum(t["amount"] for t in result if t["from_name"] == "C")
        assert total_from_c == 1500

    def test_four_people_complex(self, svc):
        """4人以上の複雑な精算: 送金の合計が正しい"""
        # A paid 3000, B paid 1000, C paid 0, D paid 0 => total 4000, per_person 1000
        # Balances: A:+2000, B:0, C:-1000, D:-1000
        payment = [
            {"name": "A", "amount": 2000},
            {"name": "B", "amount": 0},
            {"name": "C", "amount": -1000},
            {"name": "D", "amount": -1000},
        ]
        result = svc._settle_calc(payment, [])
        # Total transferred to A should be 2000
        total_to_a = sum(t["amount"] for t in result if t["to_name"] == "A")
        assert total_to_a == 2000
        # C and D each owe 1000
        for name in ("C", "D"):
            total = sum(t["amount"] for t in result if t["from_name"] == name)
            assert total == 1000

    def test_all_equal_no_transfers(self, svc):
        """全員が均等に支払った場合: 送金指示が0件"""
        payment = [
            {"name": "A", "amount": 0},
            {"name": "B", "amount": 0},
            {"name": "C", "amount": 0},
        ]
        result = svc._settle_calc(payment, [])
        assert result == []


# ── 境界値 ──────────────────────────────────────────────


class TestSettleCalcBoundary:
    """Boundary value tests for _settle_calc."""

    def test_amount_below_half_yen_no_transfer(self, svc):
        """amount が 0.5 未満で打ち切り"""
        payment = [
            {"name": "A", "amount": 0.4},
            {"name": "B", "amount": -0.4},
        ]
        result = svc._settle_calc(payment, [])
        assert result == []

    def test_amount_exactly_half_yen(self, svc):
        """amount がちょうど 0.5 → 送金発生"""
        payment = [
            {"name": "A", "amount": 0.5},
            {"name": "B", "amount": -0.5},
        ]
        result = svc._settle_calc(payment, [])
        assert len(result) == 1
        assert result[0]["amount"] == round(0.5)

    def test_amount_just_below_half_yen(self, svc):
        """amount が 0.49 → 打ち切り"""
        payment = [
            {"name": "A", "amount": 0.49},
            {"name": "B", "amount": -0.49},
        ]
        result = svc._settle_calc(payment, [])
        assert result == []

    def test_single_person_zero_balance(self, svc):
        """1人だけのリスト（balance=0）: creditor == debtor → 送金なし"""
        payment = [{"name": "A", "amount": 0}]
        result = svc._settle_calc(payment, [])
        assert result == []


# ── 異常系 ──────────────────────────────────────────────


class TestSettleCalcError:
    """Error cases for _settle_calc."""

    def test_empty_list_raises_index_error(self, svc):
        """空リストを渡すと IndexError（潜在バグ: ガード未実装）"""
        with pytest.raises(IndexError):
            svc._settle_calc([], [])
