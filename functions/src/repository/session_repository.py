from __future__ import annotations

from firebase_admin import firestore

from ..model import Session
from .interfaces import ISessionRepository


class SessionRepository(ISessionRepository):
    """Firestore実装: Sessionの永続化。"""

    def __init__(self):
        self._db = firestore.client()

    def _sessions_ref(self, group_id: str):
        return (
            self._db.collection("groups")
            .document(group_id)
            .collection("sessions")
        )

    def fetch_active(self, group_id: str) -> Session | None:
        docs = self._sessions_ref(group_id).where("is_settled", "==", False).get()
        if docs:
            return Session.from_doc(docs[0])
        return None

    def fetch_all(self, group_id: str) -> list[Session]:
        docs = (
            self._sessions_ref(group_id)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .get()
        )
        return [Session.from_doc(doc) for doc in docs]

    def fetch_by_id(self, group_id: str, session_id: str) -> Session | None:
        doc = self._sessions_ref(group_id).document(session_id).get()
        if doc.exists:
            return Session.from_doc(doc)
        return None

    def save(self, group_id: str, session: Session) -> str:
        ref = self._sessions_ref(group_id)
        data = session.to_dict()

        if not session.session_id:
            data["created_at"] = firestore.SERVER_TIMESTAMP
            _, doc_ref = ref.add(data)
            session.session_id = doc_ref.id
        else:
            if session.is_settled and session.settled_at is None:
                data["settled_at"] = firestore.SERVER_TIMESTAMP
            ref.document(session.session_id).set(data)

        return session.session_id
