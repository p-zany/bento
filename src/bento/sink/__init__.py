"""
Sink module for Bento application.
Handles bill processing and importing into accounting systems like beancount.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Protocol


class ImporterConfig(Protocol):
    """Protocol for importer configuration"""

    @property
    def account(self) -> str:
        """Get the account name for this importer"""
        ...

    @property
    def name(self) -> str:
        """Get the name of the importer"""
        ...


class BillImporter(ABC):
    """Abstract base class for bill importers"""

    @abstractmethod
    def identify(self, file_path: str) -> bool:
        """
        Identify if this importer can handle the given file

        Args:
            file_path: Path to the file to check

        Returns:
            True if this importer can handle the file, False otherwise
        """
        pass

    @abstractmethod
    def extract(self, file_path: str, existing_entries=None) -> Dict[str, Any]:
        """
        Extract data from the file

        Args:
            file_path: Path to the file to extract data from
            existing_entries: Optional existing entries to consider

        Returns:
            Extracted data as dictionary
        """
        pass

    @abstractmethod
    def file_account(self, file_path: str) -> str:
        """
        Get the account to use for this file

        Args:
            file_path: Path to the file

        Returns:
            Account name
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of the importer"""
        pass


# Import concrete implementations (would normally be here)
# from .importers import ...

# Re-export for easier imports
__all__ = [
    "ImporterConfig",
    "BillImporter",
]
