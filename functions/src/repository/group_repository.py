from __future__ import annotations

from firebase_admin import firestore

from ..model import Group, Member
from .interfaces import IGroupRepository


class GroupRepository(IGroupRepository):
    """Firestore実装: Group集約の永続化（membersサブコレクション含む）。"""

    def __init__(self):
        self._db = firestore.client()
        self._collection = self._db.collection("groups")

    def find_by_id(self, group_id: str) -> Group | None:
        doc = self._collection.document(group_id).get()
        if not doc.exists:
            return None
        members = self._load_members(group_id)
        return Group.from_doc(doc, members=members)

    def save(self, group: Group) -> None:
        group_ref = self._collection.document(group.id)
        doc = group_ref.get()

        data = group.to_dict()
        data["updated_at"] = firestore.SERVER_TIMESTAMP
        if not doc.exists:
            data["created_at"] = firestore.SERVER_TIMESTAMP
        group_ref.set(data, merge=True)

        for member in group.members:
            group_ref.collection("members").document(member.user_id).set(
                member.to_dict(), merge=True,
            )

    def _load_members(self, group_id: str) -> list[Member]:
        docs = self._collection.document(group_id).collection("members").get()
        return [
            Member(
                user_id=doc.id,
                display_name=doc.get("display_name") or doc.id,
                picture_url=doc.get("picture_url") or "",
            )
            for doc in docs
        ]
