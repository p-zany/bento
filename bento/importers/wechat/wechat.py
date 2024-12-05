import csv
import os
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from beancount.core import data
from beancount.core.amount import Amount
from beancount.core.number import D
from beancount.ingest import importer
from beancount.ingest.cache import _FileMemo
from loguru import logger


@dataclass(frozen=True)
class Record:
    transaction_time: datetime
    transaction_category: str
    transaction_counterparty: str
    product: str
    income_expense: str
    amount: D
    payment_method: str
    transaction_status: str
    wechat_trade_no: str
    out_trade_no: str
    note: str


@dataclass(frozen=True)
class CSVStatement:
    title: str
    file_date: datetime.date
    records: List[Record]


def extract_csv_content(file_name: str) -> CSVStatement:
    """Extract CSV file content."""
    records = []
    try:
        with open(file_name, newline="", encoding="utf-8") as csvfile:
            lines = csvfile.readlines()

            header_idx = 0
            for idx, line in enumerate(lines):
                if idx == 0:
                    title = line.strip()
                if "起始时间" in line:
                    match = re.search(r"起始时间：\[(\d{4}-\d{2}-\d{2}).*", line)
                    if match:
                        file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if "交易时间" in line:
                    header_idx = idx
                    break

            reader = csv.DictReader(lines[header_idx:])
            for row in reader:
                records.append(
                    Record(
                        transaction_time=datetime.strptime(
                            row["交易时间"], "%Y-%m-%d %H:%M:%S"
                        ),
                        transaction_category=row["交易类型"],
                        transaction_counterparty=row["交易对方"],
                        product=row["商品"],
                        income_expense=row["收/支"],
                        amount=D(row["金额(元)"].replace("¥", "")),
                        payment_method=row["支付方式"],
                        transaction_status=row["当前状态"],
                        wechat_trade_no=row["交易单号"],
                        out_trade_no=row["商户单号"],
                        note=row["备注"],
                    )
                )
        return CSVStatement(title=title, file_date=file_date, records=records)
    except Exception as e:
        logger.error(f"Error extracting CSV content: {e}")
        return None


class Importer(importer.ImporterProtocol):
    def __init__(
        self,
        account: str,
        fee_account: str,
        additional_accounts: Dict[str, str],
        expense_account: str,
        classifier=None,
    ):
        self.account = account
        self.default_expense_account = expense_account
        self.fee_account = fee_account
        self.additional_accounts = additional_accounts
        self.income_account = "Income:RedPacket"
        self.classifier = classifier
        self.comment_prefix = "转账备注:"

    def identify(self, file: _FileMemo) -> bool:
        if not file.name.endswith(".csv"):
            logger.info(f"File {file.name} is not a CSV")
            return False

        csv_statement = file.convert(extract_csv_content)
        if not csv_statement:
            logger.info(f"File {file.name} is not a valid CSV")
            return False

        if "微信支付账单明细" not in csv_statement.title:
            logger.info(f"File {file.name} is not a WeChat bill")
            return False

        return True

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from the file."""
        entries = []
        csv_statement = file.convert(extract_csv_content)

        for record in csv_statement.records:
            transaction = self._parse_transaction(file.name, record)
            if transaction:
                entries.append(transaction)

        return entries[::-1]  # Reverse the list to maintain chronological order

    def file_account(self, file: _FileMemo) -> str:
        """Return the account name."""
        return self.account

    def file_date(self, file: _FileMemo) -> Optional[datetime.date]:
        """Return a date associated with the downloaded file
        (e.g., the statement date)."""
        csv_statement = file.convert(extract_csv_content)
        return csv_statement.file_date

    # def file_name(self, file: _FileMemo) -> Optional[str]:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return None

    def _get_asset_account(self, payment_method: str) -> str:
        """Determine asset account based on payment method."""
        return self.additional_accounts.get(payment_method, self.account)

    def _parse_transaction(
        self, file_name: str, record: Record
    ) -> Optional[data.Transaction]:
        """Parse a single transaction record."""
        try:
            # Basic information parsing
            transaction_date = record.transaction_time.date()
            transaction_type = record.transaction_category
            payee = record.transaction_counterparty
            narration = record.product
            income_expense = record.income_expense
            payment_method = record.payment_method

            # Handle transfer notes
            if self.comment_prefix in narration:
                narration = narration.replace(self.comment_prefix, "")

            # Set metadata
            meta_kv = {
                "transaction_type": transaction_type,
                "payment_method": payment_method,
                "time": record.transaction_time.time().strftime("%H:%M:%S"),
            }
            if record.note and record.note != "/":
                meta_kv["note"] = record.note.strip()
            if record.wechat_trade_no:
                meta_kv["wechat_trade_no"] = record.wechat_trade_no.strip()
            if record.out_trade_no and record.out_trade_no != "/":
                meta_kv["out_trade_no"] = record.out_trade_no.strip()

            # Get asset account
            asset_account = self._get_asset_account(payment_method)

            reliable = False
            if self.classifier:
                reliable, predicted_account = self.classifier(payee, narration)

            # Create transaction
            postings = []
            if income_expense == "收入":
                postings.extend(
                    [
                        data.Posting(
                            account=asset_account,
                            units=Amount(record.amount, "CNY"),
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                        data.Posting(
                            account=self.income_account,
                            units=None,
                            cost=None,
                            price=None,
                            flag=None,
                            meta=None,
                        ),
                    ]
                )
            else:
                if transaction_type == "零钱提现":
                    fee = Decimal("0")
                    if record.note and "服务费" in record.note:
                        fee_match = re.search(r"服务费¥(\d+\.?\d*)", record.note)
                        if fee_match:
                            fee = Decimal(fee_match.group(1))
                    postings.extend(
                        [
                            data.Posting(
                                account=asset_account,
                                units=Amount(-record.amount, "CNY"),
                                cost=None,
                                price=None,
                                flag=None,
                                meta=None,
                            ),
                            data.Posting(
                                account=self._get_asset_account(payment_method),
                                units=None,
                                cost=None,
                                price=None,
                                flag=None,
                                meta=None,
                            ),
                            data.Posting(
                                account=self.fee_account,
                                units=Amount(fee, "CNY"),
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
                                account=asset_account,
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

            return data.Transaction(
                meta=data.new_metadata(os.path.basename(file_name), 0, meta_kv),
                date=transaction_date,
                flag=(
                    "*"
                    if income_expense == "收入"
                    or transaction_type == "零钱提现"
                    or reliable
                    else "!"
                ),
                payee=payee,
                narration=narration,
                tags=set(),
                links=set(),
                postings=postings,
            )

        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None
