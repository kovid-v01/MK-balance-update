import json
import logging
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

import browser  # noqa: E402
import main  # noqa: E402


TEST_DEBUG_PORT = "9333"
logger = logging.getLogger("owned_browser_lifecycle")


def _chrome_is_installed():
    return Path(main.DEFAULT_CHROME_PATH).exists()


def _fetch_cdp_targets(port):
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
        return json.load(response)


def _page_target_count(port):
    return sum(
        1
        for target in _fetch_cdp_targets(port)
        if target.get("type") == "page"
    )


def _wait_for_stable_page_count(port, attempts=6):
    previous = None
    for _ in range(attempts):
        current = _page_target_count(port)
        if previous is not None and current == previous:
            return current
        previous = current
        time.sleep(1)
    return previous


@unittest.skipUnless(_chrome_is_installed(), "Chrome is not installed")
class LiveOwnedBrowserWindowTests(unittest.TestCase):
    def setUp(self):
        if main._pids_listening_on_port(TEST_DEBUG_PORT):
            self.skipTest(f"Port {TEST_DEBUG_PORT} is already in use")

        self.profile_dir = tempfile.TemporaryDirectory(prefix="mk-balance-chrome-test-")
        self._old_env = {
            "REMOTE_DEBUGGING_PORT": os.environ.get("REMOTE_DEBUGGING_PORT"),
            "CHROME_BROWSER_PATH": os.environ.get("CHROME_BROWSER_PATH"),
            "CHROME_USER_DATA_DIR": os.environ.get("CHROME_USER_DATA_DIR"),
        }
        os.environ["REMOTE_DEBUGGING_PORT"] = TEST_DEBUG_PORT
        os.environ["CHROME_BROWSER_PATH"] = main.DEFAULT_CHROME_PATH
        os.environ["CHROME_USER_DATA_DIR"] = self.profile_dir.name
        self.browser_process = None

    def tearDown(self):
        try:
            if self.browser_process is not None:
                main._stop_owned_browser(
                    self.browser_process,
                    logger,
                    port=TEST_DEBUG_PORT,
                )
        finally:
            for key, value in self._old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self.profile_dir.cleanup()

    def test_lost_connection_closes_window_then_opens_one_replacement(self):
        self.browser_process = main._ensure_owned_browser(
            "chrome",
            None,
            logger,
        )
        self.assertIsNotNone(self.browser_process)
        self.assertTrue(
            browser.wait_for_cdp_endpoint(TEST_DEBUG_PORT, timeout_seconds=30)
        )

        first_pids = main._pids_listening_on_port(TEST_DEBUG_PORT)
        self.assertEqual(len(first_pids), 1)
        first_pages = _wait_for_stable_page_count(TEST_DEBUG_PORT)
        self.assertGreaterEqual(first_pages, 1)

        same_process = main._ensure_owned_browser(
            "chrome",
            self.browser_process,
            logger,
        )
        self.assertIs(same_process, self.browser_process)
        self.assertEqual(
            main._pids_listening_on_port(TEST_DEBUG_PORT),
            first_pids,
        )
        self.assertEqual(_page_target_count(TEST_DEBUG_PORT), first_pages)

        main._stop_owned_browser(
            self.browser_process,
            logger,
            port=TEST_DEBUG_PORT,
        )
        self.assertFalse(browser.cdp_endpoint_is_ready(TEST_DEBUG_PORT))
        self.assertEqual(main._pids_listening_on_port(TEST_DEBUG_PORT), set())

        self.browser_process = main._ensure_owned_browser(
            "chrome",
            self.browser_process,
            logger,
        )
        self.assertTrue(
            browser.wait_for_cdp_endpoint(TEST_DEBUG_PORT, timeout_seconds=30)
        )
        self.assertEqual(len(main._pids_listening_on_port(TEST_DEBUG_PORT)), 1)


if __name__ == "__main__":
    unittest.main()
