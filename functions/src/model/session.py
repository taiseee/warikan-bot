from __future__ import annotations
from firebase_admin import firestore


class Session:
    def __init__(
        self,
        session_id: str = "",
        name: str = "",
        is_settled: bool = False,
        created_at=None,
        settled_at=None,
        settlement_result=None,
    ):
        self.session_id = session_id
        self.name = name
        self.is_settled = is_settled
        self.created_at = created_at
        self.settled_at = settled_at
        self.settlement_result = settlement_result

    def _to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_settled": self.is_settled,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
            "settlement_result": self.settlement_result,
        }

    @classmethod
    def _from_doc(cls, doc) -> "Session":
        d = doc.to_dict()
        return cls(
            session_id=doc.id,
            name=d.get("name", ""),
            is_settled=d.get("is_settled", False),
            created_at=d.get("created_at"),
            settled_at=d.get("settled_at"),
            settlement_result=d.get("settlement_result"),
        )

    @classmethod
    def _sessions_ref(cls, group_id: str):
        return (
            firestore.client()
            .collection("groups")
            .document(group_id)
            .collection("sessions")
        )

    @classmethod
    def fetch_active(cls, group_id: str) -> "Session | None":
        docs = cls._sessions_ref(group_id).where("is_settled", "==", False).get()
        if docs:
            return cls._from_doc(docs[0])
        return None

    @classmethod
    def fetch_all(cls, group_id: str) -> list["Session"]:
        docs = (
            cls._sessions_ref(group_id)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .get()
        )
        return [cls._from_doc(doc) for doc in docs]

    @classmethod
    def fetch_by_id(cls, group_id: str, session_id: str) -> "Session | None":
        doc = cls._sessions_ref(group_id).document(session_id).get()
        if doc.exists:
            return cls._from_doc(doc)
        return None

    def save(self, group_id: str) -> str:
        ref = self.__class__._sessions_ref(group_id)
        if not self.session_id:
            self.created_at = firestore.SERVER_TIMESTAMP
            _, doc_ref = ref.add(self._to_dict())
            self.session_id = doc_ref.id
        else:
            ref.document(self.session_id).set(self._to_dict())
        return self.session_id

    def mark_settled(self, group_id: str, settlement_result: dict):
        self.is_settled = True
        self.settled_at = firestore.SERVER_TIMESTAMP
        self.settlement_result = settlement_result
        self.__class__._sessions_ref(group_id).document(self.session_id).update({
            "is_settled": True,
            "settled_at": firestore.SERVER_TIMESTAMP,
            "settlement_result": settlement_result,
        })
