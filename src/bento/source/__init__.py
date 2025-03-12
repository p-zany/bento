"""
Source module for Bento application.
"""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from .password import FilePasswordHandler


class Entity:
    topic: str
    name: str
    path: str
    needs_password: bool
    checksum: str


class Statement:
    name: str
    content: bytes


class Source(ABC):
    def __init__(self):
        self._password_handler = FilePasswordHandler()

    @abstractmethod
    def unsubscribe(self) -> None:
        pass

    @abstractmethod
    def subscribe(
        self,
        on_ledger: Callable[[Statement], None],
        on_auth_request: Callable[[str], Awaitable[str]] = None,
    ) -> None:
        pass


__all__ = ["Statement", "Source"]
