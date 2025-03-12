export SINK__LEDGER__DUPLICATE_META := "__duplicate__"
export SINK__CLASSIFIER__RULE__RULES_PATH := "./config/account_rules.yaml"
export SINK__CLASSIFIER__ADAPTIVE__CHECK_INTERVAL := "3600"
export SINK__CLASSIFIER__EXPENSE__ALGORITHM := "random_forest"
export SINK__CLASSIFIER__EXPENSE__CONFIDENCE_THRESHOLD := "0.8"
export SINK__CLASSIFIER__EXPENSE__CLASSIFIER_PATH := "/home/pzany/bean/pzany/ml/model.joblib"
export SINK__CLASSIFIER__EXPENSE__PARAMS := '{"n_estimators": 100, "random_state": 42}'
export SINK__IMPORTERS__ALIPAY__ADDITIONAL_ACCOUNTS := '{"招商银行信用卡(1984)": "Liabilities:Credit:CMB:1984", "中国银行储蓄卡(3871)": "Assets:BOC:3871"}'
export SINK__IMPORTERS__DEFAULT__EXPENSE_ACCOUNT := "Expenses:Uncategorized"
export SINK__IMPORTERS__DEFAULT__INCOME_ACCOUNT := "Income:Uncategorized"
export SINK__IMPORTERS__BOC__ACCOUNT := "Assets:BOC"
export SINK__IMPORTERS__BOC__IGNORE_APPS := "true"
export SINK__IMPORTERS__BOC_CREDIT__ACCOUNT := "Liabilities:Credit:BOC"
export SINK__IMPORTERS__BOC_CREDIT__ASSET_ACCOUNT := "Assets:Uncategorized"
export SINK__IMPORTERS__BOC_CREDIT__IGNORE_APPS := "true"
export SINK__IMPORTERS__CITIC_CREDIT__ACCOUNT := "Liabilities:Credit:CITIC"
export SINK__IMPORTERS__CITIC_CREDIT__ASSET_ACCOUNT := "Assets:Uncategorized"
export SINK__IMPORTERS__CMB__ACCOUNT := "Assets:CMB"
export SINK__IMPORTERS__CMB__IGNORE_APPS := "true"
export SINK__IMPORTERS__CMB_CREDIT__ACCOUNT := "Liabilities:Credit:CMB"
export SINK__IMPORTERS__CMB_CREDIT__ASSET_ACCOUNT := "Assets:Uncategorized"
export SINK__IMPORTERS__WECHAT__ACCOUNT := "Assets:WeChat"
export SINK__IMPORTERS__WECHAT__FEE_ACCOUNT := "Expenses:Fee"
export SINK__IMPORTERS__WECHAT__ADDITIONAL_ACCOUNTS := '{"招商银行储蓄卡(6066)": "Assets:CMB:6066", "中国银行信用卡(8132)": "Liabilities:Credit:BOC:8132", "中信银行信用卡(5093)": "Liabilities:Credit:CITIC:5093"}'

export SOURCE__TYPE := "gmail"
export SOURCE__GMAIL__CLIENT_SECRET_FILE := "/home/pzany/bento/secret/client_secret_671563122573-vebs3c24i76kb90568jjoueqpl9svpsk.apps.googleusercontent.com.json"
export SOURCE__GMAIL__CLIENT_TOKEN_FILE := "/home/pzany/bento/secret/client_token.json"
export SOURCE__GMAIL__SERVICE_ACCOUNT_FILE := "/home/pzany/bento/secret/bento-453210-7ea6d16a9c93.json"
export SOURCE__GMAIL__HISTORY_ID := ""
export SOURCE__GMAIL__LABEL := "Bento"
export SOURCE__GMAIL__PROJECT_ID := "bento-453210"
export SOURCE__GMAIL__SUBSCRIPTION_ID := "statement-sub"
export SOURCE__GMAIL__TOPIC_NAME := "statement"

default:
    @just --list

image:
    nix build .#image

run:
    @echo "Running bento..."
    uv run bento

up:
    nix flake update
