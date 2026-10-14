import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from browser import _select_latest_incoming_limit  # noqa: E402


class SelectLatestIncomingLimitTests(unittest.TestCase):
    def test_ignores_outgoing_and_seeds_without_trigger(self):
        messages = [
            {"id": "false_old", "outgoing": False, "text": "please LIMIT"},
            {"id": "true_ours", "outgoing": True, "text": "LIMIT reminder"},
            {"id": "false_new", "outgoing": False, "text": "Need Limit now"},
        ]

        triggered, latest_id = _select_latest_incoming_limit(messages, None)

        self.assertFalse(triggered)
        self.assertEqual(latest_id, "false_new")

    def test_new_incoming_limit_triggers_once(self):
        messages = [
            {"id": "false_old", "outgoing": False, "text": "LIMIT"},
            {"id": "false_new", "outgoing": False, "text": "check LIMIT"},
        ]

        triggered, latest_id = _select_latest_incoming_limit(
            messages,
            "false_old",
        )

        self.assertTrue(triggered)
        self.assertEqual(latest_id, "false_new")

        triggered_again, same_id = _select_latest_incoming_limit(
            messages,
            latest_id,
        )

        self.assertFalse(triggered_again)
        self.assertEqual(same_id, "false_new")


if __name__ == "__main__":
    unittest.main()
