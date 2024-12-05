export LEDGER__DUPLICATE_META := "__duplicate__"
export CLASSIFIER__RULE__RULES_PATH := "./config/account_rules.yaml"
export CLASSIFIER__ADAPTIVE__CHECK_INTERVAL := "3600"
export CLASSIFIER__EXPENSE__ALGORITHM := "random_forest"
export CLASSIFIER__EXPENSE__CONFIDENCE_THRESHOLD := "0.8"
export CLASSIFIER__EXPENSE__CLASSIFIER_PATH := "/home/pzany/bean/pzany/ml/model.joblib"
export CLASSIFIER__EXPENSE__PARAMS := '{"n_estimators": 100, "random_state": 42}'
export IMPORTERS__ALIPAY__ADDITIONAL_ACCOUNTS := '{"招商银行信用卡(1984)": "Liabilities:Credit:CMB:1984", "中国银行储蓄卡(3871)": "Assets:BOC:3871"}'
export IMPORTERS__DEFAULT__EXPENSE_ACCOUNT := "Expenses:Uncategorized"
export IMPORTERS__DEFAULT__INCOME_ACCOUNT := "Income:Uncategorized"
export IMPORTERS__BOC__ACCOUNT := "Assets:BOC"
export IMPORTERS__BOC__IGNORE_APPS := "true"
export IMPORTERS__BOC_CREDIT__ACCOUNT := "Liabilities:Credit:BOC"
export IMPORTERS__BOC_CREDIT__ASSET_ACCOUNT := "Assets:Uncategorized"
export IMPORTERS__BOC_CREDIT__IGNORE_APPS := "true"
export IMPORTERS__CITIC_CREDIT__ACCOUNT := "Liabilities:Credit:CITIC"
export IMPORTERS__CITIC_CREDIT__ASSET_ACCOUNT := "Assets:Uncategorized"
export IMPORTERS__CMB__ACCOUNT := "Assets:CMB"
export IMPORTERS__CMB__IGNORE_APPS := "true"
export IMPORTERS__CMB_CREDIT__ACCOUNT := "Liabilities:Credit:CMB"
export IMPORTERS__CMB_CREDIT__ASSET_ACCOUNT := "Assets:Uncategorized"
export IMPORTERS__WECHAT__ACCOUNT := "Assets:WeChat"
export IMPORTERS__WECHAT__FEE_ACCOUNT := "Expenses:Fee"
export IMPORTERS__WECHAT__ADDITIONAL_ACCOUNTS := '{"招商银行储蓄卡(6066)": "Assets:CMB:6066", "中国银行信用卡(8132)": "Liabilities:Credit:BOC:8132", "中信银行信用卡(5093)": "Liabilities:Credit:CITIC:5093"}'

default:
    @just --list

image:
    nix build .#image

run:
    @echo "Running fava..."
    poetry run fava ./ledger.bean
