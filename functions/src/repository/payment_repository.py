from __future__ import annotations

from firebase_admin import firestore

from .interfaces import IPaymentRepository


class PaymentRepository(IPaymentRepository):
    """Firestore実装: Payment（支払い記録）の永続化。"""

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

    def add(self, group_id: str, session_id: str, payer_id: str, amount: int, item: str) -> str:
        _, doc_ref = self._payments_ref(group_id, session_id).add({
            "payer_id": payer_id,
            "item": item,
            "amount": amount,
            "created_at": firestore.SERVER_TIMESTAMP,
        })
        return doc_ref.id

    def delete(self, group_id: str, session_id: str, payment_id: str) -> bool:
        ref = self._payments_ref(group_id, session_id).document(payment_id)
        doc = ref.get()
        if not doc.exists:
            return False
        ref.delete()
        return True

    def list_ordered(self, group_id: str, session_id: str) -> list[dict]:
        docs = self._payments_ref(group_id, session_id).order_by("created_at").get()
        return [
            {"payment_id": doc.id, **doc.to_dict()}
            for doc in docs
        ]

    def list_all(self, group_id: str, session_id: str) -> list[dict]:
        docs = self._payments_ref(group_id, session_id).get()
        return [
            {"payment_id": doc.id, **doc.to_dict()}
            for doc in docs
        ]
