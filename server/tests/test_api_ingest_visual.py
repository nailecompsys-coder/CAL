import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException

from app.routers.api_ingest import (
    VisualFaxRowIn,
    VisualScheduleBatch,
    ingest_visual_schedule_route,
    retired_surgeon_schedule_route,
    retired_surgical_cases_route,
)


class ApiIngestVisualTest(unittest.TestCase):
    def setUp(self):
        self._freeze = os.environ.pop("CAL_SCHEDULE_WRITE_FREEZE", None)
        os.environ["CAL_SCHEDULE_WRITE_FREEZE"] = "0"

    def tearDown(self):
        if self._freeze is not None:
            os.environ["CAL_SCHEDULE_WRITE_FREEZE"] = self._freeze
        else:
            os.environ.pop("CAL_SCHEDULE_WRITE_FREEZE", None)

    def test_visual_schedule_endpoint_stages_even_when_legacy_writes_are_frozen(self):
        os.environ["CAL_SCHEDULE_WRITE_FREEZE"] = "1"
        body = VisualScheduleBatch(
            source_fax_id=168,
            rows=[
                VisualFaxRowIn(
                    page=1,
                    surgeon_initials="JF",
                    case_date="2026-09-16",
                    row_type="surgical",
                    room="MIN S05",
                    patient_name="White, Jeffrey Allan",
                )
            ],
        )
        with patch("app.routers.api_ingest.stage_reviewed_rows", return_value={"writeMode": "staging_only"}) as stage:
            result = ingest_visual_schedule_route(body, db=Mock())
        stage.assert_called_once()
        self.assertEqual(result["result"]["writeMode"], "staging_only")

    def test_visual_schedule_endpoint_stages_reviewed_rows_without_backup_or_apply(self):
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
        with patch("app.routers.api_ingest.stage_reviewed_rows", return_value={"writeMode": "staging_only"}) as stage:
            result = ingest_visual_schedule_route(body, db=db)

        stage.assert_called_once()
        args, kwargs = stage.call_args
        self.assertIs(args[0], db)
        self.assertEqual(kwargs["external_fax_id"], 162)
        self.assertEqual(kwargs["rows"][0].surgeon_initials, "JF")
        self.assertEqual(kwargs["rows"][0].start_time.strftime("%H:%M"), "07:15")
        self.assertEqual(result["result"], {"writeMode": "staging_only"})

    def test_visual_schedule_endpoint_refuses_invalid_row_type(self):
        body = VisualScheduleBatch(
            source_fax_id=162,
            rows=[
                VisualFaxRowIn(
                    page=1,
                    surgeon_initials="JF",
                    case_date="2026-09-16",
                    row_type="not-a-row",
                    room="CLMMFLGS",
                    patient_name="Flores, Anna",
                )
            ],
        )
        with self.assertRaises(HTTPException) as ctx:
            ingest_visual_schedule_route(body, db=Mock())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("row_type", ctx.exception.detail)

    def test_old_desk_write_routes_are_retired(self):
        for route in (retired_surgeon_schedule_route, retired_surgical_cases_route):
            with self.assertRaises(HTTPException) as ctx:
                route()
            self.assertEqual(ctx.exception.status_code, 410)
            self.assertIn("visual-schedule", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
