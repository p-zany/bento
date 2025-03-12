"""
Email module with common classes for all email sources.
"""

import os
import tempfile
from datetime import datetime
from typing import Awaitable, Callable, List, Optional

from . import Entity, Source


class EmailAttachment:
    filename: str
    content_type: str
    content: bytes
    size: int

    def __init__(
        self, filename: str, content_type: str, content: bytes, size: int = None
    ):
        self.filename = filename
        self.content_type = content_type
        self.content = content
        self.size = size if size is not None else len(content)

    def save_to_temp(self) -> str:
        temp_path = os.path.join(tempfile.gettempdir(), self.filename)
        with open(temp_path, "wb") as f:
            f.write(self.content)
        return temp_path


class Email:
    message_id: str
    sender: str
    recipient: str
    subject: str
    date: datetime
    body_text: str
    body_html: Optional[str]
    attachments: List[EmailAttachment]

    def __init__(
        self,
        message_id: str,
        sender: str,
        recipient: str,
        subject: str,
        date: datetime,
        body_text: str,
        body_html: Optional[str] = None,
        attachments: List[EmailAttachment] = None,
    ):
        self.message_id = message_id
        self.sender = sender
        self.recipient = recipient
        self.subject = subject
        self.date = date
        self.body_text = body_text
        self.body_html = body_html
        self.attachments = attachments or []

    @property
    def has_attachments(self) -> bool:
        return len(self.attachments) > 0

    def get_attachment_by_filename(self, filename: str) -> Optional[EmailAttachment]:
        for attachment in self.attachments:
            if attachment.filename == filename:
                return attachment
        return None


class EmailSource(Source):
    def __init__(self):
        super().__init__()

    def subscribe(
        self,
        on_ledger: Callable[[Entity], None],
        on_auth_request: Callable[[str], Awaitable[str]] = None,
    ) -> None:
        pass

    def unsubscribe(self) -> None:
        pass

    async def _parse_email(self, email: Email) -> List[Entity]:
        entities = []
        entity = Entity()
        entity.name = f"{email.subject}"
        entity.topic = email.subject

        if email.has_attachments:
            for attachment in email.attachments:
                temp_path = os.path.join(tempfile.gettempdir(), attachment.filename)
                with open(temp_path, "wb") as f:
                    f.write(attachment.content)

                entity.name = f"{email.subject}_{attachment.filename}"
                entity.source = temp_path

                if "已加密" in email.body_text:
                    entity.needs_password = True
                else:
                    entity.needs_password = False

                entities.append(entity)

        return entities
