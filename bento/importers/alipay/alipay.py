import csv
import os
import re
from dataclasses import dataclass
from datetime import datetime
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
    counterparty_account: str
    product_description: str
    income_expense: str
    amount: D
    payment_method: str
    transaction_status: str
    transaction_order_number: str
    merchant_order_number: str
    notes: str


@dataclass(frozen=True)
class CVSStatement:
    title: str
    file_date: datetime.date
    records: List[Record]


def extract_csv_content(file_name: str) -> CVSStatement:
    """Extract CSV file content."""
    content = []
    try:
        with open(file_name, "rb") as csvfile:
            all_lines = csvfile.read().decode("gbk")
            lines = all_lines.split("\n")

            header_idx = 0
            for idx, line in enumerate(lines):
                if "起始时间" in line:
                    match = re.search(r"起始时间：\[(\d{4}-\d{2}-\d{2}).*", line)
                    if match:
                        file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if "支付宝（中国）网络技术有限公司  电子客户回单" in line:
                    title = line.strip("-")
                if "交易时间" in line:
                    header_idx = idx
                    break

            reader = csv.DictReader(lines[header_idx:])
            for row in reader:
                content.append(
                    Record(
                        transaction_time=datetime.strptime(
                            row["交易时间"], "%Y-%m-%d %H:%M:%S"
                        ),
                        transaction_category=row["交易分类"],
                        transaction_counterparty=row["交易对方"],
                        counterparty_account=row["对方账号"],
                        product_description=row["商品说明"],
                        income_expense=row["收/支"],
                        amount=D(row["金额"]),
                        payment_method=row["收/付款方式"],
                        transaction_status=row["交易状态"],
                        transaction_order_number=row["交易订单号"],
                        merchant_order_number=row["商家订单号"],
                        notes=row["备注"],
                    )
                )

        logger.info(f"Extracted {len(content)} transactions")
        return CVSStatement(title=title, file_date=file_date, records=content)
    except Exception as e:
        logger.error(f"Error extracting CSV content: {e}")
        return None


class Importer(importer.ImporterProtocol):
    def __init__(
        self,
        account: str,
        additional_accounts: Dict[str, str],
        expense_account: str,
        classifier=None,
    ):
        self.account = account
        self.default_expense_account = expense_account
        self.additional_accounts = additional_accounts
        self.income_account = "Income:RedPacket"
        self.classifier = classifier
        self.comment_prefix = "转账备注:"

    def name(self) -> str:
        """Return a unique identifier for the importer instance."""
        return "alipay"

    def identify(self, file: _FileMemo) -> bool:
        """Return true if the identifier is able to process the file."""
        if not file.name.endswith(".csv"):
            logger.info(f"File {file.name} is not a CSV")
            return False

        csv_statement = file.convert(extract_csv_content)
        if not csv_statement:
            logger.info(f"File {file.name} is not a valid CSV")
            return False

        if "支付宝（中国）网络技术有限公司  电子客户回单" not in csv_statement.title:
            logger.info(f"File {file.name} is not a Alipay bill")
            return False

        return True

    def extract(self, file: _FileMemo) -> List[data.Transaction]:
        """Extract transactions from the file."""
        entries = []
        csv_statement = file.convert(extract_csv_content)
        for row in csv_statement.records:
            transaction = self._parse_transaction(file.name, row)
            if transaction:
                entries.append(transaction)
        return entries

    def file_account(self, file: _FileMemo) -> str:
        """Return the account for the file."""
        return self.account

    def file_date(self, file: _FileMemo) -> Optional[datetime.date]:
        """Return a date associated with the downloaded file
        (e.g., the statement date)."""
        csv_statement = file.convert(extract_csv_content)
        return csv_statement.file_date

    # def file_name(self) -> Optional[str]:
    #     """Return a cleaned up filename for storage (optional)."""
    #     return None

    def _parse_transaction(
        self, file_name: str, row: List[str]
    ) -> Optional[data.Transaction]:
        """Parse a single transaction record."""
        try:
            # 基本信息解析
            transaction_type = row.transaction_category
            payee = row.transaction_counterparty
            if payee == "余额宝":
                return None  # treat yuebao same as alipay

            narration = f"{row.transaction_category} {row.product_description}"

            is_expense = bool(row.income_expense == "支出")
            amount = row.amount
            payment_method = row.payment_method

            # 设置元数据
            meta_kv = {
                "transaction_type": transaction_type,
                "payment_method": payment_method,
            }
            if row.transaction_order_number:  # 交易单号
                meta_kv["alipay_trade_no"] = row.transaction_order_number.strip()
            if (
                row.merchant_order_number and row.merchant_order_number != "/"
            ):  # 商户单号
                meta_kv["out_trade_no"] = row.merchant_order_number.strip()

            asset_account = self._get_asset_account(payment_method)

            reliable = False
            if self.classifier:
                reliable, predicted_account = self.classifier(payee, narration)

            # 创建交易
            postings = []
            if is_expense:
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
                            account=asset_account,
                            units=Amount(amount, "CNY"),
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

            return data.Transaction(
                meta=data.new_metadata(os.path.basename(file_name), 0, meta_kv),
                date=row.transaction_time.date(),
                flag="*" if reliable else "!",
                payee=payee,
                narration=narration,
                tags=set(),
                links=set(),
                postings=postings,
            )

        except ValueError as e:
            logger.error(f"Invalid amount: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None

    def _get_asset_account(self, payment_method: str) -> str:
        """Determine asset account based on payment method."""
        return self.additional_accounts.get(payment_method, self.account)
