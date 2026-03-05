from firebase_admin import firestore

from firebase_functions.firestore_fn import (
    DocumentSnapshot,
)


class Group:
    def __init__(self, id: str = "", conversation_id: str = "", active_session_id: str = "", created_at=firestore.SERVER_TIMESTAMP, updated_at=firestore.SERVER_TIMESTAMP):
        self._collection = firestore.client().collection("groups")
        self.id = id
        self.conversation_id = conversation_id
        self.active_session_id = active_session_id
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "active_session_id": self.active_session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def from_doc(self, doc: DocumentSnapshot) -> "Group":
        d = doc.to_dict()
        return Group(
            id=doc.id,
            conversation_id=d.get("conversation_id", ""),
            active_session_id=d.get("active_session_id", ""),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    def fetch_or_create(self, group_id: str) -> "Group":
        group_ref = self._collection.document(group_id)
        group = group_ref.get()

        if group.exists:
            return Group().from_doc(group)

        group = Group(id=group_id)
        group_ref.set(group.to_dict())

        return group

    def update(self):
        self.updated_at = firestore.SERVER_TIMESTAMP
        self._collection.document(self.id).update(self.to_dict())
        return self

    @staticmethod
    def get_members(group_id: str) -> list[dict]:
        db = firestore.client()
        docs = db.collection("groups").document(group_id).collection("members").get()
        return [
            {"user_id": doc.id, "display_name": doc.get("display_name") or doc.id}
            for doc in docs
        ]

    @staticmethod
    def upsert_member(group_id: str, user_id: str, display_name: str, picture_url: str = ""):
        db = firestore.client()
        member_ref = (
            db.collection("groups")
            .document(group_id)
            .collection("members")
            .document(user_id)
        )
        member_ref.set(
            {"display_name": display_name, "picture_url": picture_url},
            merge=True,
        )
