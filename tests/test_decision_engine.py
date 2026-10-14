import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from decision_engine import (  # noqa: E402
    Action,
    Severity,
    evaluate_balance,
    get_alert_threshold,
)


class EvaluateBalanceTests(unittest.TestCase):
    def test_below_2000_suppresses_limit_and_alert(self):
        decision = evaluate_balance(
            balance_value=1999.99,
            balance_text="₹ 1,999.99",
            app_name="MK Balance",
            should_alert=True,
            alert_threshold=(5_000_000, "50 L", Severity.WARNING),
            limit_requested=True,
        )

        self.assertEqual(decision.action, Action.NO_ACTION)
        self.assertIsNone(get_alert_threshold(1999.99))

    def test_limit_request_sends_balance(self):
        decision = evaluate_balance(
            balance_value=8_000_000,
            balance_text="₹ 80,00,000",
            app_name="MK Balance",
            should_alert=False,
            alert_threshold=None,
            limit_requested=True,
        )

        self.assertEqual(decision.action, Action.SEND_BALANCE)
        self.assertFalse(decision.mention_everyone)
        self.assertNotIn("LIMIT", decision.message)

    def test_new_50l_drop_alerts(self):
        alert_threshold = get_alert_threshold(4_900_000)
        self.assertEqual(alert_threshold[1], "50 L")

        decision = evaluate_balance(
            balance_value=4_900_000,
            balance_text="₹ 49,00,000",
            app_name="MK Balance",
            should_alert=True,
            alert_threshold=alert_threshold,
            limit_requested=False,
        )

        self.assertEqual(decision.action, Action.ALERT)
        self.assertTrue(decision.mention_everyone)
        self.assertEqual(decision.message, "Balance is below 50 L")

    def test_already_alerted_50l_without_limit_is_no_action(self):
        alert_threshold = get_alert_threshold(4_900_000)
        decision = evaluate_balance(
            balance_value=4_900_000,
            balance_text="₹ 49,00,000",
            app_name="MK Balance",
            should_alert=False,
            alert_threshold=alert_threshold,
            limit_requested=False,
        )

        self.assertEqual(decision.action, Action.NO_ACTION)

    def test_one_crore_no_longer_alerts(self):
        self.assertIsNone(get_alert_threshold(9_999_999))
        self.assertIsNone(get_alert_threshold(10_000_000))

        decision = evaluate_balance(
            balance_value=9_500_000,
            balance_text="₹ 95,00,000",
            app_name="MK Balance",
            should_alert=False,
            alert_threshold=get_alert_threshold(9_500_000),
            limit_requested=False,
        )

        self.assertEqual(decision.action, Action.NO_ACTION)


if __name__ == "__main__":
    unittest.main()
