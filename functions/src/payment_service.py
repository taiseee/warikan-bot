from __future__ import annotations
from datetime import datetime, timezone
from firebase_admin import firestore

from .model import Group, Session


def _fmt_ts(ts) -> str | None:
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


class PaymentService:

    def __init__(self):
        self._db = firestore.client()

    def _payments_ref(self, group_id: str, session_id: str):
        return (
            self._db.collection("groups")
            .document(group_id)
            .collection("sessions")
            .document(session_id)
            .collection("payments")
        )

    def _get_or_create_active_session(self, group_id: str) -> Session:
        session = Session.fetch_active(group_id)
        if session:
            return session
        # アクティブセッションがなければ日付から自動生成
        name = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
        session = Session(name=name)
        session.save(group_id)
        return session

    def create_session(self, group_id: str, name: str = None) -> dict:
        existing = Session.fetch_active(group_id)
        if existing:
            return {
                "status": "error",
                "message": f"アクティブなセッション「{existing.name}」があります。先に精算してください。",
                "details": {"session_id": existing.session_id, "name": existing.name},
            }
        if not name:
            name = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
        session = Session(name=name)
        session_id = session.save(group_id)
        return {
            "status": "success",
            "message": f"割り勘セッション「{name}」を開始しました。",
            "details": {"session_id": session_id, "name": name},
        }

    def add_payment(self, group_id: str, payer_id: str, amount: int, item: str) -> dict:
        members = Group.get_members(group_id)
        member_map = {m["user_id"]: m["display_name"] for m in members}

        if payer_id not in member_map:
            return {
                "status": "error",
                "message": f"payer_id '{payer_id}' はメンバーに登録されていません。",
            }

        session = self._get_or_create_active_session(group_id)
        _, doc_ref = self._payments_ref(group_id, session.session_id).add({
            "payer_id": payer_id,
            "item": item,
            "amount": amount,
            "created_at": firestore.SERVER_TIMESTAMP,
        })

        return {
            "status": "success",
            "message": "支払いを記録しました。",
            "details": {
                "payment_id": doc_ref.id,
                "session_id": session.session_id,
                "session_name": session.name,
                "payer_name": member_map[payer_id],
                "item": item,
                "amount": amount,
            },
        }

    def cancel_payment(self, group_id: str, payment_id: str) -> dict:
        session = Session.fetch_active(group_id)
        if not session:
            return {"status": "error", "message": "アクティブなセッションがありません。"}

        payment_ref = self._payments_ref(group_id, session.session_id).document(payment_id)
        doc = payment_ref.get()
        if not doc.exists:
            return {"status": "error", "message": f"支払いID '{payment_id}' が見つかりません。"}

        payment_ref.delete()
        return {
            "status": "success",
            "message": "支払いを取り消しました。",
            "details": {"payment_id": payment_id},
        }

    def list_payments(self, group_id: str) -> dict:
        session = Session.fetch_active(group_id)
        if not session:
            return {"status": "error", "message": "アクティブなセッションがありません。"}

        members = Group.get_members(group_id)
        member_map = {m["user_id"]: m["display_name"] for m in members}

        docs = self._payments_ref(group_id, session.session_id).order_by("created_at").get()
        payments = []
        for doc in docs:
            d = doc.to_dict()
            payments.append({
                "payment_id": doc.id,
                "payer_name": member_map.get(d["payer_id"], d["payer_id"]),
                "item": d["item"],
                "amount": d["amount"],
            })

        total = sum(p["amount"] for p in payments)
        return {
            "status": "success",
            "session_id": session.session_id,
            "session_name": session.name,
            "payments": payments,
            "total_amount": total,
        }

    def settle(self, group_id: str, div_num: int = None) -> dict:
        session = Session.fetch_active(group_id)
        if not session:
            return {"status": "error", "message": "アクティブなセッションがありません。"}

        members = Group.get_members(group_id)
        member_map = {m["user_id"]: m["display_name"] for m in members}

        if div_num is None:
            div_num = len(members)

        if div_num == 0:
            return {
                "status": "error",
                "message": "グループにメンバーが登録されていません。div_num を指定してください。",
            }

        docs = self._payments_ref(group_id, session.session_id).get()
        if not docs:
            return {"status": "error", "message": "支払いが記録されていません。"}

        # 支払い者ごとに集計
        payer_totals: dict[str, int] = {}
        for doc in docs:
            d = doc.to_dict()
            payer_id = d["payer_id"]
            payer_totals[payer_id] = payer_totals.get(payer_id, 0) + d["amount"]

        total_amount = sum(payer_totals.values())
        per_person = total_amount / div_num

        # payment_balance リストを構築（支払い者）
        paid = [
            {"name": member_map.get(pid, pid), "amount": amt}
            for pid, amt in payer_totals.items()
        ]

        # 未払いメンバーを追加
        paid_ids = set(payer_totals.keys())
        for m in members:
            if m["user_id"] not in paid_ids:
                paid.append({"name": m["display_name"], "amount": 0})

        # div_num より少なければ「未登録X」で補完
        for i in range(div_num - len(paid)):
            paid.append({"name": f"未登録{chr(ord('A') + i)}", "amount": 0})

        if len(paid) > div_num:
            return {
                "status": "error",
                "message": f"精算人数({div_num})より支払い者数({len(paid)})が多いです。div_num を大きく設定してください。",
            }

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

        session.mark_settled(group_id, settlement_result)

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
        sessions = Session.fetch_all(group_id)
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
        session = Session.fetch_by_id(group_id, session_id)
        if not session:
            return {"status": "error", "message": f"セッション '{session_id}' が見つかりません。"}

        members = Group.get_members(group_id)
        member_map = {m["user_id"]: m["display_name"] for m in members}

        docs = self._payments_ref(group_id, session_id).order_by("created_at").get()
        payments = []
        for doc in docs:
            d = doc.to_dict()
            payments.append({
                "payment_id": doc.id,
                "payer_name": member_map.get(d["payer_id"], d["payer_id"]),
                "item": d["item"],
                "amount": d["amount"],
            })

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
