"""
Notification module for Bento application.
Handles user notifications through various channels like Telegram.
"""

# Re-export concrete implementations
from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional

from .bot import TelegramNotificationProvider


class NotificationProvider(ABC):
    """Abstract base class for notification providers"""

    @abstractmethod
    async def setup(self) -> None:
        """Set up the notification provider"""
        pass

    @abstractmethod
    async def send_notification(self, message: str) -> bool:
        """
        Send a notification to subscribed users

        Args:
            message: The message to send

        Returns:
            Success status
        """
        pass

    @abstractmethod
    async def get_active_subscribers(self) -> List[str]:
        """
        Get list of active subscriber IDs

        Returns:
            List of subscriber IDs
        """
        pass

    @abstractmethod
    async def request_password(
        self,
        user_id: str,
        email_id: str,
        email_subject: str,
        attachment_index: int,
        file_name: str,
        callback: Callable[[str], Any],
    ) -> Optional[str]:
        """
        Request a password from a user for a password-protected attachment

        Args:
            user_id: User to request password from
            email_id: ID of the email
            email_subject: Subject of the email
            attachment_index: Index of the attachment
            file_name: Name of the file
            callback: Function to call with password when received

        Returns:
            Request ID or None if failed
        """
        pass


# Re-export for easier imports
__all__ = [
    "NotificationProvider",
    "TelegramNotificationProvider",
]
