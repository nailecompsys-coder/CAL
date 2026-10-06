import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_source_validation import page_owners
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
        self.assertEqual(page_owners(self.db, self.doc), {1: "JF", 2: "JF", 3: "LW", 4: "LW"})


if __name__ == "__main__":
    unittest.main()
