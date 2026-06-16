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


if __name__ == "__main__":
    unittest.main()
