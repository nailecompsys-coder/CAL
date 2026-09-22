import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_pdf_intake import prepare_fax_pdf
from app.models import Base, FaxDocument, FaxPage


class FaxPdfIntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_root = os.environ.get("CAL_FAX_DATA_DIR")
        os.environ["CAL_FAX_DATA_DIR"] = self.temp.name
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()
        if self.previous_root is None:
            os.environ.pop("CAL_FAX_DATA_DIR", None)
        else:
            os.environ["CAL_FAX_DATA_DIR"] = self.previous_root

    @staticmethod
    def fake_render(pdf_path: Path, workdir: Path, expected_pages: int):
        pages = workdir / "pages"
        ocr = workdir / "ocr"
        pages.mkdir()
        ocr.mkdir()
        output = []
        for number in range(1, expected_pages + 1):
            image = pages / f"page-{number}.png"
            text = ocr / f"page-{number:03d}.txt"
            image.write_bytes(f"png-{number}".encode())
            text.write_text(f"ocr-{number}")
            output.append({
                "page_number": number,
                "image_path": image,
                "image_sha256": "a" * 64,
                "ocr_text_path": text,
                "ocr_text_sha256": "b" * 64,
            })
        return output

    def test_prepare_records_verified_pdf_and_pages(self):
        with (
            patch("app.fax_pdf_intake._pdf_page_count", return_value=2),
            patch("app.fax_pdf_intake._render_and_ocr", side_effect=self.fake_render),
        ):
            result = prepare_fax_pdf(
                self.db,
                external_fax_id=168,
                original_filename="fax-168.pdf",
                source=io.BytesIO(b"%PDF-1.7 test"),
            )
            self.db.commit()

        document = self.db.query(FaxDocument).one()
        self.assertEqual(result["pageCount"], 2)
        self.assertEqual(result["writeMode"], "staging_only")
        self.assertEqual(document.status, "rendered")
        self.assertTrue(Path(document.source_path).exists())
        self.assertEqual(self.db.query(FaxPage).count(), 2)

    def test_same_fax_and_checksum_is_idempotent(self):
        with (
            patch("app.fax_pdf_intake._pdf_page_count", return_value=1),
            patch("app.fax_pdf_intake._render_and_ocr", side_effect=self.fake_render),
        ):
            prepare_fax_pdf(self.db, external_fax_id=168, original_filename="fax.pdf", source=io.BytesIO(b"%PDF-1.7 same"))
            self.db.commit()
            result = prepare_fax_pdf(self.db, external_fax_id=168, original_filename="fax.pdf", source=io.BytesIO(b"%PDF-1.7 same"))
        self.assertTrue(result["idempotent"])
        self.assertEqual(self.db.query(FaxDocument).count(), 1)
        self.assertEqual(self.db.query(FaxPage).count(), 1)

    def test_rejects_non_pdf_before_render(self):
        with self.assertRaisesRegex(ValueError, "valid PDF"):
            prepare_fax_pdf(self.db, external_fax_id=168, original_filename="bad.pdf", source=io.BytesIO(b"not pdf"))
        self.assertEqual(self.db.query(FaxDocument).count(), 0)

    def test_rejects_different_pdf_for_existing_fax_id(self):
        with (
            patch("app.fax_pdf_intake._pdf_page_count", return_value=1),
            patch("app.fax_pdf_intake._render_and_ocr", side_effect=self.fake_render),
        ):
            prepare_fax_pdf(self.db, external_fax_id=168, original_filename="fax.pdf", source=io.BytesIO(b"%PDF-1.7 first"))
            self.db.commit()
            with self.assertRaisesRegex(ValueError, "different immutable PDF"):
                prepare_fax_pdf(self.db, external_fax_id=168, original_filename="fax.pdf", source=io.BytesIO(b"%PDF-1.7 second"))


if __name__ == "__main__":
    unittest.main()
