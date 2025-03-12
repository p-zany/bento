"""
Gmail source implementation.
"""

import base64
import os
import socket
from datetime import datetime
from typing import Awaitable, Callable

import json
import schedule
from google.auth.transport.requests import Request
from google.cloud import pubsub_v1
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger

from . import Entity
from .email import Email, EmailAttachment, EmailSource


class GmailSource(EmailSource):
    def __init__(
        self,
        client_secret_file: str,
        client_token_file: str,
        service_account_file: str,
        history_id: str = None,
        label: str = "Bento",
        project_id: str = "Bento",
        subscription_id: str = None,
        topic_name: str = None,
    ):
        super().__init__()
        self.client_secret_file = client_secret_file
        self.client_token_file = client_token_file
        self.service_account_file = service_account_file
        self.service = None
        self._label = label
        self._watched_topic = f"projects/{project_id}/topics/{topic_name}"
        self._project_id = project_id
        self._subscription_id = subscription_id
        self._subscriber = None
        self._subscription_path = None
        self._streaming_pull_future = None

        assert self._authenticate(), "Failed to authenticate with Gmail"

        schedule.every().day.do(self._setup_watch, self._watched_topic).tag(
            "watch_renewal"
        )
        schedule.run_all()

    def subscribe(
        self,
        on_ledger: Callable[[Entity], None],
        on_auth_request: Callable[[str], Awaitable[str]] = None,
    ) -> None:
        self._streaming_pull_future = self._subscriber.subscribe(
            self._subscription_path,
            callback=lambda message: self._process_pubsub_message(
                message, on_ledger, on_auth_request
            ),
        )

        logger.info(f"Subscribed to Gmail notifications on {self._subscription_path}")

    def unsubscribe(self) -> None:
        try:
            self.service.users().stop(userId="me").execute()
            logger.info("Gmail watch stopped")
        except Exception as e:
            logger.error(f"Failed to stop Gmail watch: {e}")

        if self._streaming_pull_future:
            self._streaming_pull_future.cancel()
            self._streaming_pull_future = None

        if self._subscriber:
            self._subscriber.close()
            self._subscriber = None

        schedule.clear("watch_renewal")

        logger.info("Unsubscribed from Gmail notifications")

    def _authenticate(self) -> bool:
        # 使用OAuth认证Gmail
        try:
            socket.setdefaulttimeout(600)
            # Gmail认证
            gmail_scopes = ["https://www.googleapis.com/auth/gmail.readonly"]

            # 尝试从文件加载OAuth凭据
            gmail_creds = None
            if os.path.exists(self.client_token_file):
                try:
                    gmail_creds = Credentials.from_authorized_user_file(
                        self.client_token_file, scopes=gmail_scopes
                    )
                except Exception as e:
                    logger.warning(f"Could not load credentials from file: {e}")

            # 检查凭据是否有效
            if not gmail_creds or not gmail_creds.valid:
                if gmail_creds and gmail_creds.expired and gmail_creds.refresh_token:
                    gmail_creds.refresh(Request())
                else:
                    # 使用客户端密钥文件创建OAuth流
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.client_secret_file, gmail_scopes
                    )
                    gmail_creds = flow.run_local_server(port=0, open_browser=False)

                # 保存凭据
                with open(self.client_token_file, "w") as token_file:
                    token_file.write(gmail_creds.to_json())

            # 构建Gmail服务
            self.service = build("gmail", "v1", credentials=gmail_creds)
            logger.info("Authenticated with Gmail using OAuth")

            # 使用Service Account认证PubSub
            if not self.service_account_file:
                logger.error("Service account file not specified for PubSub")
                return False

            if not os.path.exists(self.service_account_file):
                logger.error(
                    f"Service account file not found: {self.service_account_file}"
                )
                return False

            pubsub_scopes = [
                "https://www.googleapis.com/auth/pubsub",
                "https://www.googleapis.com/auth/cloud-platform",
            ]

            pubsub_credentials = service_account.Credentials.from_service_account_file(
                self.service_account_file, scopes=pubsub_scopes
            )

            self._subscriber = pubsub_v1.SubscriberClient(
                credentials=pubsub_credentials
            )
            self._subscription_path = self._subscriber.subscription_path(
                self._project_id, self._subscription_id
            )
            logger.info("Authenticated with PubSub using Service Account")

            return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def _setup_watch(self, topic_path) -> None:
        request = {
            "labelIds": ["INBOX"],
            "topicName": topic_path,
        }
        try:
            response = self.service.users().watch(userId="me", body=request).execute()
            logger.info(
                f"Gmail watch set up/renewed for topic: {topic_path} with response: {response}"
            )
        except Exception as e:
            logger.error(f"Failed to set up/renew Gmail watch: {e}")

    def _process_pubsub_message(self, message, on_ledger, on_auth_request):
        logger.info(f"Get and process pubsub message: {message}")
        try:
            data = json.loads(message.data.decode("utf-8"))
            logger.info(f"Decoded pubsub message: {data}")

            history_id = data.get("historyId")

            email = self._process_gmail_message(history_id)
            if email:
                entities = self._parse_email(email)
                for entity in entities:
                    on_ledger(entity)

                # message.ack()

        except Exception as e:
            logger.error(f"Error processing pubsub message: {e}")

    def _process_gmail_message(self, history_id):
        try:
            result = (
                self.service.users()
                .history()
                .list(
                    userId="me",
                    historyTypes=["messageAdded"],
                    maxResults=1,
                    startHistoryId=history_id,
                )
                .execute()
            )

            logger.info(f"Gmail history from {history_id}: {result}")

            message = result["history"][0]["messages"][0]

            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=message["id"])
                .execute()
            )

            logger.info("get Gmail message")

            headers = {h["name"]: h["value"] for h in message["payload"]["headers"]}

            sender = headers.get("From", "")
            recipient = headers.get("To", "")
            subject = headers.get("Subject", "")
            date_str = headers.get("Date", "")
            date = (
                datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
                if date_str
                else datetime.now()
            )

            body_text = ""
            body_html = None
            attachments = []

            parts = [message["payload"]]
            while parts:
                part = parts.pop(0)

                if "parts" in part:
                    parts.extend(part["parts"])

                if "body" in part and "data" in part["body"]:
                    if part["mimeType"] == "text/plain":
                        body_text = base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8")
                    elif part["mimeType"] == "text/html":
                        body_html = base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8")

                if (
                    part.get("filename")
                    and "body" in part
                    and "attachmentId" in part["body"]
                ):
                    attachment = (
                        self.service.users()
                        .messages()
                        .attachments()
                        .get(
                            userId="me",
                            messageId=message["id"],
                            id=part["body"]["attachmentId"],
                        )
                        .execute()
                    )

                    content = base64.urlsafe_b64decode(attachment["data"])

                    attachments.append(
                        EmailAttachment(
                            filename=part["filename"],
                            content_type=part["mimeType"],
                            content=content,
                        )
                    )

            email = Email(
                message_id=message["id"],
                sender=sender,
                recipient=recipient,
                subject=subject,
                date=date,
                body_text=body_text,
                body_html=body_html,
                attachments=attachments,
            )

            return email
        except Exception as e:
            logger.error(f"Error processing Gmail message {history_id}: {e}")
            return None
