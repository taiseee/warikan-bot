from __future__ import annotations


class Member:
    """Group集約内のエンティティ: グループメンバーを表す。"""

    def __init__(self, user_id: str, display_name: str, picture_url: str = ""):
        self.user_id = user_id
        self.display_name = display_name
        self.picture_url = picture_url

    def to_dict(self) -> dict:
        return {"display_name": self.display_name, "picture_url": self.picture_url}
