import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_source_validation import validate_page_ownership
from app.models import Base, FaxDocument, FaxPage, Surgeon


class FaxSourceValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            Surgeon(first_name="Jorge", last_name="Florin", is_active=True),
            Surgeon(first_name="Lucy", last_name="Woodley", is_active=True),
        ])
        self.doc = FaxDocument(external_fax_id=245, source_sha256="sha", page_count=4)
        self.db.add(self.doc)
        self.db.flush()
        for number, text in enumerate([
            "Surgeon: Jorge Luis Florin, MD\n",
            "Continuation of patient table\n",
            "Surgeon: Lucille Eugenie Woodley, MD\n",
            "Continuation of patient table\n",
        ], start=1):
            path = Path(self.tmp.name) / f"page-{number}.txt"
            path.write_text(text)
            self.db.add(FaxPage(
                fax_document_id=self.doc.id, page_number=number,
                ocr_text_path=str(path), image_path=str(path),
                image_sha256="image", ocr_text_sha256="ocr",
            ))
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_continuation_pages_keep_prior_surgeon(self):
        validate_page_ownership(self.db, self.doc, [
            SimpleNamespace(page=2, surgeon_initials="JF"),
            SimpleNamespace(page=4, surgeon_initials="LW"),
        ])

    def test_florin_continuation_cannot_be_attributed_to_woodley(self):
        with self.assertRaisesRegex(ValueError, "conflicts with source page 2"):
            validate_page_ownership(self.db, self.doc, [SimpleNamespace(page=2, surgeon_initials="LW")])

    def test_row_without_source_page_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no verified source page"):
            validate_page_ownership(self.db, self.doc, [SimpleNamespace(page=0, surgeon_initials="LW")])


if __name__ == "__main__":
    unittest.main()
