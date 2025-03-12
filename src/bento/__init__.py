"""
Command-line entry point for Bento application.
"""

import time

import schedule
from loguru import logger

from .config import Settings
from .source.gmail import GmailSource


def main() -> None:
    import ssl

    print(ssl.OPENSSL_VERSION)

    settings = Settings()
    gmail_source = GmailSource(
        client_secret_file=settings.source.gmail.client_secret_file,
        client_token_file=settings.source.gmail.client_token_file,
        service_account_file=settings.source.gmail.service_account_file,
        history_id=settings.source.gmail.history_id,
        label=settings.source.gmail.label,
        project_id=settings.source.gmail.project_id,
        subscription_id=settings.source.gmail.subscription_id,
        topic_name=settings.source.gmail.topic_name,
    )

    gmail_source.subscribe(
        on_ledger=lambda entity: print(entity),
        on_auth_request=lambda auth_request: auth_request,
    )

    logger.info("Starting scheduler loop...")
    while True:
        schedule.run_pending()
        time.sleep(1)
