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


# Amounts are in rupees.
#
# The thresholds are checked from the lowest threshold
# to the highest threshold so that the most severe
# applicable alert level is selected.
#
# Example:
#   ₹9 L   -> below ₹10 L
#   ₹25 L  -> below ₹30 L
#   ₹45 L  -> below ₹50 L
#   ₹80 L  -> below ₹1 CR
#   ₹1.2 CR -> normal
BALANCE_ALERT_THRESHOLDS = (
    (1_000_000, "10 L", Severity.CRITICAL),
    (3_000_000, "30 L", Severity.HIGH),
    (5_000_000, "50 L", Severity.WARNING),
    (10_000_000, "1 CR", Severity.WARNING),
)


# Do not send any WhatsApp balance update or alert
# when the balance is below this amount.
#
# NOTE:
# This is currently ₹100 because that is what your
# existing implementation used.
MESSAGE_SUPPRESSION_THRESHOLD = 100


def get_alert_threshold(balance_value):
    """
    Determine which alert threshold applies to the balance.

    Returns:
        tuple: (threshold_value, threshold_label, severity)
        None: if no alert threshold applies.
    """

    if balance_value is None:
        return None

    # Never generate an alert for zero or negative balance.
    # The main application should also suppress WhatsApp
    # messages completely in this situation.
    if balance_value <= 0:
        return None

    # Suppress all messages below the configured
    # minimum message threshold.
    if balance_value < MESSAGE_SUPPRESSION_THRESHOLD:
        return None

    # Find the first threshold that the balance is below.
    for threshold, threshold_label, severity in BALANCE_ALERT_THRESHOLDS:
        if balance_value < threshold:
            return threshold, threshold_label, severity

    # Balance is above every configured alert threshold.
    return None


def evaluate_balance(
    balance_value,
    balance_text,
    app_name=None,
    should_alert=False,
    alert_threshold=None,
):
    """
    Apply deterministic business rules to the retrieved balance.

    These rules take precedence over any future LLM recommendation.

    Parameters:
        balance_value:
            Parsed numeric balance.

        balance_text:
            Original balance text displayed by the portal.

        app_name:
            Application name used in normal balance messages.

        should_alert:
            Whether the alert-memory logic has determined that
            an alert should be sent for the current threshold.

        alert_threshold:
            Threshold returned by get_alert_threshold().

    Returns:
        Decision object.
    """

    # ---------------------------------------------------------
    # 1. Balance could not be parsed
    # ---------------------------------------------------------

    if balance_value is None:
        return Decision(
            action=Action.NO_ACTION,
            severity=Severity.NORMAL,
            reason="Balance could not be parsed.",
        )

    # ---------------------------------------------------------
    # 2. Zero or negative balance
    # ---------------------------------------------------------
    #
    # This is a hard business rule.
    #
    # No balance message.
    # No alert.
    # No @all.
    #
    # Alert memory should also not cause an alert here.
    # ---------------------------------------------------------

    if balance_value <= 0:
        return Decision(
            action=Action.NO_ACTION,
            severity=Severity.NORMAL,
            reason="Balance is zero or negative. WhatsApp update suppressed.",
        )

    # ---------------------------------------------------------
    # 3. Balance below message suppression threshold
    # ---------------------------------------------------------

    if balance_value < MESSAGE_SUPPRESSION_THRESHOLD:
        return Decision(
            action=Action.NO_ACTION,
            severity=Severity.CRITICAL,
            reason=(
                f"Balance is below Rs. "
                f"{MESSAGE_SUPPRESSION_THRESHOLD:,}. "
                "WhatsApp update suppressed."
            ),
        )

    # ---------------------------------------------------------
    # 4. Alert required
    # ---------------------------------------------------------
    #
    # Alert memory is handled outside this decision engine.
    #
    # If should_alert=True, we generate an ALERT decision.
    # main.py will:
    #
    #   1. Send the balance
    #   2. Send the alert with @all
    #   3. Save the threshold in alert memory
    #
    # If should_alert=False, the normal balance message
    # will be returned instead.
    # ---------------------------------------------------------

    if should_alert and alert_threshold is not None:

        threshold, threshold_label, severity = alert_threshold

        return Decision(
            action=Action.ALERT,
            severity=severity,
            reason=(
                f"Balance is below the Rs. "
                f"{threshold_label} threshold."
            ),
            message=f"Balance is below {threshold_label}",
            mention_everyone=True,
        )

    # ---------------------------------------------------------
    # 5. Normal balance update
    # ---------------------------------------------------------
    #
    # This is returned when:
    #
    #   - balance is valid
    #   - balance is positive
    #   - balance is above suppression threshold
    #   - no new alert needs to be generated
    #
    # The normal balance message can therefore be sent
    # every scheduled cycle.
    # ---------------------------------------------------------

    label = app_name or "MK Balance"

    return Decision(
        action=Action.SEND_BALANCE,
        severity=Severity.NORMAL,
        reason="Balance is valid for scheduled update.",
        message=f"{label}: {balance_text}",
        mention_everyone=False,
    )