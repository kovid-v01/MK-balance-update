import logging
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "app.log"


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

    logger.info("Application: %s", app_name)
    logger.info("Automation platform started")


if __name__ == "__main__":
    main()