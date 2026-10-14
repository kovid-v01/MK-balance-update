import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "app"))

import main  # noqa: E402


class LogRetentionTests(unittest.TestCase):
    def test_deletes_logs_older_than_two_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            now = datetime(2026, 10, 14, 21, 0, 0)
            (log_dir / "app-2026-10-14.log").write_text("today")
            (log_dir / "app-2026-10-13.log").write_text("yesterday")
            (log_dir / "app-2026-10-12.log").write_text("two days")
            (log_dir / "app-2026-10-11.log").write_text("too old")
            (log_dir / "automation.lock").write_text("keep")

            main._purge_old_log_files(
                log_dir=log_dir,
                retention_days=2,
                now=now,
            )

            names = sorted(path.name for path in log_dir.iterdir())
            self.assertEqual(
                names,
                [
                    "app-2026-10-12.log",
                    "app-2026-10-13.log",
                    "app-2026-10-14.log",
                    "automation.lock",
                ],
            )


if __name__ == "__main__":
    unittest.main()
