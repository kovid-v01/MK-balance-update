from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(str, Enum):
    SEND_BALANCE = "SEND_BALANCE"
    ALERT = "ALERT"
    NO_ACTION = "NO_ACTION"


class Severity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Decision:
    action: Action
    severity: Severity
    reason: str
    message: Optional[str] = None
    mention_everyone: bool = False


LOW_BALANCE_THRESHOLD = 5_000_000


def evaluate_balance(balance_value, balance_text, app_name=None):
    """
    Apply deterministic business rules to the retrieved balance.

    These rules take precedence over any future LLM recommendation.
    """

    # Unable to parse the balance safely.
    if balance_value is None:
        return Decision(
            action=Action.NO_ACTION,
            severity=Severity.NORMAL,
            reason="Balance could not be parsed.",
        )

    # Critical business rule:
    # Never send a balance or alert when balance is negative.
    if balance_value < 0:
        return Decision(
            action=Action.NO_ACTION,
            severity=Severity.NORMAL,
            reason="Negative balance detected. WhatsApp update suppressed.",
        )

    label = app_name or "MK Balance"

    if balance_value < LOW_BALANCE_THRESHOLD:
        return Decision(
            action=Action.ALERT,
            severity=Severity.HIGH,
            reason=(
                "Balance is below the low-balance threshold of "
                f"{LOW_BALANCE_THRESHOLD:,.0f}."
            ),
            message=f"Low balance alert: {label} is {balance_text}.",
            mention_everyone=True,
        )

    return Decision(
        action=Action.SEND_BALANCE,
        severity=Severity.NORMAL,
        reason="Balance is valid for scheduled update.",
        message=f"{label}: {balance_text}",
    )
