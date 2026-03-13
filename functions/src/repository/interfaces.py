from __future__ import annotations

from abc import ABC, abstractmethod

from ..model import Group, Session


class IGroupRepository(ABC):
    """Group集約の永続化契約。membersはGroup集約の一部としてsave()で永続化。"""

    @abstractmethod
    def find_by_id(self, group_id: str) -> Group | None: ...

    @abstractmethod
    def save(self, group: Group) -> None: ...


class ISessionRepository(ABC):
    """Sessionの永続化契約。mark_settledはエンティティのドメインメソッド。"""

    @abstractmethod
    def fetch_active(self, group_id: str) -> Session | None: ...

    @abstractmethod
    def fetch_all(self, group_id: str) -> list[Session]: ...

    @abstractmethod
    def fetch_by_id(self, group_id: str, session_id: str) -> Session | None: ...

    @abstractmethod
    def save(self, group_id: str, session: Session) -> str: ...


class IPaymentRepository(ABC):
    """Payment（支払い記録）の永続化契約。"""

    @abstractmethod
    def add(self, group_id: str, session_id: str, payer_id: str, amount: int, item: str) -> str: ...

    @abstractmethod
    def delete(self, group_id: str, session_id: str, payment_id: str) -> bool: ...

    @abstractmethod
    def list_ordered(self, group_id: str, session_id: str) -> list[dict]: ...

    @abstractmethod
    def list_all(self, group_id: str, session_id: str) -> list[dict]: ...
