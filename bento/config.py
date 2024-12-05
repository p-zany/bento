from typing import Dict

from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    name: str = "Beancount Helper"
    version: str = "0.1.0"


class RuleSettings(BaseSettings):
    rules_path: str = "./config/account_rules.yaml"


class AdaptiveSettings(BaseSettings):
    check_interval: int = 3600  # 1 hour

    class Config:
        env_prefix = "ADAPTIVE_"


class ExpenseClassifierSettings(BaseSettings):
    algorithm: str = "random_forest"
    params: dict = {}
    confidence_threshold: float = 0.8
    classifier_path: str = "./data/models/expense_classifier.joblib"
    uncategorized: str = "Expenses:Uncategorized"

    class Config:
        env_prefix = "EXPENSE_"


class ClassifierSettings(BaseSettings):
    rule: RuleSettings = RuleSettings()
    adaptive: AdaptiveSettings = AdaptiveSettings()
    expense: ExpenseClassifierSettings = ExpenseClassifierSettings()

    class Config:
        env_prefix = "CLASSIFIER_"


class DefaultImporterSettings(BaseSettings):
    expense_account: str = "Expenses:Uncategorized"
    income_account: str = "Income:Uncategorized"


class AlipayImporterSettings(BaseSettings):
    account: str = "Assets:Alipay"
    additional_accounts: Dict[str, str] = {}


class BOCImporterSettings(BaseSettings):
    account: str = "Assets:BOC"
    ignore_apps: bool = True


class BOCCreditImporterSettings(BaseSettings):
    account: str = "Liabilities:Credit:BOC"
    asset_account: str = "Assets:Uncategorized"
    ignore_apps: bool = True


class CiticCreditImporterSettings(BaseSettings):
    account: str = "Liabilities:Credit:Citic"
    asset_account: str = "Assets:Uncategorized"
    ignore_apps: bool = True


class CMBImporterSettings(BaseSettings):
    account: str = "Assets:CMB:6066"
    ignore_apps: bool = True


class CMBCreditImporterSettings(BaseSettings):
    account: str = "Liabilities:Credit:CMB"
    asset_account: str = "Assets:Uncategorized"
    ignore_apps: bool = True


class WeChatImporterSettings(BaseSettings):
    account: str = "Liabilities:Assets:WeChat"
    fee_account: str = "Expenses:Fee"
    additional_accounts: Dict[str, str] = {}


class ImporterSettings(BaseSettings):
    default: DefaultImporterSettings = DefaultImporterSettings()
    alipay: AlipayImporterSettings = AlipayImporterSettings()
    boc: BOCImporterSettings = BOCImporterSettings()
    boc_credit: BOCCreditImporterSettings = BOCCreditImporterSettings()
    citic_credit: CiticCreditImporterSettings = CiticCreditImporterSettings()
    cmb: CMBImporterSettings = CMBImporterSettings()
    cmb_credit: CMBCreditImporterSettings = CMBCreditImporterSettings()
    wechat: WeChatImporterSettings = WeChatImporterSettings()


class LedgerSettings(BaseSettings):
    duplicate_meta: str = "__duplicate__"


class Settings(BaseSettings):
    app: AppSettings = AppSettings()  # 使用固定的 AppSettings
    classifier: ClassifierSettings = ClassifierSettings()
    importers: ImporterSettings = ImporterSettings()
    ledger: LedgerSettings = LedgerSettings()

    def dict_for_api(self):
        data = self.model_dump()
        return data

    class Config:
        env_nested_delimiter = "__"


settings = Settings()
