import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

import browser  # noqa: E402
import main  # noqa: E402


class CdpEndpointTests(unittest.TestCase):
    @patch("browser.cdp_endpoint_is_ready", side_effect=[False, False, True])
    @patch("browser.time.sleep")
    def test_wait_for_cdp_endpoint_retries_until_ready(self, sleep, ready):
        self.assertTrue(
            browser.wait_for_cdp_endpoint(
                "9222",
                timeout_seconds=10,
                poll_seconds=1,
            )
        )
        self.assertEqual(ready.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("browser.cdp_endpoint_is_ready", return_value=False)
    @patch("browser.time.sleep")
    @patch("browser.time.monotonic", side_effect=[0, 0, 2])
    def test_wait_for_cdp_endpoint_reports_timeout(self, monotonic, sleep, ready):
        self.assertFalse(
            browser.wait_for_cdp_endpoint(
                "9222",
                timeout_seconds=1,
                poll_seconds=1,
            )
        )
        ready.assert_called_once_with("9222")


class OwnedBrowserRecoveryTests(unittest.TestCase):
    def test_stop_owned_browser_terminates_running_process(self):
        process = MagicMock()
        process.poll.return_value = None
        logger = MagicMock()

        main._stop_owned_browser(process, logger)

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=15)

    @patch("main._launch_browser")
    @patch("main._stop_owned_browser")
    def test_restart_owned_browser_stops_then_starts(self, stop, launch):
        process = MagicMock()
        replacement = MagicMock()
        launch.return_value = replacement

        result = main._restart_owned_browser(
            "chrome",
            process,
            MagicMock(),
        )

        stop.assert_called_once()
        launch.assert_called_once_with("chrome")
        self.assertIs(result, replacement)


class PortalReplacementTests(unittest.TestCase):
    def test_close_portal_page_closes_only_the_page(self):
        portal_page = MagicMock()

        browser._close_portal_page(portal_page)

        portal_page.close.assert_called_once_with(run_before_unload=False)


if __name__ == "__main__":
    unittest.main()
