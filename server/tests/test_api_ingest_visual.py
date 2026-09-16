import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException

from app.fax_visual_ingest_service import BackupReceipt
from app.routers.api_ingest import (
    VisualFaxRowIn,
    VisualScheduleBatch,
    ingest_visual_schedule_route,
    retired_surgeon_schedule_route,
    retired_surgical_cases_route,
)


class ApiIngestVisualTest(unittest.TestCase):
    def test_visual_schedule_endpoint_backs_up_and_applies_reviewed_rows(self):
        body = VisualScheduleBatch(
            source_fax_id=162,
            rows=[
                VisualFaxRowIn(
                    fax_id=162,
                    page=2,
                    surgeon_initials="jf",
                    case_date="2026-09-16",
                    start_time="0715",
                    row_type="surgical",
                    room="MIN S05",
                    patient_name="White, Jeffrey Allan",
                    procedure="Robotic assisted case",
                )
            ],
        )
        db = Mock()
        receipt = BackupReceipt(True, "unit", "/tmp/backup.dump", {"size_bytes": 10})
        with (
            patch("app.routers.api_ingest.run_local_backup", return_value=receipt) as backup,
            patch("app.routers.api_ingest.apply_visual_schedule", return_value={"ok": True}) as apply,
        ):
            result = ingest_visual_schedule_route(body, db=db)

        backup.assert_called_once()
        apply.assert_called_once()
        args, kwargs = apply.call_args
        self.assertIs(args[0], db)
        self.assertEqual(kwargs["source_fax_id"], 162)
        self.assertEqual(args[1][0].surgeon_initials, "JF")
        self.assertEqual(args[1][0].start_time.strftime("%H:%M"), "07:15")
        self.assertEqual(result["result"], {"ok": True})

    def test_visual_schedule_endpoint_refuses_without_backup(self):
        body = VisualScheduleBatch(
            source_fax_id=162,
            rows=[
                VisualFaxRowIn(
                    page=1,
                    surgeon_initials="JF",
                    case_date="2026-09-16",
                    row_type="clinic",
                    room="CLMMFLGS",
                    patient_name="Flores, Anna",
                )
            ],
        )
        with patch(
            "app.routers.api_ingest.run_local_backup",
            return_value=BackupReceipt(False, "unit", metadata={"error": "no pg_dump"}),
        ):
            with self.assertRaises(HTTPException) as ctx:
                ingest_visual_schedule_route(body, db=Mock())
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("Backup failed", ctx.exception.detail)

    def test_old_desk_write_routes_are_retired(self):
        for route in (retired_surgeon_schedule_route, retired_surgical_cases_route):
            with self.assertRaises(HTTPException) as ctx:
                route()
            self.assertEqual(ctx.exception.status_code, 410)
            self.assertIn("visual-schedule", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
