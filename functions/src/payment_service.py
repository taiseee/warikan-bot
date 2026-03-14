from __future__ import annotations

from datetime import datetime, timezone

from .model import Session
from .repository.interfaces import IGroupRepository, ISessionRepository, IPaymentRepository


def _fmt_ts(ts) -> str | None:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


class PaymentService:

    def __init__(
        self,
        group_repo: IGroupRepository,
        session_repo: ISessionRepository,
        payment_repo: IPaymentRepository,
    ):
        self._group_repo = group_repo
        self._session_repo = session_repo
        self._payment_repo = payment_repo

    def _get_members_map(self, group_id: str) -> dict[str, str]:
        group = self._group_repo.find_by_id(group_id)
        if not group:
            return {}
        return {m.user_id: m.display_name for m in group.members}

    def _get_members_list(self, group_id: str) -> list[dict]:
        group = self._group_repo.find_by_id(group_id)
        if not group:
            return []
        return [{"user_id": m.user_id, "display_name": m.display_name} for m in group.members]

    def _get_or_create_active_session(self, group_id: str) -> Session:
        session = self._session_repo.fetch_active(group_id)
        if session:
            return session
        # アクティブセッションがなければ日付から自動生成
        name = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
        session = Session(name=name)
        self._session_repo.save(group_id, session)
        return session

    def create_session(self, group_id: str, name: str = None) -> dict:
        existing = self._session_repo.fetch_active(group_id)
        if existing:
            return {
                "status": "error",
                "message": f"アクティブなセッション「{existing.name}」があります。先に精算してください。",
                "details": {"session_id": existing.session_id, "name": existing.name},
            }
        if not name:
            name = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
        session = Session(name=name)
        session_id = self._session_repo.save(group_id, session)
        return {
            "status": "success",
            "message": f"割り勘セッション「{name}」を開始しました。",
            "details": {"session_id": session_id, "name": name},
        }

    def add_payment(self, group_id: str, payer_id: str, amount: int, item: str) -> dict:
        member_map = self._get_members_map(group_id)

        if payer_id not in member_map:
            return {
                "status": "error",
                "message": f"payer_id '{payer_id}' はメンバーに登録されていません。",
            }

        session = self._get_or_create_active_session(group_id)
        payment_id = self._payment_repo.add(group_id, session.session_id, payer_id, amount, item)

        return {
            "status": "success",
            "message": "支払いを記録しました。",
            "details": {
                "payment_id": payment_id,
                "session_id": session.session_id,
                "session_name": session.name,
                "payer_name": member_map[payer_id],
                "item": item,
                "amount": amount,
            },
        }

    def cancel_payment(self, group_id: str, payment_id: str) -> dict:
        session = self._session_repo.fetch_active(group_id)
        if not session:
            return {"status": "error", "message": "アクティブなセッションがありません。"}

        deleted = self._payment_repo.delete(group_id, session.session_id, payment_id)
        if not deleted:
            return {"status": "error", "message": f"支払いID '{payment_id}' が見つかりません。"}

        return {
            "status": "success",
            "message": "支払いを取り消しました。",
            "details": {"payment_id": payment_id},
        }

    def list_payments(self, group_id: str) -> dict:
        session = self._session_repo.fetch_active(group_id)
        if not session:
            return {"status": "error", "message": "アクティブなセッションがありません。"}

        member_map = self._get_members_map(group_id)
        raw_payments = self._payment_repo.list_ordered(group_id, session.session_id)

        payments = [
            {
                "payment_id": p["payment_id"],
                "payer_name": member_map.get(p["payer_id"], p["payer_id"]),
                "item": p["item"],
                "amount": p["amount"],
            }
            for p in raw_payments
        ]

        total = sum(p["amount"] for p in payments)
        return {
            "status": "success",
            "session_id": session.session_id,
            "session_name": session.name,
            "payments": payments,
            "total_amount": total,
        }

    def settle(self, group_id: str, div_num: int = None) -> dict:
        session = self._session_repo.fetch_active(group_id)
        if not session:
            return {"status": "error", "message": "アクティブなセッションがありません。"}

        members = self._get_members_list(group_id)
        member_map = {m["user_id"]: m["display_name"] for m in members}

        if div_num is None:
            div_num = len(members)

        if div_num == 0:
            return {
                "status": "error",
                "message": "グループにメンバーが登録されていません。div_num を指定してください。",
            }

        if div_num > len(members):
            return {
                "status": "error",
                "message": f"精算人数({div_num})がグループメンバー数({len(members)})を超えています。",
            }

        raw_payments = self._payment_repo.list_all(group_id, session.session_id)
        if not raw_payments:
            return {"status": "error", "message": "支払いが記録されていません。"}

        # 支払い者ごとに集計
        payer_totals: dict[str, int] = {}
        for p in raw_payments:
            payer_id = p["payer_id"]
            payer_totals[payer_id] = payer_totals.get(payer_id, 0) + p["amount"]

        if len(payer_totals) > div_num:
            return {
                "status": "error",
                "message": f"精算人数({div_num})より支払い者数({len(payer_totals)})が多いです。div_num を大きく設定してください。",
            }

        total_amount = sum(payer_totals.values())
        per_person = total_amount / div_num

        # payment_balance リストを構築（支払い者）
        paid = [
            {"name": member_map.get(pid, pid), "amount": amt}
            for pid, amt in payer_totals.items()
        ]

        if div_num == len(members):
            # div_num 未指定（全員割り勘）: 未払いメンバーを全員追加
            paid_ids = set(payer_totals.keys())
            for m in members:
                if m["user_id"] not in paid_ids:
                    paid.append({"name": m["display_name"], "amount": 0})
        else:
            # div_num 指定あり: 残り枠を「未払いX」で補完
            for i in range(div_num - len(paid)):
                paid.append({"name": f"未払い{chr(ord('A') + i)}", "amount": 0})

        payment_balance = [
            {"name": p["name"], "amount": p["amount"] - per_person}
            for p in paid
        ]

        transfers = self._settle_calc(payment_balance, [])

        settlement_result = {
            "total_amount": total_amount,
            "per_person": round(per_person),
            "transfers": transfers,
        }

        session.mark_settled(settlement_result)
        self._session_repo.save(group_id, session)

        return {
            "status": "success",
            "message": "精算が完了しました。",
            "details": settlement_result,
        }

    def _settle_calc(self, payment: list[dict], transfers: list[dict]) -> list[dict]:
        payment.sort(key=lambda x: x["amount"], reverse=True)
        creditor = payment[0]
        debtor = payment[-1]

        amount = min(creditor["amount"], abs(debtor["amount"]))
        if amount < 0.5:  # 端数切り捨て
            return transfers

        creditor["amount"] -= amount
        debtor["amount"] += amount
        transfers.append({
            "from_name": debtor["name"],
            "to_name": creditor["name"],
            "amount": round(amount),
        })

        return self._settle_calc(payment, transfers)

    def list_sessions(self, group_id: str, is_settled: bool = None) -> dict:
        sessions = self._session_repo.fetch_all(group_id)
        if is_settled is not None:
            sessions = [s for s in sessions if s.is_settled == is_settled]

        return {
            "status": "success",
            "sessions": [
                {
                    "session_id": s.session_id,
                    "name": s.name,
                    "is_settled": s.is_settled,
                    "created_at": _fmt_ts(s.created_at),
                    "settled_at": _fmt_ts(s.settled_at),
                }
                for s in sessions
            ],
        }

    def get_session_detail(self, group_id: str, session_id: str) -> dict:
        session = self._session_repo.fetch_by_id(group_id, session_id)
        if not session:
            return {"status": "error", "message": f"セッション '{session_id}' が見つかりません。"}

        member_map = self._get_members_map(group_id)
        raw_payments = self._payment_repo.list_ordered(group_id, session_id)

        payments = [
            {
                "payment_id": p["payment_id"],
                "payer_name": member_map.get(p["payer_id"], p["payer_id"]),
                "item": p["item"],
                "amount": p["amount"],
            }
            for p in raw_payments
        ]

        return {
            "status": "success",
            "session_id": session.session_id,
            "name": session.name,
            "is_settled": session.is_settled,
            "created_at": _fmt_ts(session.created_at),
            "settled_at": _fmt_ts(session.settled_at),
            "payments": payments,
            "settlement_result": session.settlement_result,
        }
