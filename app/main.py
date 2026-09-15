import re
import subprocess
import sys
import time
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv

from browser import (
    ensure_whatsapp_tab_open,
    get_portal_balance,
    open_browser_session,
    send_whatsapp_message,
)
from decision_engine import Action, evaluate_balance


load_dotenv()

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"
DEFAULT_GROUP_NAME = "Automations test"
DEFAULT_CHECK_INTERVAL_SECONDS = 300
DEFAULT_REMOTE_DEBUGGING_PORT = 9222
DEFAULT_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
DEFAULT_CHROME_PROFILE_DIR = r"C:\chrome-debug-profile"
DEFAULT_BRAVE_PROFILE_DIR = r"C:\brave-debug-profile"
SUPPORTED_BROWSER_NAMES = {"existing", "chrome", "brave"}


def _parse_balance_value(balance_text):
    if balance_text is None:
        return None

    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", str(balance_text))
    if not match:
        return None

    return float(match.group(0).replace(",", ""))


def _next_run_at(now, interval_seconds):
    interval = max(1, int(interval_seconds))
    timestamp = now.timestamp()
    next_timestamp = ((timestamp // interval) + 1) * interval
    return datetime.fromtimestamp(next_timestamp, tz=now.tzinfo)


def _sleep_until_next_run(interval_seconds, logger):
    now = datetime.now()
    next_run = _next_run_at(now, interval_seconds)
    sleep_seconds = max(0, (next_run - now).total_seconds())

    logger.info(
        "Next run scheduled for %s (sleeping %.1f seconds)",
        next_run.strftime("%Y-%m-%d %H:%M:%S"),
        sleep_seconds,
    )
    time.sleep(sleep_seconds)


def _browser_config(browser_name):
    browser_name = (browser_name or "existing").lower()

    if browser_name == "chrome":
        return {
            "path": os.getenv("CHROME_BROWSER_PATH", DEFAULT_CHROME_PATH),
            "user_data_dir": os.getenv("CHROME_USER_DATA_DIR", DEFAULT_CHROME_PROFILE_DIR),
        }

    if browser_name == "brave":
        return {
            "path": os.getenv("BRAVE_BROWSER_PATH", DEFAULT_BRAVE_PATH),
            "user_data_dir": os.getenv("BRAVE_USER_DATA_DIR", DEFAULT_BRAVE_PROFILE_DIR),
        }

    return None


def _validate_browser_config(browser_name, config):
    if config is None:
        return True

    browser_path = Path(config["path"])
    user_data_dir = Path(config["user_data_dir"])
    logger = logging.getLogger(__name__)

    if not browser_path.exists():
        logger.error(
            "%s browser executable not found: %s",
            browser_name,
            browser_path,
        )
        return False

    user_data_dir.mkdir(parents=True, exist_ok=True)
    return True


def _launch_browser(browser_name):
    config = _browser_config(browser_name)
    if config is None:
        return None

    if not _validate_browser_config(browser_name, config):
        return None

    browser_path = config["path"]
    user_data_dir = config["user_data_dir"]
    port = os.getenv("REMOTE_DEBUGGING_PORT", str(DEFAULT_REMOTE_DEBUGGING_PORT))

    logger = logging.getLogger(__name__)
    logger.info("Launching %s browser: %s", browser_name, browser_path)
    logger.info("Using browser profile: %s", user_data_dir)

    return subprocess.Popen(
        [
            browser_path,
            f"--remote-debugging-port={port}",
            f'--user-data-dir={user_data_dir}',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)


def main():
    logger = logging.getLogger(__name__)
    browser_name = sys.argv[1] if len(sys.argv) > 1 else "existing"
    browser_name = browser_name.lower()

    if browser_name not in SUPPORTED_BROWSER_NAMES:
        logger.error(
            "Unsupported browser mode: %s. Use existing, chrome, or brave.",
            browser_name,
        )
        sys.exit(1)

    app_name = os.getenv("APP_NAME")
    group_name = os.getenv("WHATSAPP_GROUP_NAME", DEFAULT_GROUP_NAME)
    check_interval_seconds = int(
        os.getenv("CHECK_INTERVAL_SECONDS", str(DEFAULT_CHECK_INTERVAL_SECONDS))
    )

    logger.info("Application: %s", app_name)
    logger.info("Browser mode: %s", browser_name)
    logger.info("WhatsApp group: %s", group_name)
    logger.info("Schedule interval: %s seconds", check_interval_seconds)

    browser_process = _launch_browser(browser_name)
    if browser_process is not None:
        logger.info("Waiting for browser remote debugging to become ready")
        time.sleep(5)

    with open_browser_session() as browser:
        try:
            ensure_whatsapp_tab_open(browser)
        except Exception:
            logger.exception("WhatsApp pre-open check failed")

        while True:
            logger.info("Starting portal check")

            try:
                balance = get_portal_balance(browser)
            except Exception:
                logger.exception("Portal balance retrieval failed")
                _sleep_until_next_run(check_interval_seconds, logger)
                continue

            if balance is None or str(balance).strip() == "":
                logger.error("Unable to retrieve balance")
                _sleep_until_next_run(check_interval_seconds, logger)
                continue

            logger.info("Balance retrieved successfully: %s", balance)

            balance_value = _parse_balance_value(balance)

            decision = evaluate_balance(
                balance_value=balance_value,
                balance_text=balance,
                app_name=app_name,
            )

            logger.info(
                "Decision: action=%s severity=%s reason=%s",
                decision.action.value,
                decision.severity.value,
                decision.reason,
            )

            if decision.action == Action.NO_ACTION:
                _sleep_until_next_run(check_interval_seconds, logger)
                continue

            message = decision.message

            logger.info("Preparing WhatsApp update")

            try:
                sent = send_whatsapp_message(
                    browser,
                    group_name,
                    message,
                    mention_everyone=decision.mention_everyone,
                )
            except Exception:
                logger.exception("WhatsApp send failed")
                sent = False

            if sent:
                logger.info("Balance update sent to WhatsApp group")
            else:
                logger.error("Unable to send WhatsApp message")

            _sleep_until_next_run(check_interval_seconds, logger)


if __name__ == "__main__":
    main()
