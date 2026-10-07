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
    @patch("main._wait_until_cdp_unavailable", return_value=True)
    @patch("main._pids_listening_on_port", return_value=set())
    def test_stop_owned_browser_closes_running_process(self, _pids, _wait):
        process = MagicMock()
        process.pid = 4321
        process._alive = True
        process.poll.side_effect = lambda: None if process._alive else 1
        process.terminate.side_effect = lambda: setattr(process, "_alive", False)
        process.wait.side_effect = lambda timeout=None: setattr(process, "_alive", False)
        logger = MagicMock()

        main._stop_owned_browser(process, logger)

        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=8)

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

    @patch("main._launch_browser")
    @patch("main._stop_owned_browser")
    @patch("main.cdp_endpoint_is_ready", return_value=True)
    def test_ensure_does_not_open_another_window_when_connected(
        self,
        _ready,
        stop,
        launch,
    ):
        process = MagicMock()

        result = main._ensure_owned_browser(
            "chrome",
            process,
            MagicMock(),
        )

        stop.assert_not_called()
        launch.assert_not_called()
        self.assertIs(result, process)

    @patch("main._launch_browser")
    @patch("main._stop_owned_browser")
    @patch("main.cdp_endpoint_is_ready", return_value=False)
    def test_ensure_closes_disconnected_window_then_launches_one(
        self,
        _ready,
        stop,
        launch,
    ):
        process = MagicMock()
        replacement = MagicMock()
        launch.return_value = replacement

        result = main._ensure_owned_browser(
            "chrome",
            process,
            MagicMock(),
        )

        stop.assert_called_once()
        launch.assert_called_once_with("chrome")
        self.assertIs(result, replacement)

    @patch("main.subprocess.run")
    def test_pids_listening_on_port_parses_netstat(self, run):
        run.return_value = MagicMock(
            stdout=(
                "TCP    127.0.0.1:9222         0.0.0.0:0              LISTENING       5678\n"
            )
        )

        self.assertEqual(main._pids_listening_on_port(9222), {5678})


class BrowserLaunchFocusTests(unittest.TestCase):
    @patch("main.subprocess.Popen")
    @patch("main._validate_browser_config", return_value=True)
    @patch("main._browser_config")
    def test_launch_browser_does_not_activate_window(self, config, _validate, popen):
        config.return_value = {
            "path": r"C:\chrome.exe",
            "user_data_dir": r"C:\profile",
        }
        process = MagicMock()
        popen.return_value = process

        result = main._launch_browser("chrome")

        self.assertIs(result, process)
        startupinfo = popen.call_args.kwargs["startupinfo"]
        self.assertEqual(startupinfo.wShowWindow, main.SW_SHOWNOACTIVATE)


class PortalReplacementTests(unittest.TestCase):
    def test_close_portal_page_closes_only_the_page(self):
        portal_page = MagicMock()

        browser._close_portal_page(portal_page)

        portal_page.close.assert_called_once_with(run_before_unload=False)

    def test_open_page_reuses_a_blank_tab_instead_of_a_new_window(self):
        blank = MagicMock()
        blank.title.return_value = "New Tab"
        blank.url = "about:blank"
        context = MagicMock()
        context.pages = [blank]

        result = browser._open_page(context, "https://portal.example/")

        blank.goto.assert_called_once()
        context.new_page.assert_not_called()
        context.new_cdp_session.assert_not_called()
        self.assertIs(result, blank)

    def test_open_page_opens_a_tab_in_the_existing_window(self):
        existing = MagicMock()
        existing.title.return_value = "WhatsApp"
        existing.url = "https://web.whatsapp.com/"
        new_tab = MagicMock()
        new_tab.url = "https://portal.example/"
        context = MagicMock()
        context.pages = [existing]
        cdp = MagicMock()

        def create_target(method, params):
            context.pages = [existing, new_tab]
            return {"targetId": "1"}

        cdp.send.side_effect = create_target
        context.new_cdp_session.return_value = cdp

        result = browser._open_page(context, "https://portal.example/")

        context.new_cdp_session.assert_called_once_with(existing)
        cdp.send.assert_called_once()
        self.assertEqual(cdp.send.call_args.args[1]["newWindow"], False)
        context.new_page.assert_not_called()
        self.assertIs(result, new_tab)

    def test_close_unusable_pages_closes_disconnected_tabs(self):
        dead = MagicMock()
        dead.title.side_effect = Exception("disconnected")
        live = MagicMock()
        live.title.return_value = "WhatsApp"
        live.url = "https://web.whatsapp.com/"
        context = MagicMock()
        context.pages = [dead, live]
        connected_browser = MagicMock()
        connected_browser.contexts = [context]

        browser.close_unusable_pages(connected_browser)

        dead.close.assert_called_once_with(run_before_unload=False)
        live.close.assert_not_called()


class WhatsAppLocatorTests(unittest.TestCase):
    def test_wait_for_first_visible_uses_the_first_ready_selector(self):
        missing = MagicMock()
        missing.wait_for.side_effect = Exception("not visible")
        found = MagicMock()
        missing_locator = MagicMock()
        missing_locator.first = missing
        found_locator = MagicMock()
        found_locator.first = found
        page = MagicMock()
        page.locator.side_effect = [missing_locator, found_locator]

        result = browser._wait_for_first_visible(
            page,
            ["#old", "#main footer [contenteditable=\"true\"]"],
            2000,
        )

        self.assertIs(result, found)


if __name__ == "__main__":
    unittest.main()
