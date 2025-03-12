import datetime
import os
import re
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from beancount.ingest import importer
from beancount.ingest.cache import _FileMemo
from config import settings
from loguru import logger

apps = ["财付通", "支付宝"]


@dataclass(frozen=True)
class Record:
    transaction_date: datetime.date
    posted_date: datetime.date
    transaction_description: str
    card_last_four: str
    positive_amount: bool
    amount: D


@dataclass(frozen=True)
class XLSStatement:
    title: str
    file_date: datetime.date
    records: List[Record]


def extract_xls_content(file_name: str) -> XLSStatement:
    """Extract XLS file content."""
    match = re.search(r"(.*)-(\d{4}-\d{2}).xls", file_name)
    if not match:
        raise ValueError(f"File {file_name} is not a valid XLS")

    title = match.group(1)
    file_date = datetime.datetime.strptime(match.group(2), "%Y-%m").date()

    try:
        df = pd.read_excel(file_name, skiprows=1)
        records = []

        for _, row in df.iterrows():
            # 跳过空行
            if pd.isna(row["交易日期"]):
                continue

            # 解析日期
            transaction_date = datetime.datetime.strptime(
                row["交易日期"], "%Y-%m-%d"
            ).date()
            posted_date = datetime.datetime.strptime(row["入账日期"], "%Y-%m-%d").date()

            # 获取金额并判断正负
            amount = D(str(abs(row["交易金额"])))
            positive_amount = row["交易金额"] >= 0

            record = Record(
                transaction_date=transaction_date,
                posted_date=posted_date,
                transaction_description=str(row["交易描述"]),
                card_last_four=str(row["卡末四位"]),
                positive_amount=positive_amount,
                amount=amount,
            )
            records.append(record)

        return XLSStatement(title=title, file_date=file_date, records=records[::-1])

    except Exception as e:
        logger.error(f"Error extracting XLS content: {e}")
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
        return "citic_credit"

    def identify(self, file: _FileMemo) -> bool:
        """Return true if the identifier is able to process the file."""
        if not file.name.endswith(".xls"):
            logger.info(f"File {file.name} is not a valid XLS")
            return False

        xls_statement = file.convert(extract_xls_content)
        if not xls_statement:
            logger.info(f"File {file.name} is not a valid XLS")
            return False

        if "citic" not in xls_statement.title.lower():
            logger.info(f"File {file.name} is not a Citic credit bill")
            return False

        return True

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from CITIC credit card statement."""
        entries = []
        xls_statement = file.convert(extract_xls_content)
        for record in xls_statement.records:
            transaction = self._parse_transaction(file.name, record)
            if transaction:
                entries.append(transaction)
        return entries

    def file_account(self, file: _FileMemo) -> str:
        """Return the account for the file."""
        return self.account

    def file_date(self, file: _FileMemo) -> Optional[datetime.date]:
        """Return a date associated with the downloaded file
        (e.g., the statement date)."""
        xls_statement = file.convert(extract_xls_content)
        return xls_statement.file_date

    # def file_name(self, file: _FileMemo) -> Optional[str]:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return None

    def _parse_transaction(
        self, file_name: str, record: Record
    ) -> Optional[data.Transaction]:
        """Parse a single transaction record."""
        try:
            transaction_date = (
                record.transaction_date
                if record.transaction_date
                else record.posted_date
            )
            card_last_four = record.card_last_four

            description = record.transaction_description
            if "－" in description:
                payee, narration = description.split("－", 1)
            else:
                payee = description
                narration = ""

            is_expense = record.positive_amount

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
                            units=Amount(record.amount, "CNY"),
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
                            units=Amount(record.amount, "CNY"),
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
