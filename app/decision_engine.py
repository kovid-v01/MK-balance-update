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


# Amounts are in rupees.  Check the lowest threshold first so the message
# always reflects the most severe applicable level.
BALANCE_ALERT_THRESHOLDS = (
    (1_000_000, "10 L", Severity.CRITICAL),
    (3_000_000, "30 L", Severity.HIGH),
    (5_000_000, "50 L", Severity.WARNING),
    (10_000_000, "1 CR", Severity.WARNING),
)
MESSAGE_SUPPRESSION_THRESHOLD = 10_000


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

    # Do not send either scheduled balance updates or threshold alerts once
    # the balance is under Rs. 10,000.
    if balance_value < MESSAGE_SUPPRESSION_THRESHOLD:
        return Decision(
            action=Action.NO_ACTION,
            severity=Severity.CRITICAL,
            reason="Balance is below Rs. 10,000. WhatsApp update suppressed.",
        )

    for threshold, threshold_label, severity in BALANCE_ALERT_THRESHOLDS:
        if balance_value < threshold:
            return Decision(
                action=Action.ALERT,
                severity=severity,
                reason=f"Balance is below the Rs. {threshold_label} threshold.",
                message=f"Balance is below {threshold_label}",
                mention_everyone=True,
            )

    label = app_name or "MK Balance"
    return Decision(
        action=Action.SEND_BALANCE,
        severity=Severity.NORMAL,
        reason="Balance is valid for scheduled update.",
        message=f"{label}: {balance_text}",
    )
