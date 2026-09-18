import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


# Alert memory will be stored here:
#
# automation-platform-test/
# ├── app/
# │   ├── main.py
# │   ├── browser.py
# │   ├── decision_engine.py
# │   └── alert_memory.py
# │
# └── data/
#     └── alert_state.json
#
DATA_DIR = Path("data")
STATE_FILE = DATA_DIR / "alert_state.json"


def load_alert_state():
    """
    Load previously triggered alert thresholds from disk.

    If no memory file exists, start with an empty state.
    """

    if not STATE_FILE.exists():
        logger.info("No alert memory found. Starting with empty state.")

        return {
            "alerted_thresholds": []
        }

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        # Make sure the expected key exists.
        if "alerted_thresholds" not in state:
            state["alerted_thresholds"] = []

        logger.info("Alert memory loaded: %s", state)

        return state

    except Exception:
        logger.exception(
            "Failed to load alert memory. Starting with empty state."
        )

        return {
            "alerted_thresholds": []
        }


def save_alert_state(state):
    """
    Save alert memory to disk.

    A temporary file is written first and then replaced
    so that we don't leave a partially written JSON file
    if the application is interrupted during the write.
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    temporary_file = STATE_FILE.with_suffix(".tmp")

    try:
        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(
                state,
                file,
                indent=2
            )

        temporary_file.replace(STATE_FILE)

        logger.info("Alert memory saved: %s", state)

    except Exception:
        logger.exception("Failed to save alert memory")


def is_threshold_alerted(state, threshold):
    """
    Check whether an alert has already been sent
    for the specified threshold.
    """

    if threshold is None:
        return False

    alerted_thresholds = state.get(
        "alerted_thresholds",
        []
    )

    return threshold in alerted_thresholds


def mark_threshold_alerted(state, threshold):
    """
    Mark a threshold as alerted.

    This prevents the same alert from being sent
    repeatedly while the balance remains below that
    threshold.
    """

    if threshold is None:
        return

    alerted_thresholds = state.setdefault(
        "alerted_thresholds",
        []
    )

    if threshold not in alerted_thresholds:
        alerted_thresholds.append(threshold)

        logger.info(
            "Alert threshold marked as triggered: %s",
            threshold
        )


def clear_threshold_alert(state, threshold):
    """
    Clear a threshold from alert memory.

    This is important for recovery.

    Example:

        ₹45 L  → alert below ₹50 L
        ₹60 L  → threshold cleared
        ₹40 L  → alert below ₹50 L again
    """

    if threshold is None:
        return

    alerted_thresholds = state.get(
        "alerted_thresholds",
        []
    )

    if threshold in alerted_thresholds:
        alerted_thresholds.remove(threshold)

        logger.info(
            "Alert threshold cleared: %s",
            threshold
        )


def clear_all_alerts(state):
    """
    Clear all remembered alert thresholds.
    """

    state["alerted_thresholds"] = []

    logger.info("All alert memory cleared")