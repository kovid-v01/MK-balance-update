import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def main():
    logger = logging.getLogger(__name__)
    logger.info("Automation platform started")


if __name__ == "__main__":
    main()