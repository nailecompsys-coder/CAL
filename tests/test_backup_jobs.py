import importlib
import app
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class BackupJobsTest(unittest.TestCase):
    def test_backup_job_records_success_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["CAL_BACKUP_STATUS_PATH"] = os.path.join(tmpdir, "status.json")
            import app.backup_jobs as backup_jobs

            importlib.reload(backup_jobs)
            self.assertTrue(backup_jobs.start_backup_job("admin"))
            self.assertFalse(backup_jobs.start_backup_job("admin"))

            fake_wasabi = types.SimpleNamespace(run_backup=lambda: {
                "success": True,
                "wasabi_ok": True,
                "timestamp": "20260616-120000",
                "wasabi_key": "cal-backups/20260616-120000/db.sql.gz",
                "db_size_bytes": 1024,
            })
            original_wasabi = getattr(app, "wasabi_backup", None)
            with patch.dict(sys.modules, {"app.wasabi_backup": fake_wasabi}):
                app.wasabi_backup = fake_wasabi
                try:
                    backup_jobs.run_backup_job("admin")
                finally:
                    if original_wasabi is None:
                        delattr(app, "wasabi_backup")
                    else:
                        app.wasabi_backup = original_wasabi

            status = backup_jobs.backup_status()
            self.assertEqual(status["state"], "succeeded")
            self.assertEqual(status["timestamp"], "20260616-120000")


if __name__ == "__main__":
    unittest.main()
