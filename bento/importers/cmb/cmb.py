import csv
import datetime
import os
import re
from dataclasses import dataclass
from typing import List, Optional

from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from beancount.ingest import importer
from beancount.ingest.cache import _FileMemo
from config import settings
from loguru import logger

apps = ["财付通-"]


@dataclass(frozen=True)
class Record:
    card_last_four: str
    transaction_date: datetime.date
    transaction_time: datetime.time
    is_expense: bool
    amount: D
    balance: D
    transaction_type: str
    transaction_note: str


@dataclass(frozen=True)
class CSVStatement:
    title: str
    file_date: datetime.date
    records: List[Record]


def extract_csv_content(file_name: str) -> Optional[CSVStatement]:
    """Extract CSV content from the file."""
    records = []
    try:
        with open(file_name, "r") as csvfile:
            lines = csvfile.readlines()

            header_index = 0
            for i, line in enumerate(lines):
                if i == 0:
                    title = line.strip()
                if "账    号" in line:
                    match = re.search(r".*(\d{4})\s+.*", line)
                    if match:
                        card_last_four = match.group(1)
                if "起始日期" in line:
                    match = re.search(r".*\[(\d{8})\].+", line)
                    if match:
                        file_date = datetime.datetime.strptime(
                            match.group(1), "%Y%m%d"
                        ).date()
                if "交易日期" in line:
                    header_index = i
                    break

            # Extract valid data rows
            # starting from the header and skipping the last two lines
            reader = csv.DictReader(lines[header_index:-2])
            for row in reader:
                transaction_date = datetime.datetime.strptime(
                    row["交易日期"].strip(), "%Y%m%d"
                ).date()
                transaction_time = datetime.datetime.strptime(
                    row["交易时间"].strip(), "%H:%M:%S"
                ).time()
                is_expense = row["收入"].strip() == ""
                amount = D(row["收入" if not is_expense else "支出"].strip())
                balance = D(row["余额"].strip())
                transaction_type = row["交易类型"].strip()
                transaction_note = row["交易备注"].strip()
                records.append(
                    Record(
                        card_last_four,
                        transaction_date,
                        transaction_time,
                        is_expense,
                        amount,
                        balance,
                        transaction_type,
                        transaction_note,
                    )
                )

            logger.info(f"Extracted {len(records)} transactions")
            return CSVStatement(title, file_date, records)
    except Exception as e:
        logger.error(f"Error extracting CSV content: {e}")
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
        self.income_account = income_account
        self.ignore_apps = ignore_apps
        self.classifier = classifier

    def name(self) -> str:
        """Return a unique identifier for the importer instance."""
        return "cmb"

    def identify(self, file: _FileMemo) -> bool:
        """Return true if the identifier is able to process the file."""
        if not file.name.endswith(".csv"):
            logger.info(f"File {file.name} is not a CSV")
            return False

        csv_statement = file.convert(extract_csv_content)
        if not csv_statement:
            return False
        return "招商银行交易记录" in csv_statement.title

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from the file."""
        entries = []
        csv_statement = file.convert(extract_csv_content)

        for record in csv_statement.records:
            transaction = self._parse_transaction(file.name, record)
            if transaction:
                entries.append(transaction)

        return entries[::-1]

    def file_account(self, file: _FileMemo) -> str:
        """Return an account name associated with the given file for this importer."""
        csv_statement = file.convert(extract_csv_content)
        return f"{self.account}:{csv_statement.records[0].card_last_four}"

    def file_date(self, file: _FileMemo) -> datetime.date:
        """Return a date associated with the downloaded file
        (e.g., the statement date)."""
        try:
            with open(file.name, "r") as f:
                for line in f:
                    if "起始日期" in line:
                        # Extract date from format like
                        # "# 起始日期: [20240801]   终止日期: [20240930]"
                        date_str = line.split("[")[1].split("]")[0].strip()
                        return datetime.datetime.strptime(date_str, "%Y%m%d").date()
        except Exception as e:
            logger.error(f"Error getting file date: {e}")
        return None

    # def file_name(self) -> Optional[str]:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return None

    def _parse_transaction(
        self, file_name: str, record: Record
    ) -> Optional[data.Transaction]:
        """Parse a single transaction record."""
        try:
            is_expense = record.is_expense

            # Set merchant name and description
            payee = record.transaction_type
            narration = record.transaction_note

            reliable = False
            if self.classifier:
                reliable, predicted_account = self.classifier(payee, narration)

            postings = []
            if is_expense:
                postings.extend(
                    [
                        data.Posting(
                            account=f"{self.account}:{record.card_last_four}",
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
                            units=Amount(record.amount, "CNY"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ]
                )
            else:  # Income
                postings.extend(
                    [
                        data.Posting(
                            account=f"{self.account}:{record.card_last_four}",
                            units=Amount(record.amount, "CNY"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                        data.Posting(
                            account=(
                                predicted_account if reliable else self.income_account
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
            meta["time"] = record.transaction_time.strftime("%H:%M:%S")

            if self.ignore_apps:
                if any(app in narration for app in apps):
                    meta[settings.ledger.duplicate_meta] = True

            return data.Transaction(
                meta=meta,
                date=record.transaction_date,
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
