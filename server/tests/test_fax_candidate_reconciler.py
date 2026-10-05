import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_candidate_reconciler import reconcile_desk_extract
from app.models import Base, FaxDocument, FaxPage, Surgeon


class FaxCandidateReconcilerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            Surgeon(first_name="Jorge", last_name="Florin", is_active=True),
            Surgeon(first_name="Lucy", last_name="Woodley", is_active=True),
        ])
        self.doc = FaxDocument(external_fax_id=245, source_sha256="sha", page_count=3)
        self.db.add(self.doc)
        self.db.flush()
        for number, contents in enumerate([
            "Surgeon: Jorge Luis Florin, MD\n",
            "10/08/26 08:45 Person, Alex EXCISION WGD S08\n",
            "Surgeon: Lucille Woodley, MD\n10/09/26 10:30 Other, Ben Procedure AHMGGENSRG\n10/09/26 10:40 Third, Chris Post-op AHMGGENSRG\n",
        ], start=1):
            path = Path(self.temp.name) / f"page-{number}.txt"
            path.write_text(contents)
            self.db.add(FaxPage(
                fax_document_id=self.doc.id, page_number=number,
                image_path=str(path), image_sha256="image",
                ocr_text_path=str(path), ocr_text_sha256="ocr",
            ))
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def test_fax_header_overrides_wrong_desk_surgeon_and_clinic_group(self):
        extract = {"schedule": {"surgeons": [{
            "surgeon_name": "Lucy Woodley, MD",
            "or_block": {"cases": [
                {"case_date": "2026-10-08", "start_time": "08:45", "patient_name": "Person, Alex", "room": "WGD S08", "procedure": "EXCISION"},
                {"case_date": "2026-10-09", "start_time": "10:30", "patient_name": "Other, Ben", "room": "AHMGGENSRG", "procedure": "Procedure"},
            ]},
            "clinic_rotation": {"slots": [
                {"case_date": "2026-10-09", "start_time": "10:40", "patient_name": "Third, Chris", "site_raw": "AHMGGENSRG", "procedure": "Post-op"},
            ]},
        }]}}
        rows, report = reconcile_desk_extract(self.db, self.doc, extract)
        self.assertEqual(report, {"rows": 3, "sourcePageReassignments": 1, "visitTypeCorrections": 1})
        self.assertEqual((rows[0].surgeon_initials, rows[0].page, rows[0].row_type), ("JF", 2, "surgical"))
        self.assertEqual((rows[1].surgeon_initials, rows[1].page, rows[1].row_type), ("LW", 3, "clinic"))


if __name__ == "__main__":
    unittest.main()
