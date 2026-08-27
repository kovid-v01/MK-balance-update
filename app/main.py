import re
import subprocess
import sys
import time
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv

from browser import get_portal_balance, send_whatsapp_message


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


def _parse_balance_value(balance_text):
    if balance_text is None:
        return None

    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", str(balance_text))
    if not match:
        return None

    return float(match.group(0).replace(",", ""))


def _build_message(balance_text, app_name):
    label = app_name or "MK Balance"
    return f"{label}: {balance_text}"


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


def _launch_browser(browser_name):
    config = _browser_config(browser_name)
    if config is None:
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

    while True:
        logger.info("Starting portal check")

        balance = get_portal_balance()

        if not balance:
            logger.error("Unable to retrieve balance")
            _sleep_until_next_run(check_interval_seconds, logger)
            continue

        logger.info("Balance retrieved successfully: %s", balance)

        balance_value = _parse_balance_value(balance)

        if balance_value is not None and balance_value < 0:
            logger.error("Negative balance detected; skipping WhatsApp send: %s", balance)
            _sleep_until_next_run(check_interval_seconds, logger)
            continue

        message = _build_message(balance, app_name)
        sent = send_whatsapp_message(group_name, message)

        if sent:
            logger.info("Balance update sent to WhatsApp group")
        else:
            logger.error("Unable to send WhatsApp message")

        _sleep_until_next_run(check_interval_seconds, logger)


if __name__ == "__main__":
    main()
