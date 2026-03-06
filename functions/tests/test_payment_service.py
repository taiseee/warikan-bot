"""Tests for PaymentService — service layer with mocked Firestore."""

import pytest
from unittest.mock import patch, MagicMock
from src.payment_service import PaymentService
from src.model.session import Session


# ── Helpers ──────────────────────────────────────────────


def _make_doc(doc_id, data):
    """Create a mock Firestore document snapshot."""
    doc = MagicMock()
    doc.id = doc_id
    doc.exists = True
    doc.to_dict.return_value = data
    doc.get = lambda field, default=None: data.get(field, default)
    return doc


def _make_session(session_id="sess1", name="テスト", is_settled=False):
    return Session(
        session_id=session_id,
        name=name,
        is_settled=is_settled,
    )


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
def svc():
    with patch("src.payment_service.firestore") as mock_fs:
        mock_fs.SERVER_TIMESTAMP = "SERVER_TIMESTAMP"
        service = PaymentService()
        yield service


# ═══════════════════════════════════════════════════════
# 2-1. create_session
# ═══════════════════════════════════════════════════════


class TestCreateSession:

    @patch.object(Session, "save", return_value="new_sess_id")
    @patch.object(Session, "fetch_active", return_value=None)
    def test_create_with_name(self, mock_fetch, mock_save, svc):
        """名前を指定してセッションを開始する"""
        result = svc.create_session("G1", name="飲み会")
        assert result["status"] == "success"
        assert "飲み会" in result["message"]
        assert result["details"]["name"] == "飲み会"

    @patch.object(Session, "save", return_value="new_sess_id")
    @patch.object(Session, "fetch_active", return_value=None)
    def test_create_without_name_uses_date(self, mock_fetch, mock_save, svc):
        """名前を省略すると日付ベースの名前で自動生成される"""
        result = svc.create_session("G1")
        assert result["status"] == "success"
        # Name should contain 年月日
        assert "年" in result["details"]["name"]
        assert "月" in result["details"]["name"]

    @patch.object(Session, "fetch_active")
    def test_create_when_active_exists_returns_error(self, mock_fetch, svc):
        """アクティブなセッションが既に存在する場合はエラー"""
        mock_fetch.return_value = _make_session()
        result = svc.create_session("G1", name="新セッション")
        assert result["status"] == "error"
        assert "精算してください" in result["message"]


# ═══════════════════════════════════════════════════════
# 3-1. add_payment
# ═══════════════════════════════════════════════════════


class TestAddPayment:

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_add_payment_success(self, mock_fetch, mock_members, svc):
        """有効なメンバーで支払いを記録する"""
        mock_fetch.return_value = _make_session()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "pay1"
        svc._payments_ref = MagicMock(return_value=MagicMock(
            add=MagicMock(return_value=(None, mock_doc_ref))
        ))
        result = svc.add_payment("G1", "U1", 1000, "ランチ")
        assert result["status"] == "success"
        assert result["details"]["amount"] == 1000
        assert result["details"]["payer_name"] == "Alice"

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active", return_value=None)
    @patch.object(Session, "save", return_value="auto_sess")
    def test_add_payment_auto_creates_session(self, mock_save, mock_fetch, mock_members, svc):
        """セッションなしで支払い追加 → 自動作成"""
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "pay1"
        svc._payments_ref = MagicMock(return_value=MagicMock(
            add=MagicMock(return_value=(None, mock_doc_ref))
        ))
        result = svc.add_payment("G1", "U1", 500, "コーヒー")
        assert result["status"] == "success"
        mock_save.assert_called_once()

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    def test_add_payment_invalid_payer(self, mock_members, svc):
        """メンバーに存在しない payer_id → エラー"""
        result = svc.add_payment("G1", "UNKNOWN", 1000, "ランチ")
        assert result["status"] == "error"
        assert "メンバーに登録されていません" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_add_payment_correct_amount(self, mock_fetch, mock_members, svc):
        """金額が正しく記録される"""
        mock_fetch.return_value = _make_session()
        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "pay1"
        svc._payments_ref = MagicMock(return_value=MagicMock(
            add=MagicMock(return_value=(None, mock_doc_ref))
        ))
        result = svc.add_payment("G1", "U2", 3500, "タクシー")
        assert result["details"]["amount"] == 3500


# ═══════════════════════════════════════════════════════
# 3-2. cancel_payment
# ═══════════════════════════════════════════════════════


class TestCancelPayment:

    @patch.object(Session, "fetch_active")
    def test_cancel_success(self, mock_fetch, svc):
        """存在する支払いを取り消す"""
        mock_fetch.return_value = _make_session()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_payments_ref = MagicMock()
        mock_payments_ref.document.return_value = MagicMock(
            get=MagicMock(return_value=mock_doc),
            delete=MagicMock(),
        )
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)
        result = svc.cancel_payment("G1", "pay1")
        assert result["status"] == "success"

    @patch.object(Session, "fetch_active", return_value=None)
    def test_cancel_no_active_session(self, mock_fetch, svc):
        """アクティブセッションなし → エラー"""
        result = svc.cancel_payment("G1", "pay1")
        assert result["status"] == "error"
        assert "アクティブなセッションがありません" in result["message"]

    @patch.object(Session, "fetch_active")
    def test_cancel_nonexistent_payment(self, mock_fetch, svc):
        """存在しない payment_id → エラー"""
        mock_fetch.return_value = _make_session()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_payments_ref = MagicMock()
        mock_payments_ref.document.return_value = MagicMock(
            get=MagicMock(return_value=mock_doc),
        )
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)
        result = svc.cancel_payment("G1", "nonexistent")
        assert result["status"] == "error"
        assert "見つかりません" in result["message"]


# ═══════════════════════════════════════════════════════
# 3-3. list_payments
# ═══════════════════════════════════════════════════════


class TestListPayments:

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_list_payments_success(self, mock_fetch, mock_members, svc):
        """アクティブセッションの支払い一覧を取得"""
        mock_fetch.return_value = _make_session()
        docs = [
            _make_doc("p1", {"payer_id": "U1", "item": "ランチ", "amount": 1000, "created_at": None}),
            _make_doc("p2", {"payer_id": "U2", "item": "コーヒー", "amount": 500, "created_at": None}),
        ]
        mock_payments_ref = MagicMock()
        mock_payments_ref.order_by.return_value.get.return_value = docs
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)

        result = svc.list_payments("G1")
        assert result["status"] == "success"
        assert len(result["payments"]) == 2
        assert result["total_amount"] == 1500

    @patch.object(Session, "fetch_active", return_value=None)
    def test_list_payments_no_session(self, mock_fetch, svc):
        """アクティブセッションがない → エラー"""
        result = svc.list_payments("G1")
        assert result["status"] == "error"
        assert "アクティブなセッションがありません" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_list_payments_empty(self, mock_fetch, mock_members, svc):
        """支払い0件 → 空リスト、total=0"""
        mock_fetch.return_value = _make_session()
        mock_payments_ref = MagicMock()
        mock_payments_ref.order_by.return_value.get.return_value = []
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)

        result = svc.list_payments("G1")
        assert result["status"] == "success"
        assert result["payments"] == []
        assert result["total_amount"] == 0

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_list_payments_unknown_payer_fallback(self, mock_fetch, mock_members, svc):
        """member_mapにないpayer_id → payer_idがそのまま表示される"""
        mock_fetch.return_value = _make_session()
        docs = [
            _make_doc("p1", {"payer_id": "UNKNOWN_USER", "item": "何か", "amount": 100, "created_at": None}),
        ]
        mock_payments_ref = MagicMock()
        mock_payments_ref.order_by.return_value.get.return_value = docs
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)

        result = svc.list_payments("G1")
        assert result["payments"][0]["payer_name"] == "UNKNOWN_USER"


# ═══════════════════════════════════════════════════════
# 4-1. settle
# ═══════════════════════════════════════════════════════


class TestSettle:
    """Tests for settle method."""

    def _setup_settle(self, svc, payments_data):
        """Helper to set up mock payments for settle tests."""
        docs = [
            _make_doc(f"p{i}", data)
            for i, data in enumerate(payments_data)
        ]
        mock_payments_ref = MagicMock()
        mock_payments_ref.get.return_value = docs
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)
        return docs

    # ── 正常系 ──

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_success(self, mock_mark, mock_fetch, mock_members, svc):
        """div_num=None（全員割り勘）→ 全メンバーで精算"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 3000},
            {"payer_id": "U2", "amount": 0},
        ])
        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["total_amount"] == 3000
        assert result["details"]["per_person"] == 1000
        assert len(result["details"]["transfers"]) > 0
        mock_mark.assert_called_once()

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_with_div_num(self, mock_mark, mock_fetch, mock_members, svc):
        """div_num=2 < メンバー数3: 支払い者1人 + 未払いA で2人精算"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 2000},
        ])
        result = svc.settle("G1", div_num=2)
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        # 未払いA → U1 への送金が1件
        assert len(result["details"]["transfers"]) == 1
        assert result["details"]["transfers"][0]["from_name"] == "未払いA"

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_with_unpaid_members_default(self, mock_mark, mock_fetch, mock_members, svc):
        """div_num=None → 全メンバーが paid に含まれる（未払いメンバーは display_name で追加）"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 3000},
        ])
        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        # Bob, Charlie が名前付きで送金元に含まれる
        transfer_froms = {t["from_name"] for t in result["details"]["transfers"]}
        assert "Bob" in transfer_froms
        assert "Charlie" in transfer_froms

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS_5)
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_div_num_fills_anonymous(self, mock_mark, mock_fetch, mock_members, svc):
        """div_num=3 < メンバー5人, 支払い者1人 → 未払いA, 未払いB で補完"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 3000},
        ])
        result = svc.settle("G1", div_num=3)
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        transfer_froms = [t["from_name"] for t in result["details"]["transfers"]]
        assert "未払いA" in transfer_froms
        assert "未払いB" in transfer_froms

    # ── 異常系 ──

    @patch.object(Session, "fetch_active", return_value=None)
    def test_settle_no_active_session(self, mock_fetch, svc):
        """アクティブセッションなし → エラー"""
        result = svc.settle("G1")
        assert result["status"] == "error"
        assert "アクティブなセッションがありません" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_settle_no_payments(self, mock_fetch, mock_members, svc):
        """支払い0件 → エラー"""
        mock_fetch.return_value = _make_session()
        mock_payments_ref = MagicMock()
        mock_payments_ref.get.return_value = []
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)

        result = svc.settle("G1")
        assert result["status"] == "error"
        assert "支払いが記録されていません" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=[])
    @patch.object(Session, "fetch_active")
    def test_settle_div_num_zero(self, mock_fetch, mock_members, svc):
        """メンバー0人 & div_num=None → div_num=0 → エラー"""
        mock_fetch.return_value = _make_session()
        result = svc.settle("G1")
        assert result["status"] == "error"
        assert "メンバーが登録されていません" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_settle_div_num_exceeds_members(self, mock_fetch, mock_members, svc):
        """div_num > メンバー数 → エラー（ユースケース外）"""
        mock_fetch.return_value = _make_session()
        result = svc.settle("G1", div_num=5)
        assert result["status"] == "error"
        assert "グループメンバー数" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    def test_settle_div_num_less_than_payers(self, mock_fetch, mock_members, svc):
        """div_num < 支払い者数 → エラー"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 1000},
            {"payer_id": "U2", "amount": 1000},
            {"payer_id": "U3", "amount": 1000},
        ])
        result = svc.settle("G1", div_num=2)
        assert result["status"] == "error"
        assert "精算人数" in result["message"]

    # ── 境界値 ──

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS[:1])
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_div_num_one(self, mock_mark, mock_fetch, mock_members, svc):
        """div_num=1 → 1人で全額負担、送金なし"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 1000},
        ])
        result = svc.settle("G1", div_num=1)
        assert result["status"] == "success"
        assert result["details"]["per_person"] == 1000
        assert result["details"]["transfers"] == []

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_indivisible_amount(self, mock_mark, mock_fetch, mock_members, svc):
        """割り切れない金額 (1000÷3) → per_person の端数処理"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 1000},
        ])
        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["per_person"] == round(1000 / 3)

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_active")
    @patch.object(Session, "mark_settled")
    def test_settle_tiny_amount(self, mock_mark, mock_fetch, mock_members, svc):
        """amount=1, div_num=3 → per_person ≈ 0.33、端数処理"""
        mock_fetch.return_value = _make_session()
        self._setup_settle(svc, [
            {"payer_id": "U1", "amount": 1},
        ])
        result = svc.settle("G1")
        assert result["status"] == "success"
        assert result["details"]["per_person"] == round(1 / 3)


# ═══════════════════════════════════════════════════════
# 2-2. list_sessions
# ═══════════════════════════════════════════════════════


class TestListSessions:

    @patch.object(Session, "fetch_all")
    def test_list_all_sessions(self, mock_fetch, svc):
        """フィルタなし → 全セッション返却"""
        mock_fetch.return_value = [
            _make_session("s1", "セッション1", is_settled=False),
            _make_session("s2", "セッション2", is_settled=True),
        ]
        result = svc.list_sessions("G1")
        assert result["status"] == "success"
        assert len(result["sessions"]) == 2

    @patch.object(Session, "fetch_all")
    def test_list_settled_only(self, mock_fetch, svc):
        """is_settled=True → 精算済のみ"""
        mock_fetch.return_value = [
            _make_session("s1", "セッション1", is_settled=False),
            _make_session("s2", "セッション2", is_settled=True),
        ]
        result = svc.list_sessions("G1", is_settled=True)
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["is_settled"] is True

    @patch.object(Session, "fetch_all")
    def test_list_unsettled_only(self, mock_fetch, svc):
        """is_settled=False → 未精算のみ"""
        mock_fetch.return_value = [
            _make_session("s1", "セッション1", is_settled=False),
            _make_session("s2", "セッション2", is_settled=True),
        ]
        result = svc.list_sessions("G1", is_settled=False)
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["is_settled"] is False

    @patch.object(Session, "fetch_all", return_value=[])
    def test_list_sessions_empty(self, mock_fetch, svc):
        """セッション0件 → 空リスト"""
        result = svc.list_sessions("G1")
        assert result["sessions"] == []


# ═══════════════════════════════════════════════════════
# 2-3. get_session_detail
# ═══════════════════════════════════════════════════════


class TestGetSessionDetail:

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_by_id")
    def test_get_detail_success(self, mock_fetch, mock_members, svc):
        """存在するsession_id → 詳細情報返却"""
        mock_fetch.return_value = _make_session("s1", "テスト")
        mock_payments_ref = MagicMock()
        mock_payments_ref.order_by.return_value.get.return_value = [
            _make_doc("p1", {"payer_id": "U1", "item": "ランチ", "amount": 1000, "created_at": None}),
        ]
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)

        result = svc.get_session_detail("G1", "s1")
        assert result["status"] == "success"
        assert result["session_id"] == "s1"
        assert len(result["payments"]) == 1

    @patch.object(Session, "fetch_by_id", return_value=None)
    def test_get_detail_not_found(self, mock_fetch, svc):
        """存在しないsession_id → エラー"""
        result = svc.get_session_detail("G1", "nonexistent")
        assert result["status"] == "error"
        assert "見つかりません" in result["message"]

    @patch("src.payment_service.Group.get_members", return_value=MEMBERS)
    @patch.object(Session, "fetch_by_id")
    def test_get_detail_settled_includes_result(self, mock_fetch, mock_members, svc):
        """精算済みセッション → settlement_result も含まれる"""
        session = _make_session("s1", "テスト", is_settled=True)
        session.settlement_result = {"total_amount": 3000, "per_person": 1000, "transfers": []}
        mock_fetch.return_value = session
        mock_payments_ref = MagicMock()
        mock_payments_ref.order_by.return_value.get.return_value = []
        svc._payments_ref = MagicMock(return_value=mock_payments_ref)

        result = svc.get_session_detail("G1", "s1")
        assert result["status"] == "success"
        assert result["settlement_result"]["total_amount"] == 3000
