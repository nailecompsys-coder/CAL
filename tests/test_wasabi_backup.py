import unittest
import sys
import types
from unittest.mock import patch

sys.modules.setdefault("botocore", types.ModuleType("botocore"))
sys.modules.setdefault("boto3", types.SimpleNamespace(client=lambda *args, **kwargs: None))
fake_exceptions = types.ModuleType("botocore.exceptions")
fake_exceptions.ClientError = Exception
sys.modules.setdefault("botocore.exceptions", fake_exceptions)
fake_config = types.ModuleType("botocore.config")
fake_config.Config = lambda *args, **kwargs: None
sys.modules.setdefault("botocore.config", fake_config)

from app import wasabi_backup


class FakePaginator:
    def paginate(self, **kwargs):
        return [
            {
                "Contents": [
                    {
                        "Key": "cal-backups/20260616-194617/db.sql.gz",
                        "Size": 643544867,
                    },
                    {
                        "Key": "cal-backups/20260616-194617/metadata.json",
                        "Size": 128,
                    },
                    {"Key": "cal-backups/", "Size": 0},
                ]
            }
        ]


class FakeS3Client:
    def get_paginator(self, name):
        self.paginator_name = name
        return FakePaginator()


class WasabiBackupTest(unittest.TestCase):
    def test_list_backups_includes_files_inside_timestamp_prefix(self):
        with patch("app.wasabi_backup.is_configured", return_value=True):
            with patch("app.wasabi_backup._s3_client", return_value=FakeS3Client()):
                backups = wasabi_backup.list_backups()

        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["timestamp"], "20260616-194617")
        self.assertEqual(backups[0]["total_bytes"], 643544995)
        self.assertEqual(
            backups[0]["files"][0]["key"],
            "cal-backups/20260616-194617/db.sql.gz",
        )

    def test_dr_manifest_uses_git_for_code_and_redacts_secrets(self):
        with patch("app.wasabi_backup._version", return_value="1.35"):
            with patch("app.wasabi_backup._git_value") as git_value:
                git_value.side_effect = [
                    "git@github.com:nailecompsys-coder/CAL.git",
                    "abc123",
                    "main",
                    "",
                ]
                with patch.dict(
                    "os.environ",
                    {
                        "DATABASE_URL": "postgresql://cal_app:secret@cal_postgres:5432/cal_prod",
                        "WASABI_BUCKET": "mfsa-cal",
                        "WASABI_KEY_ID": "key",
                        "WASABI_SECRET": "secret",
                        "CAL_DB_USER": "cal_app",
                    },
                    clear=True,
                ):
                    manifest = wasabi_backup._dr_manifest(
                        "20260616-194617",
                        123,
                        "cal-backups/20260616-194617/db.sql.gz",
                    )

        self.assertEqual(manifest["restore"]["code_source"], "git")
        self.assertEqual(manifest["database"]["dump_size_bytes"], 123)
        self.assertEqual(manifest["env"]["safe_values"]["WASABI_BUCKET"], "mfsa-cal")
        self.assertIn("DATABASE_URL", manifest["env"]["present_secret_keys"])
        self.assertNotIn("postgresql://cal_app:secret", str(manifest["env"]))


if __name__ == "__main__":
    unittest.main()
