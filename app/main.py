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

    return subprocess.Popen(
        [
            browser_path,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={user_data_dir}",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_owned_browser(browser_process, logger):
    """Stop only the Chrome process started by this application."""
    if browser_process is None or browser_process.poll() is not None:
        return

    logger.warning(
        "Stopping the app-owned browser process (PID %s) for recovery",
        browser_process.pid,
    )

    browser_process.terminate()

    try:
        browser_process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        logger.warning("Browser did not exit gracefully; terminating it forcefully")
        browser_process.kill()
        browser_process.wait(timeout=10)


def _restart_owned_browser(browser_name, browser_process, logger):
    """Restart the dedicated browser after repeated CDP or portal failures."""
    _stop_owned_browser(browser_process, logger)

    logger.warning("Restarting app-owned %s browser for automatic recovery", browser_name)
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

def main():

    logger = logging.getLogger(__name__)

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

    debug_port = os.getenv(
        "REMOTE_DEBUGGING_PORT",
        str(DEFAULT_REMOTE_DEBUGGING_PORT),
    )
    browser_process = _launch_browser(browser_name)
    consecutive_browser_failures = 0

    while True:

        try:

            if (
                browser_name != "existing"
                and browser_process is not None
                and browser_process.poll() is not None
            ):
                logger.warning(
                    "The app-owned browser process exited unexpectedly; "
                    "starting a replacement."
                )
                browser_process = _launch_browser(browser_name)

            if not wait_for_cdp_endpoint(
                debug_port,
                timeout_seconds=CDP_STARTUP_TIMEOUT_SECONDS,
            ):
                raise RuntimeError("Chrome DevTools endpoint is unavailable")

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

            if (
                browser_name != "existing"
                and consecutive_browser_failures
                >= MAX_CONSECUTIVE_BROWSER_FAILURES
            ):
                browser_process = _restart_owned_browser(
                    browser_name,
                    browser_process,
                    logger,
                )
                consecutive_browser_failures = 0

            elif browser_name == "existing":
                logger.warning(
                    "Existing-browser mode cannot safely restart Chrome. "
                    "Use 'python app\\main.py chrome' for automatic recovery."
                )

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
