"""
Database models for Bento application.
"""

import datetime
import json
import uuid
from enum import Enum
from typing import Any, Dict

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from bento.db.database import Base


class Subscriber(Base):
    """Telegram subscriber model."""

    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_activity_at = Column(DateTime, default=datetime.datetime.utcnow)

    # 关联的密码请求
    password_requests = relationship("PasswordRequest", back_populates="subscriber")

    def __repr__(self):
        return f"<Subscriber(id={self.id}, user_id={self.user_id}, username={self.username})>"

    @property
    def display_name(self) -> str:
        """获取用户的显示名称"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.username:
            return self.username
        else:
            return f"User {self.user_id}"


class PasswordRequestStatus(Enum):
    """密码请求状态枚举"""

    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELED = "canceled"


class PasswordRequest(Base):
    """密码请求模型，用于跟踪需要用户提供密码的请求"""

    __tablename__ = "password_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    subscriber_id = Column(Integer, ForeignKey("subscribers.id"), nullable=False)
    email_id = Column(String(255), nullable=False)
    email_subject = Column(String(255), nullable=True)
    attachment_index = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    status = Column(String(20), default=PasswordRequestStatus.PENDING.value)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # 用于存储附加数据的JSON字段
    metadata = Column(Text, nullable=True)

    # 关联的订阅者
    subscriber = relationship("Subscriber", back_populates="password_requests")

    def __repr__(self):
        return f"<PasswordRequest(id={self.id}, subscriber_id={self.subscriber_id}, filename={self.filename})>"

    @property
    def metadata_dict(self) -> Dict[str, Any]:
        """将元数据JSON转换为字典"""
        if not self.metadata:
            return {}
        try:
            return json.loads(self.metadata)
        except (json.JSONDecodeError, TypeError):
            return {}

    @metadata_dict.setter
    def metadata_dict(self, value: Dict[str, Any]):
        """将字典转换为元数据JSON"""
        if value is None:
            self.metadata = None
        else:
            self.metadata = json.dumps(value)

    def update_status(self, status: PasswordRequestStatus):
        """更新请求状态"""
        self.status = status.value
        self.updated_at = datetime.datetime.utcnow()


class EmailProcessingRecord(Base):
    """电子邮件处理记录，用于跟踪已处理的邮件以避免重复处理"""

    __tablename__ = "email_processing_records"

    id = Column(Integer, primary_key=True)
    email_id = Column(String(255), unique=True, nullable=False)
    sender = Column(String(255), nullable=False)
    subject = Column(String(512), nullable=True)
    attachments_count = Column(Integer, default=0)
    processed_successfully = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<EmailProcessingRecord(id={self.id}, email_id={self.email_id}, success={self.processed_successfully})>"
