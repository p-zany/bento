import datetime
import os
import re
from dataclasses import dataclass
from typing import List, Optional

import pdfplumber
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from beancount.ingest import importer
from beancount.ingest.cache import _FileMemo
from config import settings
from loguru import logger

apps = ["微信", "支付宝"]


@dataclass(frozen=True)
class Record:
    card_last_four: str
    transaction_date: datetime.date
    transaction_time: datetime.time
    currency: str
    is_expense: bool
    amount: Amount
    balance: Amount
    transaction_name: str
    transaction_channel: str
    transaction_site: str
    comment: str
    counterparty_account_name: str
    counterparty_card_number: str
    counterparty_bank: str


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
            for idx, page in enumerate(pdf.pages):
                if idx == 0:
                    text = page.extract_text()

                    if "中国银行交易流水明细清单" not in text:
                        logger.error(f"File {file_name} is not a valid BOC bill")
                        return None

                    title = "中国银行交易流水明细清单"

                    match = re.search(r"交易区间：\s+(\d{4}-\d{2}-\d{2})", text)
                    if match:
                        file_date = datetime.datetime.strptime(
                            match.group(1), "%Y-%m-%d"
                        ).date()
                    else:
                        logger.error(f"Failed to parse file date: {text}")
                        return None

                    match = re.search(r"借记卡号：\s+(\d{19})", text)
                    if match:
                        card_last_four = match.group(1)[-4:]
                    else:
                        logger.error(f"Failed to parse card last four: {text}")
                        return None

                tables = page.extract_tables()
                for table in tables:
                    if "记账日期" not in table[0][0] and not re.match(
                        r"\d{4}-\d{2}-\d{2}", table[0][0]
                    ):
                        logger.debug(f"Skip table because of header: {table[0][0]}")
                        continue

                    for row in table:
                        if "记账日期" in row[0]:
                            continue

                        transaction_date = datetime.datetime.strptime(
                            row[0], "%Y-%m-%d"
                        ).date()
                        transaction_time = datetime.datetime.strptime(
                            row[1], "%H:%M:%S"
                        ).time()

                        currency = row[2]
                        if currency != "人民币":
                            logger.warning(f"Unsupported currency: {currency}")
                            continue

                        is_expense = row[3][0] == "-"
                        amount = D(row[3][1:]) if is_expense else D(row[3])
                        balance = D(row[4])
                        transaction_name = row[5].replace("\n", "")
                        transaction_channel = row[6].replace("\n", "")
                        transaction_site = row[7].replace("\n", "")
                        comment = row[8].replace("\n", "")
                        counterparty_account_name = row[9].replace("\n", "")
                        counterparty_card_number = row[10].replace("\n", "")
                        counterparty_bank = row[11].replace("\n", "")

                        records.append(
                            Record(
                                card_last_four,
                                transaction_date,
                                transaction_time,
                                currency,
                                is_expense,
                                amount,
                                balance,
                                transaction_name,
                                transaction_channel,
                                transaction_site,
                                comment,
                                counterparty_account_name,
                                counterparty_card_number,
                                counterparty_bank,
                            )
                        )

        logger.info(f"Extracted {len(records)} records from {file_name}")
        return PDFStatement(title, file_date, records)
    except Exception as e:
        logger.error(f"Error extracting PDF content: {e}")
        return None


class Importer(importer.ImporterProtocol):
    def __init__(
        self,
        account: str,
        expense_account: str,
        income_account: str,
        ignore_apps: bool,
        classifier=None,
    ):
        self.account = account
        self.default_expense_account = expense_account
        self.default_income_account = income_account
        self.ignore_apps = ignore_apps
        self.classifier = classifier

    def name(self) -> str:
        """Return a unique identifier for the importer instance."""
        return "boc"

    def identify(self, file: _FileMemo) -> bool:
        """Return true if the identifier is able to process the file."""
        if not file.name.endswith(".pdf") and not file.name.endswith(".PDF"):
            logger.info(f"File {file.name} is not a PDF")
            return False

        pdf_statement = file.convert(extract_pdf_content)
        if not pdf_statement:
            logger.info(f"File {file.name} is not a valid PDF")
            return False
        return pdf_statement.title == "中国银行交易流水明细清单"

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from the file."""
        entries = []
        pdf_statement = file.convert(extract_pdf_content)
        for record in pdf_statement.records:
            transaction = self._parse_transaction(
                file.name, record.card_last_four, record
            )
            if transaction:
                entries.append(transaction)

        return entries

    def file_account(self, file: _FileMemo) -> str:
        """Return an account name associated with the given file for this importer."""
        pdf_statement = file.convert(extract_pdf_content)
        if not pdf_statement or not pdf_statement.records:
            raise ValueError(f"No records found in {file.name}")
        return f"{self.account}:{pdf_statement.records[0].card_last_four}"

    def file_date(self, file: _FileMemo) -> datetime.date:
        """Return a date associated with the downloaded file
        (e.g., the statement date)."""
        pdf_statement = file.convert(extract_pdf_content)
        if not pdf_statement:
            raise ValueError(f"No PDF statement found in {file.name}")
        return pdf_statement.file_date

    # def file_name(self, file: _FileMemo) -> str:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return file.name

    def _parse_transaction(
        self, file_name: str, card_last_four: str, record: Record
    ) -> Optional[data.Transaction]:
        """Parse a single transaction from the record."""
        try:
            transaction_date = record.transaction_date
            transaction_time = record.transaction_time

            currency_str = record.currency
            if currency_str != "人民币":
                logger.warning(f"Unsupported currency: {currency_str}")
                return None

            is_expense = record.is_expense
            amount = record.amount

            payee = (
                f"{record.counterparty_account_name} {record.counterparty_card_number}"
            )
            narration = f"{record.transaction_name} {record.transaction_channel}"

            reliable = False
            if self.classifier:
                reliable, predicted_account = self.classifier(payee, narration)

            postings = []
            if is_expense:
                postings.extend(
                    [
                        data.Posting(
                            account=f"{self.account}:{card_last_four}",
                            units=None,
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
                            units=Amount(amount, "CNY"),
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
                            units=Amount(amount, "CNY"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                        data.Posting(
                            account=(
                                predicted_account
                                if reliable
                                else self.default_income_account
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
            meta["time"] = transaction_time.strftime("%H:%M:%S")
            if self.ignore_apps:
                if any(app in payee for app in apps):
                    meta[settings.ledger.duplicate_meta] = True

            return data.Transaction(
                meta=meta,
                date=transaction_date,
                flag="*" if reliable else "!",
                payee=payee,
                narration=narration,
                tags=set(),
                links=set(),
                postings=postings,
            )

        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None
