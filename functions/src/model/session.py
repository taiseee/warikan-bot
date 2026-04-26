from __future__ import annotations


class Session:
    """セッションエンティティ: 割り勘セッションの状態を管理する。"""

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

    def mark_settled(self, settlement_result: dict):
        """ドメインメソッド: 精算確定の状態遷移。settled_at はリポジトリが永続化時に設定。"""
        self.is_settled = True
        self.settlement_result = settlement_result

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_settled": self.is_settled,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
            "settlement_result": self.settlement_result,
        }

    @classmethod
    def from_doc(cls, doc) -> Session:
        d = doc.to_dict()
        return cls(
            session_id=doc.id,
            name=d.get("name", ""),
            is_settled=d.get("is_settled", False),
            created_at=d.get("created_at"),
            settled_at=d.get("settled_at"),
            settlement_result=d.get("settlement_result"),
        )
