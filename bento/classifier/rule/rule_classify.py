import re
from dataclasses import dataclass
from typing import Callable, Dict

import yaml


class Predicates:
    """Collection of predicate functions for rule matching."""

    @staticmethod
    def equals(value: str, target: str) -> bool:
        """Exact string match."""
        return value == target

    @staticmethod
    def contains(value: str, target: str) -> bool:
        """Substring match."""
        return target in value

    @staticmethod
    def starts_with(value: str, target: str) -> bool:
        """String starts with prefix."""
        return value.startswith(target)

    @staticmethod
    def ends_with(value: str, target: str) -> bool:
        """String ends with suffix."""
        return value.endswith(target)

    @staticmethod
    def matches(value: str, pattern: str) -> bool:
        """Regular expression match."""
        return bool(re.search(pattern, value))

    @staticmethod
    def get_predicate(name: str) -> Callable[[str, str], bool]:
        """Get predicate function by name."""
        return getattr(Predicates, name)


@dataclass
class AccountRule:
    """Rule for account classification."""

    name: str
    condition: Dict[str, Dict[str, str]]
    prediction_account: str

    def matches(self, payee: str, narration: str) -> bool:
        """Check if transaction matches this rule's conditions."""

        # or
        for field, conditions in self.condition.items():
            value = (
                payee if field == "payee" else narration if field == "narration" else ""
            )
            if not value:
                continue
            # and
            succ = True
            for predicate_name, target in conditions.items():
                predicate_func = Predicates.get_predicate(predicate_name)
                if not predicate_func(value.lower(), target.lower()):  # ignore case
                    succ = False
                    break
            if succ:
                return True
        return False


class RuleAccountClassifier:
    def __init__(self, rule_file: str):
        """Initialize with path to rules yaml file."""
        self.rules = self._load_rules(rule_file)

    def _load_rules(self, rule_file: str) -> list[AccountRule]:
        """Load and parse rules from yaml file."""
        with open(rule_file) as f:
            config = yaml.safe_load(f)

        rules = []
        for rule in config["rules"]:
            rules.append(
                AccountRule(
                    name=rule["name"],
                    condition=rule["condition"],
                    prediction_account=rule["prediction_account"],
                )
            )
        return rules

    def classify(self, payee: str, narration: str) -> tuple[bool, str]:
        """
        Classify a transaction by applying rules.
        Returns the predicted account based on payee and narration.
        """
        for rule in self.rules:
            if rule.matches(payee, narration):
                return True, rule.prediction_account

        return False, None
