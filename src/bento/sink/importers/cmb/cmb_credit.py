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
    transaction_type: str
    transaction_date: datetime.date
    posted_date: datetime.date
    transaction_description: str
    amount: D
    card_last_four: str


@dataclass(frozen=True)
class PDFStatement:
    title: str
    file_date: datetime.date
    records: List[Record]


def extract_pdf_content(file_name: str) -> PDFStatement:
    """Extract PDF file content."""
    try:
        with pdfplumber.open(file_name) as pdf:
            records = []
            state = "还款"
            first_page = True
            title = None
            file_date = None
            data_flag = False

            for page in pdf.pages:
                text = page.extract_text()
                lines = text.split("\n")
                start = False

                for line in lines:
                    if title is None:
                        title = line
                        continue
                    if file_date is None:
                        if "账单日" in line:
                            data_flag = True
                            continue
                    if data_flag and file_date is None:
                        file_date = datetime.datetime.strptime(
                            line.split()[0], "%Y年%m月%d日"
                        ).date()
                        continue
                    if (first_page and "SOLD" in line) or (
                        not first_page and "CMB Credit Card Statement" in line
                    ):
                        start = True
                        continue
                    if "本期还款总额 = " in line:  # finish
                        break
                    if not start:
                        continue

                    if line == "还款":
                        state = "还款"
                        continue
                    if line == "消费":
                        state = "消费"
                        continue
                    if line == "退款":
                        state = "退款"
                        continue
                    if state == "还款":
                        match = re.search(
                            r"(\d{2}\/\d{2})\s+(.+)\s-?(\d+\.\d{2})\s+(\d{4})\s+(.+)",
                            line,
                        )
                        if not match:
                            logger.warning(f"Error parsing line: {line}")
                            continue
                        records.append(
                            Record(
                                transaction_type=state,
                                transaction_date=None,
                                posted_date=(
                                    datetime.datetime.strptime(
                                        f"{file_date.year}/{match.group(1)}", "%Y/%m/%d"
                                    ).date()
                                ),
                                transaction_description=match.group(2),
                                amount=D(match.group(3)),
                                card_last_four=match.group(4),
                            )
                        )
                    if state == "退款" or state == "消费":
                        match = re.search(
                            r"""
                            (\d{2}/\d{2})\s+    # transaction date
                            (\d{2}/\d{2})\s+    # posted date
                            (.+)\s+             # description
                            -?(\d+\.\d{2})\s+   # amount
                            (\d{4})\s+          # card last four
                            (.+)                # notes
                            """,
                            line,
                            re.VERBOSE,
                        )
                        if not match:
                            logger.warning(f"Error parsing line: {line}")
                            continue
                        records.append(
                            Record(
                                transaction_type=state,
                                transaction_date=(
                                    datetime.datetime.strptime(
                                        f"{file_date.year}/{match.group(1)}", "%Y/%m/%d"
                                    ).date()
                                ),
                                posted_date=(
                                    datetime.datetime.strptime(
                                        f"{file_date.year}/{match.group(2)}", "%Y/%m/%d"
                                    ).date()
                                ),
                                transaction_description=match.group(3),
                                amount=D(match.group(4)),
                                card_last_four=match.group(5),
                            )
                        )

                first_page = False

            logger.info(f"Extracted {len(records)} transactions")
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
        return "cmb_credit"

    def identify(self, file: _FileMemo) -> bool:
        """Return true if the identifier is able to process the file."""
        if not file.name.endswith(".pdf") and not file.name.endswith(".PDF"):
            logger.info(f"File {file.name} is not a PDF")
            return False

        pdf_statement = file.convert(extract_pdf_content)
        if not pdf_statement:
            logger.info(f"File {file.name} is not a valid PDF")
            return False

        if "招商银行信用卡对账单" not in pdf_statement.title:
            logger.info(f"File {file.name} is not a CMB credit bill")
            return False

        return True

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from CMB credit card statement."""
        entries = []
        pdf_statement = file.convert(extract_pdf_content)
        for record in pdf_statement.records:
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
        pdf_statement = file.convert(extract_pdf_content)
        return pdf_statement.file_date

    # def file_name(self, file: _FileMemo) -> Optional[str]:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return None

    def _parse_transaction(
        self, file_name: str, record: Record
    ) -> Optional[data.Transaction]:
        """解析单条交易记录"""
        try:
            transaction_date = (
                record.transaction_date
                if record.transaction_date
                else record.posted_date
            )
            card_last_four = record.card_last_four

            description = record.transaction_description
            if "-" in description:
                payee, narration = description.split("-", 1)
            else:
                payee = description
                narration = ""

            is_expense = record.transaction_type == "消费"

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
            if record.transaction_type == "还款":
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
