import datetime
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pdfplumber
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from beancount.ingest import importer
from beancount.ingest.cache import _FileMemo
from config import settings
from loguru import logger

apps = ["微信"]


@dataclass(frozen=True)
class Record:
    transaction_date: datetime.date
    posted_date: datetime.date
    card_last_four: str
    description: str
    amount: D
    currency: str
    is_expense: bool


@dataclass(frozen=True)
class PDFStatement:
    title: str
    file_date: datetime.date
    records: List[Record]


def extract_pdf_content(file_name: str) -> Optional[PDFStatement]:
    """Extract PDF file content."""
    try:
        records = []
        with pdfplumber.open(file_name) as pdf:
            if not pdf.pages:
                logger.error(f"File {file_name} is not a valid PDF")
                return None

            match = re.search(
                r"(.*)\((\d{4}-\d{2})\)", pdf.pages[0].extract_text(), re.IGNORECASE
            )
            if not match:
                logger.error(f"File {file_name} is not a valid PDF")
                return None

            title = match.group(1)
            file_date = datetime.datetime.strptime(match.group(2), "%Y-%m").date()

            for i, page in enumerate(pdf.pages):
                # FIXME: 假设每次换币种, 会新开一页
                if "RMB Transaction Detailed List" in page.extract_text():
                    currency = "CNY"
                elif "FCY Transaction Detailed List" in page.extract_text():
                    currency = "USD"

                tables = page.extract_tables()
                logger.debug(f"Found {len(tables)} tables at page {i}")
                for table in tables:
                    if "交易日" not in table[0][0] and not re.match(
                        r"\d{4}-\d{2}-\d{2}", table[0][0]
                    ):
                        logger.debug(f"Skip table because of header: {table[0][0]}")
                        continue

                    for row in table:
                        if "交易日" in row[0]:
                            continue

                        transaction_date = datetime.datetime.strptime(
                            row[0], "%Y-%m-%d"
                        ).date()
                        posted_date = datetime.datetime.strptime(
                            row[1], "%Y-%m-%d"
                        ).date()
                        card_last_four = row[2]
                        description = row[3].replace("\n", "")
                        is_expense = bool(row[5].strip())
                        amount_str = (row[5] or row[4]).strip()
                        if not amount_str:
                            logger.warning(f"Skip row because of empty amount: {row}")
                            continue

                        amount = D(amount_str)

                        record = Record(
                            transaction_date=transaction_date,
                            posted_date=posted_date,
                            card_last_four=card_last_four,
                            description=description,
                            amount=amount,
                            currency=currency,
                            is_expense=is_expense,
                        )
                        records.append(record)

        logger.info(f"Extracted {len(records)} records from {file_name}")
        return PDFStatement(title=title, file_date=file_date, records=records)
    except Exception as e:
        logger.error(f"Error extracting PDF content: {e}")
        return None


class Importer(importer.ImporterProtocol):
    def __init__(
        self,
        account: str,
        expense_account: str,
        asset_account: str,
        ignore_apps: bool,
        classifier=None,
    ):
        self.account = account
        self.default_expense_account = expense_account
        self.asset_account = asset_account
        self.ignore_apps = ignore_apps
        self.classifier = classifier

    def name(self) -> str:
        return "boc_credit"

    def identify(self, file: _FileMemo) -> bool:
        """Identify if the file is a BOC credit card statement PDF."""
        if not file.name.endswith(".pdf") and not file.name.endswith(".PDF"):
            logger.info(f"File {file.name} is not a PDF")
            return False

        pdf_content = file.convert(extract_pdf_content)
        if not pdf_content:
            logger.info(f"File {file.name} is not a valid PDF")
            return False

        if "BOC Credit Card Billing Statement" not in pdf_content.title:
            logger.info(f"File {file.name} is not a BOC credit card statement")
            return False

        return True

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from BOC credit card statement."""
        entries = []
        cached_entries = {}
        pdf_content = file.convert(extract_pdf_content)
        for record in pdf_content.records:
            entry = self._parse_transaction(file.name, record, cached_entries)
            if entry:
                entries.append(entry)
        return entries

    def file_account(self, file: _FileMemo) -> str:
        """Return the account for the file with the most frequent card number."""
        pdf_content = file.convert(extract_pdf_content)
        if not pdf_content or not pdf_content.records:
            return self.account

        # Count occurrences of each card_last_four
        card_counts = {}
        for record in pdf_content.records:
            card_counts[record.card_last_four] = (
                card_counts.get(record.card_last_four, 0) + 1
            )

        # Get the most frequent card_last_four
        most_common_card = max(card_counts.items(), key=lambda x: x[1])[0]
        return f"{self.account}:{most_common_card}"

    def file_date(self, file: _FileMemo) -> Optional[datetime.date]:
        """Return a date associated with the downloaded file
        (e.g., the statement date)."""
        pdf_content = file.convert(extract_pdf_content)
        return pdf_content.file_date

    # def file_name(self, file: _FileMemo) -> Optional[str]:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return None

    def _parse_transaction(
        self,
        file_name: str,
        record: Record,
        cached_entries: Dict[Tuple[datetime.date, str, str, str], Record],
    ) -> Optional[data.Transaction]:
        """Parse a single transaction record."""
        try:
            transaction_date = record.posted_date
            card_last_four = record.card_last_four

            match = re.search(r"(.*)\[(.*?)\]", record.description)
            if match:
                payee = match.group(1).strip()
                narration = match.group(2).strip()
            else:
                payee = record.description
                narration = ""

            is_expense = record.is_expense

            reliable = False
            if self.classifier:
                reliable, predicted_account = self.classifier(payee, narration)

            if (transaction_date, card_last_four, payee) in cached_entries:
                logger.debug(f"Found cached transaction, append posting, {record}")
                entry = cached_entries[(transaction_date, card_last_four, payee)]
                data.create_simple_posting(
                    entry,
                    f"{self.account}:{card_last_four}",
                    -record.amount if is_expense else record.amount,
                    record.currency,
                )  # return a new posting
                return None  # skip creating a new transaction

            postings = []
            if is_expense:
                postings.extend(
                    [
                        data.Posting(
                            account=f"{self.account}:{card_last_four}",
                            units=-Amount(record.amount, record.currency),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                        data.Posting(
                            account=(
                                predicted_account
                                if reliable
                                else self.default_expense_account
                            ),
                            units=None,
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ]
                )
            else:
                postings.extend(
                    [
                        data.Posting(
                            account=f"{self.account}:{card_last_four}",
                            units=Amount(record.amount, record.currency),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                        data.Posting(
                            account=(
                                predicted_account if reliable else self.asset_account
                            ),
                            units=None,
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ]
                )

            meta = data.new_metadata(os.path.basename(file_name), 0)
            meta["transaction_date"] = record.transaction_date.strftime("%Y-%m-%d")
            if self.ignore_apps:
                if any(app in payee for app in apps):
                    meta[settings.ledger.duplicate_meta] = True

            entry = data.Transaction(
                meta=meta,
                date=transaction_date,
                flag="*" if reliable else "!",
                payee=payee,
                narration=narration,
                tags=set(),
                links=set(),
                postings=postings,
            )

            cached_entries[(transaction_date, card_last_four, payee)] = entry
            return entry

        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None
