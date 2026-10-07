import re
import subprocess
import sys
import time
import logging
import os
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright

from dotenv import load_dotenv


from browser import (
    cdp_endpoint_is_ready,
    ensure_whatsapp_tab_open,
    get_portal_balance,
    open_browser_session,
    send_whatsapp_message,
    send_whatsapp_current_chat_message,
    wait_for_cdp_endpoint,
)

from decision_engine import (
    Action,
    evaluate_balance,
    get_alert_threshold,
    BALANCE_ALERT_THRESHOLDS,
)

from alert_memory import (
    load_alert_state,
    save_alert_state,
    is_threshold_alerted,
    mark_threshold_alerted,
    clear_threshold_alert,
)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# LOGGING
# ============================================================

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"


# ============================================================
# DEFAULT CONFIGURATION
# ============================================================

DEFAULT_GROUP_NAME = "Mewar 🤝Vananam MK LIMIT"

DEFAULT_CHECK_INTERVAL_SECONDS = 300

DEFAULT_REMOTE_DEBUGGING_PORT = 9222
CDP_STARTUP_TIMEOUT_SECONDS = 30
MAX_CONSECUTIVE_BROWSER_FAILURES = 2


DEFAULT_CHROME_PATH = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe"
)


DEFAULT_BRAVE_PATH = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
)


DEFAULT_CHROME_PROFILE_DIR = r"C:\chrome-debug-profile"

DEFAULT_BRAVE_PROFILE_DIR = r"C:\brave-debug-profile"

# SW_SHOWNOACTIVATE: show the window without making it the foreground window.
SW_SHOWNOACTIVATE = 4


SUPPORTED_BROWSER_NAMES = {
    "existing",
    "chrome",
    "brave",
}


# ============================================================
# BALANCE PARSING
# ============================================================

def _parse_balance_value(balance_text):
    """
    Convert the balance text returned by the portal
    into a numeric value.

    Examples:

        ₹ 14,007,164.42
        -> 14007164.42

        ₹ -500
        -> -500

        -₹ 500
        -> -500
    """

    if balance_text is None:
        return None

    match = re.search(
        r"-?\d+(?:,\d{3})*(?:\.\d+)?",
        str(balance_text),
    )

    if not match:
        return None

    return float(
        match.group(0).replace(",", "")
    )


# ============================================================
# SCHEDULING
# ============================================================

def _next_run_at(now, interval_seconds):
    """
    Calculate the next wall-clock interval boundary.

    Example with 5-minute interval:

        10:01 → 10:05
        10:05 → 10:10
        10:09 → 10:10
    """

    interval = max(
        1,
        int(interval_seconds),
    )

    timestamp = now.timestamp()

    next_timestamp = (
        (timestamp // interval) + 1
    ) * interval

    return datetime.fromtimestamp(
        next_timestamp,
        tz=now.tzinfo,
    )


def _sleep_until_next_run(
    interval_seconds,
    logger,
):
    """
    Sleep until the next scheduled wall-clock boundary.
    """

    now = datetime.now()

    next_run = _next_run_at(
        now,
        interval_seconds,
    )

    sleep_seconds = max(
        0,
        (next_run - now).total_seconds(),
    )

    logger.info(
        "Next run scheduled for %s "
        "(sleeping %.1f seconds)",
        next_run.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        sleep_seconds,
    )

    time.sleep(
        sleep_seconds
    )


# ============================================================
# BROWSER CONFIGURATION
# ============================================================

def _browser_config(browser_name):
    """
    Return configuration for Chrome or Brave.

    Existing browser mode returns None because
    the application will connect to the already-running
    browser session.
    """

    browser_name = (
        browser_name or "existing"
    ).lower()

    if browser_name == "chrome":
        return {
            "path": os.getenv(
                "CHROME_BROWSER_PATH",
                DEFAULT_CHROME_PATH,
            ),
            "user_data_dir": os.getenv(
                "CHROME_USER_DATA_DIR",
                DEFAULT_CHROME_PROFILE_DIR,
            ),
        }

    if browser_name == "brave":
        return {
            "path": os.getenv(
                "BRAVE_BROWSER_PATH",
                DEFAULT_BRAVE_PATH,
            ),
            "user_data_dir": os.getenv(
                "BRAVE_USER_DATA_DIR",
                DEFAULT_BRAVE_PROFILE_DIR,
            ),
        }

    return None


def _validate_browser_config(
    browser_name,
    config,
):
    """
    Validate the browser executable and profile directory.
    """

    if config is None:
        return True

    browser_path = Path(
        config["path"]
    )

    user_data_dir = Path(
        config["user_data_dir"]
    )

    logger = logging.getLogger(
        __name__
    )

    if not browser_path.exists():
        logger.error(
            "%s browser executable not found: %s",
            browser_name,
            browser_path,
        )

        return False

    user_data_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return True


def _configured_debug_port():
    return os.getenv(
        "REMOTE_DEBUGGING_PORT",
        str(DEFAULT_REMOTE_DEBUGGING_PORT),
    )


def _pids_listening_on_port(port):
    """Return PIDs that are still listening on the Chrome DevTools port."""
    port = str(port)
    pids = set()

    if os.name != "nt":
        return pids

    completed = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
    )
    pattern = re.compile(
        rf":{re.escape(port)}\s+\S+\s+LISTENING\s+(\d+)",
        re.IGNORECASE,
    )

    for line in completed.stdout.splitlines():
        match = pattern.search(line)
        if not match:
            continue

        pid = int(match.group(1))
        if pid > 0:
            pids.add(pid)

    return pids


def _kill_process_tree(pid, logger):
    """Kill a Chrome process and every child it spawned."""
    logger.warning("Closing disconnected browser process tree (PID %s)", pid)

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    try:
        os.kill(pid, 15)
    except OSError:
        pass


def _wait_until_cdp_unavailable(port, timeout_seconds=20):
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if not cdp_endpoint_is_ready(port):
            return True
        time.sleep(0.5)

    return not cdp_endpoint_is_ready(port)


def _launch_browser(browser_name):
    """
    Launch Chrome or Brave with remote debugging enabled.

    Existing browser mode returns None.
    """

    config = _browser_config(
        browser_name
    )

    if config is None:
        return None

    if not _validate_browser_config(
        browser_name,
        config,
    ):
        return None

    browser_path = config["path"]

    user_data_dir = config["user_data_dir"]

    port = os.getenv(
        "REMOTE_DEBUGGING_PORT",
        str(
            DEFAULT_REMOTE_DEBUGGING_PORT
        ),
    )

    logger = logging.getLogger(
        __name__
    )

    logger.info(
        "Launching %s browser: %s",
        browser_name,
        browser_path,
    )

    logger.info(
        "Using browser profile: %s",
        user_data_dir,
    )

    launch_kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = SW_SHOWNOACTIVATE
        launch_kwargs["startupinfo"] = startupinfo

    return subprocess.Popen(
        [
            browser_path,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={user_data_dir}",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
        ],
        **launch_kwargs,
    )


def _stop_owned_browser(browser_process, logger, port=None):
    """Close disconnected Chrome windows before a replacement is launched."""
    port = port or _configured_debug_port()
    pids = set()

    if browser_process is not None and browser_process.poll() is None:
        pids.add(browser_process.pid)

    pids.update(_pids_listening_on_port(port))

    if not pids:
        logger.info("No disconnected browser window is still running")
        return

    logger.warning(
        "Closing disconnected browser window(s) before opening a replacement"
    )

    if browser_process is not None and browser_process.poll() is None:
        browser_process.terminate()
        try:
            browser_process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            logger.warning("Browser did not exit gracefully; closing it forcefully")

    for pid in sorted(pids):
        if browser_process is not None and pid == browser_process.pid:
            if browser_process.poll() is not None:
                continue
        _kill_process_tree(pid, logger)

    leftover_pids = _pids_listening_on_port(port)
    for pid in leftover_pids:
        _kill_process_tree(pid, logger)

    if not _wait_until_cdp_unavailable(port):
        logger.warning(
            "DevTools port %s is still busy after closing the disconnected window",
            port,
        )


def _ensure_owned_browser(browser_name, browser_process, logger):
    """Keep a single owned browser window. Never launch a second copy."""
    if browser_name == "existing":
        return browser_process

    port = _configured_debug_port()

    if cdp_endpoint_is_ready(port):
        logger.info(
            "Browser connection is available; not opening another window"
        )
        return browser_process

    logger.warning(
        "Browser connection is not available. "
        "Closing the disconnected window, then opening one replacement."
    )
    _stop_owned_browser(browser_process, logger, port=port)
    return _launch_browser(browser_name)


def _restart_owned_browser(browser_name, browser_process, logger):
    """Restart the dedicated browser after a lost connection."""
    logger.warning("Restarting app-owned %s browser for automatic recovery", browser_name)
    _stop_owned_browser(browser_process, logger)
    return _launch_browser(browser_name)


# ============================================================
# LOGGING CONFIGURATION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_FILE,
            encoding="utf-8",
        ),
    ],
)


# ============================================================
# ALERT MEMORY HELPERS
# ============================================================

def _clear_recovered_alerts(
    alert_state,
    balance_value,
    logger,
):
    """
    Clear alert thresholds that the balance has recovered above.

    Example:

        Memory:
            [5,000,000]

        Current balance:
            ₹6,000,000

        Result:
            5,000,000 is removed from memory.

    This allows a future drop below ₹50 L
    to trigger a new alert.
    """

    if balance_value is None:
        return

    changed = False

    for threshold, threshold_label, severity in (
        BALANCE_ALERT_THRESHOLDS
    ):
        # If the balance has recovered to or above
        # the threshold, the previous alert can be
        # cleared from memory.

        if balance_value >= threshold:

            if is_threshold_alerted(
                alert_state,
                threshold,
            ):
                clear_threshold_alert(
                    alert_state,
                    threshold,
                )

                logger.info(
                    "Balance recovered above "
                    "%s threshold. "
                    "Alert memory cleared.",
                    threshold_label,
                )

                changed = True

    if changed:
        save_alert_state(
            alert_state
        )


# ============================================================
# MAIN APPLICATION
# ============================================================

_INSTANCE_LOCK_FILE = None


def _acquire_instance_lock(logger):
    """Prevent Task Scheduler from starting a second copy of this script."""
    global _INSTANCE_LOCK_FILE

    lock_path = Path("logs") / "automation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(lock_path, "a+")

    try:
        if lock_file.tell() == 0:
            lock_file.write("0")
            lock_file.flush()
        lock_file.seek(0)

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        logger.error(
            "Another MK Balance automation process is already running. "
            "Stop the extra copy in Task Scheduler or Task Manager, "
            "then start only one."
        )
        return False

    lock_file.write(str(os.getpid()))
    lock_file.flush()
    _INSTANCE_LOCK_FILE = lock_file
    logger.info("Single-instance lock acquired")
    return True


def main():

    logger = logging.getLogger(__name__)

    if not _acquire_instance_lock(logger):
        sys.exit(1)

    # --------------------------------------------------------
    # Browser mode
    # --------------------------------------------------------

    browser_name = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "chrome"
    )

    browser_name = browser_name.lower()

    if browser_name not in SUPPORTED_BROWSER_NAMES:

        logger.error(
            "Unsupported browser mode: %s. "
            "Use existing, chrome, or brave.",
            browser_name,
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Application configuration
    # --------------------------------------------------------

    app_name = os.getenv("APP_NAME")

    group_name = os.getenv(
        "WHATSAPP_GROUP_NAME",
        DEFAULT_GROUP_NAME,
    )

    check_interval_seconds = int(
        os.getenv(
            "CHECK_INTERVAL_SECONDS",
            str(DEFAULT_CHECK_INTERVAL_SECONDS),
        )
    )

    # --------------------------------------------------------
    # Load alert memory
    # --------------------------------------------------------

    alert_state = load_alert_state()

    logger.info(
        "Alert memory initialized: %s",
        alert_state,
    )

    # --------------------------------------------------------
    # Log configuration
    # --------------------------------------------------------

    logger.info(
        "Application: %s",
        app_name,
    )

    logger.info(
        "Browser mode: %s",
        browser_name,
    )

    logger.info(
        "WhatsApp group: %s",
        group_name,
    )

    logger.info(
        "Schedule interval: %s seconds",
        check_interval_seconds,
    )

    # --------------------------------------------------------
    # Browser monitoring / reconnect loop
    # --------------------------------------------------------

    debug_port = _configured_debug_port()
    browser_process = None
    consecutive_browser_failures = 0

    while True:

        try:

            if browser_name != "existing":
                browser_process = _ensure_owned_browser(
                    browser_name,
                    browser_process,
                    logger,
                )

            if not wait_for_cdp_endpoint(
                debug_port,
                timeout_seconds=CDP_STARTUP_TIMEOUT_SECONDS,
            ):
                if browser_name != "existing":
                    logger.warning(
                        "DevTools connection did not recover. "
                        "Closing leftover windows and opening one replacement."
                    )
                    browser_process = _restart_owned_browser(
                        browser_name,
                        browser_process,
                        logger,
                    )
                    if not wait_for_cdp_endpoint(
                        debug_port,
                        timeout_seconds=CDP_STARTUP_TIMEOUT_SECONDS,
                    ):
                        raise RuntimeError(
                            "Chrome DevTools endpoint is unavailable"
                        )
                else:
                    raise RuntimeError(
                        "Chrome DevTools endpoint is unavailable"
                    )

            # ------------------------------------------------
            # Connect to browser
            # ------------------------------------------------

            logger.info(
                "Connecting to browser session"
            )

            with open_browser_session() as browser:

                logger.info(
                    "Browser session connected"
                )
                consecutive_browser_failures = 0
                session_needs_recovery = False

                # ------------------------------------------------
                # Pre-open WhatsApp
                # ------------------------------------------------

                try:

                    ensure_whatsapp_tab_open(
                        browser
                    )

                except Exception:

                    logger.exception(
                        "WhatsApp pre-open check failed"
                    )

                # =================================================
                # MAIN MONITORING LOOP
                # =================================================

                while True:

                    logger.info(
                        "Starting portal check"
                    )

                    # =================================================
                    # 1. GET BALANCE
                    # =================================================

                    try:

                        balance = get_portal_balance(
                            browser
                        )

                    except Exception:

                        logger.exception(
                            "Portal balance retrieval failed"
                        )

                        logger.warning(
                            "Browser session may be unavailable. "
                            "Closing current session and reconnecting."
                        )

                        session_needs_recovery = True
                        break

                    if (
                        balance is None
                        or str(balance).strip() == ""
                    ):

                        logger.error(
                            "Unable to retrieve balance"
                        )

                        _sleep_until_next_run(
                            check_interval_seconds,
                            logger,
                        )

                        continue

                    logger.info(
                        "Balance retrieved successfully: %s",
                        balance,
                    )

                    # =================================================
                    # 2. PARSE BALANCE
                    # =================================================

                    balance_value = _parse_balance_value(
                        balance
                    )

                    logger.info(
                        "Parsed balance value: %s",
                        balance_value,
                    )

                    # =================================================
                    # 3. CLEAR RECOVERED ALERT MEMORY
                    # =================================================

                    _clear_recovered_alerts(
                        alert_state,
                        balance_value,
                        logger,
                    )

                    # =================================================
                    # 4. DETERMINE CURRENT ALERT THRESHOLD
                    # =================================================

                    alert_threshold = get_alert_threshold(
                        balance_value
                    )

                    if alert_threshold is not None:

                        threshold_value = (
                            alert_threshold[0]
                        )

                        threshold_label = (
                            alert_threshold[1]
                        )

                        logger.info(
                            "Current alert threshold: %s (%s)",
                            threshold_label,
                            threshold_value,
                        )

                        threshold_already_alerted = (
                            is_threshold_alerted(
                                alert_state,
                                threshold_value,
                            )
                        )

                        if threshold_already_alerted:

                            logger.info(
                                "Alert for %s threshold "
                                "has already been sent. "
                                "No repeated alert will be sent.",
                                threshold_label,
                            )

                            should_alert = False

                        else:

                            logger.info(
                                "Alert for %s threshold "
                                "has not been sent yet.",
                                threshold_label,
                            )

                            should_alert = True

                    else:

                        logger.info(
                            "No alert threshold currently applies."
                        )

                        should_alert = False

                    # =================================================
                    # 5. DECISION ENGINE
                    # =================================================

                    decision = evaluate_balance(
                        balance_value=balance_value,
                        balance_text=balance,
                        app_name=app_name,
                        should_alert=should_alert,
                        alert_threshold=alert_threshold,
                    )

                    logger.info(
                        "Decision: action=%s "
                        "severity=%s reason=%s",
                        decision.action.value,
                        decision.severity.value,
                        decision.reason,
                    )

                    # =================================================
                    # 6. NO ACTION
                    # =================================================

                    if decision.action == Action.NO_ACTION:

                        logger.info(
                            "No WhatsApp message will be sent"
                        )

                        _sleep_until_next_run(
                            check_interval_seconds,
                            logger,
                        )

                        continue

                    # =================================================
                    # 7. ALERT
                    # =================================================

                    if decision.action == Action.ALERT:

                        if alert_threshold is None:

                            logger.error(
                                "ALERT decision received "
                                "without an alert threshold"
                            )

                            _sleep_until_next_run(
                                check_interval_seconds,
                                logger,
                            )

                            continue

                        threshold_value = (
                            alert_threshold[0]
                        )

                        threshold_label = (
                            alert_threshold[1]
                        )

                        # ------------------------------------------------
                        # Message 1: Balance
                        # ------------------------------------------------

                        balance_message = (
                            f"{app_name or 'MK Balance'}: "
                            f"{balance}"
                        )

                        logger.info(
                            "Alert detected for %s. "
                            "Sending balance before alert.",
                            threshold_label,
                        )

                        try:

                            balance_sent = (
                                send_whatsapp_message(
                                    browser,
                                    group_name,
                                    balance_message,
                                    mention_everyone=False,
                                )
                            )

                        except Exception:

                            logger.exception(
                                "Failed to send balance "
                                "before alert"
                            )

                            balance_sent = False

                        if balance_sent:

                            logger.info(
                                "Balance sent successfully "
                                "before alert"
                            )

                        else:

                            logger.error(
                                "Balance could not be sent "
                                "before alert"
                            )

                        # ------------------------------------------------
                        # Message 2: @all Alert
                        # ------------------------------------------------

                        logger.info(
                            "Sending alert with @all"
                        )

                        try:

                            alert_sent = (
                                send_whatsapp_current_chat_message(
                                    browser,
                                    decision.message,
                                    mention_everyone=True,
                                )
                            )

                        except Exception:

                            logger.exception(
                                "WhatsApp alert send failed"
                            )

                            alert_sent = False

                        # ------------------------------------------------
                        # Save memory ONLY if alert succeeded
                        # ------------------------------------------------

                        if alert_sent:

                            logger.info(
                                "Alert sent successfully"
                            )

                            mark_threshold_alerted(
                                alert_state,
                                threshold_value,
                            )

                            save_alert_state(
                                alert_state
                            )

                            logger.info(
                                "Alert memory updated for %s",
                                threshold_label,
                            )

                        else:

                            logger.error(
                                "Alert could not be sent"
                            )

                            logger.info(
                                "Alert threshold will NOT "
                                "be saved because the alert "
                                "was not successfully sent."
                            )

                        _sleep_until_next_run(
                            check_interval_seconds,
                            logger,
                        )

                        continue

                    # =================================================
                    # 8. NORMAL BALANCE
                    # =================================================

                    if decision.action == Action.SEND_BALANCE:

                        logger.info(
                            "Sending normal balance update"
                        )

                        try:

                            sent = send_whatsapp_message(
                                browser,
                                group_name,
                                decision.message,
                                mention_everyone=False,
                            )

                        except Exception:

                            logger.exception(
                                "WhatsApp send failed"
                            )

                            sent = False

                        if sent:

                            logger.info(
                                "Balance update sent "
                                "to WhatsApp group"
                            )

                        else:

                            logger.error(
                                "Unable to send "
                                "WhatsApp message"
                            )

                        _sleep_until_next_run(
                            check_interval_seconds,
                            logger,
                        )

                        continue

                if session_needs_recovery:
                    raise RuntimeError(
                        "Portal session could not be recovered"
                    )

        except Exception:

            consecutive_browser_failures += 1
            logger.exception(
                "Browser monitoring session failed. "
                "Will reconnect."
            )

            if browser_name == "existing":
                logger.warning(
                    "Existing-browser mode cannot safely restart Chrome. "
                    "Use 'python app\\main.py chrome' for automatic recovery."
                )

            elif not cdp_endpoint_is_ready(debug_port):
                logger.warning(
                    "Connection is gone. Closing the disconnected window "
                    "before the next launch."
                )
                _stop_owned_browser(
                    browser_process,
                    logger,
                    port=debug_port,
                )
                browser_process = None
                consecutive_browser_failures = 0

            elif consecutive_browser_failures >= MAX_CONSECUTIVE_BROWSER_FAILURES:
                browser_process = _restart_owned_browser(
                    browser_name,
                    browser_process,
                    logger,
                )
                consecutive_browser_failures = 0

        # --------------------------------------------------------
        # Reconnect delay
        # --------------------------------------------------------

        logger.warning(
            "Waiting 5 seconds before reconnecting "
            "to browser..."
        )

        time.sleep(5)

# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
