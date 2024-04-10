from firebase_admin import firestore

from firebase_functions.firestore_fn import (
    DocumentSnapshot,
)


class Group:
    def __init__(self, id: str = "", thread_id: str = "", created_at = firestore.SERVER_TIMESTAMP, updated_at = firestore.SERVER_TIMESTAMP):
        self._collection = firestore.client().collection("groups")
        self.id = id
        self.thread_id = thread_id
        self.created_at = created_at
        self.updated_at = updated_at
        
    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    def from_doc(self, doc: DocumentSnapshot) -> "Group":
        dict = doc.to_dict()
        return Group(
            id=doc.id,
            thread_id=dict.get("thread_id", ""),
            created_at=dict.get("created_at"),
            updated_at=dict.get("updated_at"),
        )

    def fetch_or_create(self, group_id: str) -> "Group":
        group_ref = self._collection.document(group_id)
        group = group_ref.get()

        if group.exists:
            return Group().from_doc(group)

        group = Group(id=group_id)
        group_ref.set(
            group.to_dict()
        )

        return group

    def update(self):
        self.updated_at = firestore.SERVER_TIMESTAMP
        self._collection.document(self.id).update(
            self.to_dict()
        )
        return self
