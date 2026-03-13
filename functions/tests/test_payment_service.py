"""Tests for PaymentService — service layer with mocked repositories (DIP)."""

import pytest
from unittest.mock import MagicMock
from src.payment_service import PaymentService
from src.model import Group, Member, Session
from src.repository.interfaces import IGroupRepository, ISessionRepository, IPaymentRepository


# ── Helpers ──────────────────────────────────────────────


def _make_session(session_id="sess1", name="テスト", is_settled=False):
    return Session(
        session_id=session_id,
        name=name,
        is_settled=is_settled,
    )


def _make_group_with_members(members_data):
    """MEMBERSデータからGroup集約を生成する。"""
    members = [Member(m["user_id"], m["display_name"]) for m in members_data]
    return Group(id="G1", members=members)


MEMBERS = [
    {"user_id": "U1", "display_name": "Alice"},
    {"user_id": "U2", "display_name": "Bob"},
    {"user_id": "U3", "display_name": "Charlie"},
]

MEMBERS_5 = MEMBERS + [
    {"user_id": "U4", "display_name": "Dave"},
    {"user_id": "U5", "display_name": "Eve"},
]


@pytest.fixture
def group_repo():
    return MagicMock(spec=IGroupRepository)


@pytest.fixture
def session_repo():
    return MagicMock(spec=ISessionRepository)


@pytest.fixture
def payment_repo():
    return MagicMock(spec=IPaymentRepository)


@pytest.fixture
def svc(group_repo, session_repo, payment_repo):
    return PaymentService(group_repo, session_repo, payment_repo)


# ═══════════════════════════════════════════════════════
# 2-1. create_session
# ═══════════════════════════════════════════════════════


class TestCreateSession:

    def test_create_with_name(self, svc, session_repo):
        """名前を指定してセッションを開始する"""
        session_repo.fetch_active.return_value = None
        session_repo.save.return_value = "new_sess_id"

        result = svc.create_session("G1", name="飲み会")
        assert result["status"] == "success"
        assert "飲み会" in result["message"]
        assert result["details"]["name"] == "飲み会"

    def test_create_without_name_uses_date(self, svc, session_repo):
        """名前を省略すると日付ベースの名前で自動生成される"""
        session_repo.fetch_active.return_value = None
        session_repo.save.return_value = "new_sess_id"

        result = svc.create_session("G1")
        assert result["status"] == "success"
        # Name should contain 年月日
        assert "年" in result["details"]["name"]
        assert "月" in result["details"]["name"]

    def test_create_when_active_exists_returns_error(self, svc, session_repo):
        """アクティブなセッションが既に存在する場合はエラー"""
        session_repo.fetch_active.return_value = _make_session()

        result = svc.create_session("G1", name="新セッション")
        assert result["status"] == "error"
        assert "精算してください" in result["message"]


# ═══════════════════════════════════════════════════════
# 3-1. add_payment
# ═══════════════════════════════════════════════════════


class TestAddPayment:

    def test_add_payment_success(self, svc, group_repo, session_repo, payment_repo):
        """有効なメンバーで支払いを記録する"""
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        session_repo.fetch_active.return_value = _make_session()
        payment_repo.add.return_value = "pay1"

        result = svc.add_payment("G1", "U1", 1000, "ランチ")
        assert result["status"] == "success"
        assert result["details"]["amount"] == 1000
        assert result["details"]["payer_name"] == "Alice"
        payment_repo.add.assert_called_once_with("G1", "sess1", "U1", 1000, "ランチ")

    def test_add_payment_auto_creates_session(self, svc, group_repo, session_repo, payment_repo):
        """セッションなしで支払い追加 → 自動作成"""
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        session_repo.fetch_active.return_value = None
        session_repo.save.return_value = "auto_sess"
        payment_repo.add.return_value = "pay1"

        result = svc.add_payment("G1", "U1", 500, "コーヒー")
        assert result["status"] == "success"
        session_repo.save.assert_called_once()

    def test_add_payment_invalid_payer(self, svc, group_repo):
        """メンバーに存在しない payer_id → エラー"""
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)

        result = svc.add_payment("G1", "UNKNOWN", 1000, "ランチ")
        assert result["status"] == "error"
        assert "メンバーに登録されていません" in result["message"]

    def test_add_payment_correct_amount(self, svc, group_repo, session_repo, payment_repo):
        """金額が正しく記録される"""
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        session_repo.fetch_active.return_value = _make_session()
        payment_repo.add.return_value = "pay1"

        result = svc.add_payment("G1", "U2", 3500, "タクシー")
        assert result["details"]["amount"] == 3500


# ═══════════════════════════════════════════════════════
# 3-2. cancel_payment
# ═══════════════════════════════════════════════════════


class TestCancelPayment:

    def test_cancel_success(self, svc, session_repo, payment_repo):
        """存在する支払いを取り消す"""
        session_repo.fetch_active.return_value = _make_session()
        payment_repo.delete.return_value = True

        result = svc.cancel_payment("G1", "pay1")
        assert result["status"] == "success"

    def test_cancel_no_active_session(self, svc, session_repo):
        """アクティブセッションなし → エラー"""
        session_repo.fetch_active.return_value = None

        result = svc.cancel_payment("G1", "pay1")
        assert result["status"] == "error"
        assert "アクティブなセッションがありません" in result["message"]

    def test_cancel_nonexistent_payment(self, svc, session_repo, payment_repo):
        """存在しない payment_id → エラー"""
        session_repo.fetch_active.return_value = _make_session()
        payment_repo.delete.return_value = False

        result = svc.cancel_payment("G1", "nonexistent")
        assert result["status"] == "error"
        assert "見つかりません" in result["message"]


# ═══════════════════════════════════════════════════════
# 3-3. list_payments
# ═══════════════════════════════════════════════════════


class TestListPayments:

    def test_list_payments_success(self, svc, group_repo, session_repo, payment_repo):
        """アクティブセッションの支払い一覧を取得"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_ordered.return_value = [
            {"payment_id": "p1", "payer_id": "U1", "item": "ランチ", "amount": 1000, "created_at": None},
            {"payment_id": "p2", "payer_id": "U2", "item": "コーヒー", "amount": 500, "created_at": None},
        ]

        result = svc.list_payments("G1")
        assert result["status"] == "success"
        assert len(result["payments"]) == 2
        assert result["total_amount"] == 1500

    def test_list_payments_no_session(self, svc, session_repo):
        """アクティブセッションがない → エラー"""
        session_repo.fetch_active.return_value = None

        result = svc.list_payments("G1")
        assert result["status"] == "error"
        assert "アクティブなセッションがありません" in result["message"]

    def test_list_payments_empty(self, svc, group_repo, session_repo, payment_repo):
        """支払い0件 → 空リスト、total=0"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_ordered.return_value = []

        result = svc.list_payments("G1")
        assert result["status"] == "success"
        assert result["payments"] == []
        assert result["total_amount"] == 0

    def test_list_payments_unknown_payer_fallback(self, svc, group_repo, session_repo, payment_repo):
        """member_mapにないpayer_id → payer_idがそのまま表示される"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_ordered.return_value = [
            {"payment_id": "p1", "payer_id": "UNKNOWN_USER", "item": "何か", "amount": 100, "created_at": None},
        ]

        result = svc.list_payments("G1")
        assert result["payments"][0]["payer_name"] == "UNKNOWN_USER"


# ═══════════════════════════════════════════════════════
# 4-1. settle
# ═══════════════════════════════════════════════════════


class TestSettle:
    """Tests for settle method."""

    # ── 正常系 ──

    def test_settle_success(self, svc, group_repo, session_repo, payment_repo):
        """div_num=None（全員割り勘）→ 全メンバーで精算"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 3000},
            {"payment_id": "p1", "payer_id": "U2", "amount": 0},
        ]

        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["total_amount"] == 3000
        assert result["details"]["per_person"] == 1000
        assert len(result["details"]["transfers"]) > 0
        session_repo.save.assert_called_once()

    def test_settle_with_div_num(self, svc, group_repo, session_repo, payment_repo):
        """div_num=2 < メンバー数3: 支払い者1人 + 未払いA で2人精算"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 2000},
        ]

        result = svc.settle("G1", div_num=2)
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        # 未払いA → U1 への送金が1件
        assert len(result["details"]["transfers"]) == 1
        assert result["details"]["transfers"][0]["from_name"] == "未払いA"

    def test_settle_with_unpaid_members_default(self, svc, group_repo, session_repo, payment_repo):
        """div_num=None → 全メンバーが paid に含まれる（未払いメンバーは display_name で追加）"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 3000},
        ]

        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        # Bob, Charlie が名前付きで送金元に含まれる
        transfer_froms = {t["from_name"] for t in result["details"]["transfers"]}
        assert "Bob" in transfer_froms
        assert "Charlie" in transfer_froms

    def test_settle_div_num_fills_anonymous(self, svc, group_repo, session_repo, payment_repo):
        """div_num=3 < メンバー5人, 支払い者1人 → 未払いA, 未払いB で補完"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS_5)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 3000},
        ]

        result = svc.settle("G1", div_num=3)
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        transfer_froms = [t["from_name"] for t in result["details"]["transfers"]]
        assert "未払いA" in transfer_froms
        assert "未払いB" in transfer_froms

    # ── 異常系 ──

    def test_settle_no_active_session(self, svc, session_repo):
        """アクティブセッションなし → エラー"""
        session_repo.fetch_active.return_value = None

        result = svc.settle("G1")
        assert result["status"] == "error"
        assert "アクティブなセッションがありません" in result["message"]

    def test_settle_no_payments(self, svc, group_repo, session_repo, payment_repo):
        """支払い0件 → エラー"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = []

        result = svc.settle("G1")
        assert result["status"] == "error"
        assert "支払いが記録されていません" in result["message"]

    def test_settle_div_num_zero(self, svc, group_repo, session_repo):
        """メンバー0人 & div_num=None → div_num=0 → エラー"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members([])

        result = svc.settle("G1")
        assert result["status"] == "error"
        assert "メンバーが登録されていません" in result["message"]

    def test_settle_div_num_exceeds_members(self, svc, group_repo, session_repo):
        """div_num > メンバー数 → エラー（ユースケース外）"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)

        result = svc.settle("G1", div_num=5)
        assert result["status"] == "error"
        assert "グループメンバー数" in result["message"]

    def test_settle_div_num_less_than_payers(self, svc, group_repo, session_repo, payment_repo):
        """div_num < 支払い者数 → エラー"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 1000},
            {"payment_id": "p1", "payer_id": "U2", "amount": 1000},
            {"payment_id": "p2", "payer_id": "U3", "amount": 1000},
        ]

        result = svc.settle("G1", div_num=2)
        assert result["status"] == "error"
        assert "精算人数" in result["message"]

    # ── 境界値 ──

    def test_settle_div_num_one(self, svc, group_repo, session_repo, payment_repo):
        """div_num=1 → 1人で全額負担、送金なし"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS[:1])
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 1000},
        ]

        result = svc.settle("G1", div_num=1)
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        assert result["details"]["transfers"] == []

    def test_settle_indivisible_amount(self, svc, group_repo, session_repo, payment_repo):
        """割り切れない金額 (1000÷3) → per_person の端数処理"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 1000},
        ]

        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["per_person"] == round(1000 / 3)

    def test_settle_tiny_amount(self, svc, group_repo, session_repo, payment_repo):
        """amount=1, div_num=3 → per_person ≈ 0.33、端数処理"""
        session_repo.fetch_active.return_value = _make_session()
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_all.return_value = [
            {"payment_id": "p0", "payer_id": "U1", "amount": 1},
        ]

        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["per_person"] == round(1 / 3)


# ═══════════════════════════════════════════════════════
# 2-2. list_sessions
# ═══════════════════════════════════════════════════════


class TestListSessions:

    def test_list_all_sessions(self, svc, session_repo):
        """フィルタなし → 全セッション返却"""
        session_repo.fetch_all.return_value = [
            _make_session("s1", "セッション1", is_settled=False),
            _make_session("s2", "セッション2", is_settled=True),
        ]
        result = svc.list_sessions("G1")
        assert result["status"] == "success"
        assert len(result["sessions"]) == 2

    def test_list_settled_only(self, svc, session_repo):
        """is_settled=True → 精算済のみ"""
        session_repo.fetch_all.return_value = [
            _make_session("s1", "セッション1", is_settled=False),
            _make_session("s2", "セッション2", is_settled=True),
        ]
        result = svc.list_sessions("G1", is_settled=True)
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["is_settled"] is True

    def test_list_unsettled_only(self, svc, session_repo):
        """is_settled=False → 未精算のみ"""
        session_repo.fetch_all.return_value = [
            _make_session("s1", "セッション1", is_settled=False),
            _make_session("s2", "セッション2", is_settled=True),
        ]
        result = svc.list_sessions("G1", is_settled=False)
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["is_settled"] is False

    def test_list_sessions_empty(self, svc, session_repo):
        """セッション0件 → 空リスト"""
        session_repo.fetch_all.return_value = []

        result = svc.list_sessions("G1")
        assert result["sessions"] == []


# ═══════════════════════════════════════════════════════
# 2-3. get_session_detail
# ═══════════════════════════════════════════════════════


class TestGetSessionDetail:

    def test_get_detail_success(self, svc, group_repo, session_repo, payment_repo):
        """存在するsession_id → 詳細情報返却"""
        session_repo.fetch_by_id.return_value = _make_session("s1", "テスト")
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_ordered.return_value = [
            {"payment_id": "p1", "payer_id": "U1", "item": "ランチ", "amount": 1000, "created_at": None},
        ]

        result = svc.get_session_detail("G1", "s1")
        assert result["status"] == "success"
        assert result["session_id"] == "s1"
        assert len(result["payments"]) == 1

    def test_get_detail_not_found(self, svc, session_repo):
        """存在しないsession_id → エラー"""
        session_repo.fetch_by_id.return_value = None

        result = svc.get_session_detail("G1", "nonexistent")
        assert result["status"] == "error"
        assert "見つかりません" in result["message"]

    def test_get_detail_settled_includes_result(self, svc, group_repo, session_repo, payment_repo):
        """精算済みセッション → settlement_result も含まれる"""
        session = _make_session("s1", "テスト", is_settled=True)
        session.settlement_result = {"total_amount": 3000, "per_person": 1000, "transfers": []}
        session_repo.fetch_by_id.return_value = session
        group_repo.find_by_id.return_value = _make_group_with_members(MEMBERS)
        payment_repo.list_ordered.return_value = []

        result = svc.get_session_detail("G1", "s1")
        assert result["status"] == "success"
        assert result["settlement_result"]["total_amount"] == 3000
