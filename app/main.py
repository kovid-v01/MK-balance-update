import re
import time
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from browser import get_portal_balance, send_whatsapp_message


load_dotenv()

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"
DEFAULT_GROUP_NAME = "Automations test"
DEFAULT_CHECK_INTERVAL_SECONDS = 300


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

    app_name = os.getenv("APP_NAME")
    group_name = os.getenv("WHATSAPP_GROUP_NAME", DEFAULT_GROUP_NAME)
    check_interval_seconds = int(
        os.getenv("CHECK_INTERVAL_SECONDS", str(DEFAULT_CHECK_INTERVAL_SECONDS))
    )

    logger.info("Application: %s", app_name)
    logger.info("WhatsApp group: %s", group_name)
    logger.info("Check interval: %s seconds", check_interval_seconds)

    while True:
        logger.info("Starting portal check")

        balance = get_portal_balance()

        if not balance:
            logger.error("Unable to retrieve balance")
            time.sleep(check_interval_seconds)
            continue

        logger.info("Balance retrieved successfully: %s", balance)

        balance_value = _parse_balance_value(balance)

        if balance_value is not None and balance_value < 0:
            logger.error("Negative balance detected; skipping WhatsApp send: %s", balance)
            time.sleep(check_interval_seconds)
            continue

        message = _build_message(balance, app_name)
        sent = send_whatsapp_message(group_name, message)

        if sent:
            logger.info("Balance update sent to WhatsApp group")
        else:
            logger.error("Unable to send WhatsApp message")

        time.sleep(check_interval_seconds)


if __name__ == "__main__":
    main()
