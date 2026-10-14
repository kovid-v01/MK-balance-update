import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from browser import (  # noqa: E402
    _is_limit_request_text,
    _select_latest_limit_request,
)

GROUP_NAME = "Mewar 🤝Vananam MK LIMIT"


class LimitRequestTextTests(unittest.TestCase):
    def test_mk_or_limit_is_a_request(self):
        self.assertTrue(_is_limit_request_text("LIMIT", GROUP_NAME))
        self.assertTrue(_is_limit_request_text("please check Limit", GROUP_NAME))
        self.assertTrue(_is_limit_request_text("MK", GROUP_NAME))
        self.assertTrue(_is_limit_request_text("need mk", GROUP_NAME))

    def test_group_title_is_not_a_request(self):
        self.assertFalse(_is_limit_request_text(GROUP_NAME, GROUP_NAME))

    def test_our_balance_post_is_not_a_request(self):
        self.assertFalse(
            _is_limit_request_text("MK Balance: ₹ 11,113,184.15", GROUP_NAME)
        )


class SelectLatestLimitRequestTests(unittest.TestCase):
    def test_seeds_without_trigger(self):
        messages = [
            {"id": "false_old", "outgoing": False, "text": "please LIMIT"},
            {"id": "true_ours", "outgoing": True, "text": "LIMIT"},
        ]

        triggered, latest_id = _select_latest_limit_request(
            messages,
            None,
            GROUP_NAME,
        )

        self.assertFalse(triggered)
        self.assertEqual(latest_id, "true_ours")

    def test_outgoing_mk_from_same_session_triggers(self):
        messages = [
            {"id": "false_old", "outgoing": False, "text": "LIMIT"},
            {"id": "true_user", "outgoing": True, "text": "MK"},
        ]

        triggered, latest_id = _select_latest_limit_request(
            messages,
            "false_old",
            GROUP_NAME,
        )

        self.assertTrue(triggered)
        self.assertEqual(latest_id, "true_user")

    def test_outgoing_limit_from_same_session_triggers(self):
        messages = [
            {"id": "false_old", "outgoing": False, "text": "LIMIT"},
            {"id": "true_user", "outgoing": True, "text": "LIMIT"},
        ]

        triggered, latest_id = _select_latest_limit_request(
            messages,
            "false_old",
            GROUP_NAME,
        )

        self.assertTrue(triggered)
        self.assertEqual(latest_id, "true_user")

    def test_group_title_bubble_does_not_hide_real_limit(self):
        messages = [
            {"id": "header", "outgoing": False, "text": GROUP_NAME},
            {"id": "real", "outgoing": False, "text": "LIMIT"},
        ]

        triggered, latest_id = _select_latest_limit_request(
            messages,
            "header",
            GROUP_NAME,
        )

        self.assertTrue(triggered)
        self.assertEqual(latest_id, "real")

    def test_same_limit_is_not_answered_twice(self):
        messages = [
            {"id": "false_new", "outgoing": False, "text": "check LIMIT"},
        ]

        triggered, latest_id = _select_latest_limit_request(
            messages,
            "false_new",
            GROUP_NAME,
        )

        self.assertFalse(triggered)
        self.assertEqual(latest_id, "false_new")


if __name__ == "__main__":
    unittest.main()
