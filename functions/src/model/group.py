from __future__ import annotations

from .member import Member


class Group:
    """Group集約ルート: グループとそのメンバーを管理する。"""

    def __init__(
        self,
        id: str = "",
        conversation_id: str = "",
        active_session_id: str = "",
        members: list[Member] | None = None,
        created_at=None,
        updated_at=None,
    ):
        self.id = id
        self.conversation_id = conversation_id
        self.active_session_id = active_session_id
        self.members: list[Member] = members or []
        self.created_at = created_at
        self.updated_at = updated_at

    def upsert_member(self, user_id: str, display_name: str, picture_url: str = ""):
        """ドメインメソッド: メンバーの追加または更新。"""
        for m in self.members:
            if m.user_id == user_id:
                m.display_name = display_name
                m.picture_url = picture_url
                return
        self.members.append(Member(user_id, display_name, picture_url))

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "active_session_id": self.active_session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_doc(cls, doc, members: list[Member] | None = None) -> Group:
        d = doc.to_dict()
        return cls(
            id=doc.id,
            conversation_id=d.get("conversation_id", ""),
            active_session_id=d.get("active_session_id", ""),
            members=members or [],
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
