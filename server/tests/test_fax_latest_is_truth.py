"""Don (Nov 20): only the latest fax is the source of truth.

What the newest applied fax no longer lists for a date it covers comes off the
card; Undo brings it back; manual/Aprima lines and held doctor/days are kept.
"""

import os
import unittest
from datetime import datetime, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow, practice_today, stage_reviewed_rows
from app.fax_restore_service import restore_fax_snapshot
from app.fax_snapshot_service import apply_staged_snapshot
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    Base,
    Location,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    Surgeon,
)


def _weekday(offset: int) -> "date":
    day = practice_today() + timedelta(days=offset)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


DAY = _weekday(5)


class LatestFaxIsTruthTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        clinic = Location(name="Apopka Office", abbreviation="AP-OV", location_type="clinic", is_active=True)
        self.db.add(clinic)
        self.db.flush()
        self.docs = {}
        for first, last in (("Jorge", "Florin"), ("Lucy", "Woodley")):
            doc = Surgeon(first_name=first, last_name=last, email=f"{last}@example.com", is_active=True)
            self.db.add(doc)
            self.db.flush()
            week = ScheduleCardWeek(surgeon_id=doc.id, week_start=DAY - timedelta(days=DAY.weekday()), master_revision="t")
            self.db.add(week)
            self.db.flush()
            for session in ("am", "pm"):
                self.db.add(ScheduleCard(
                    week_id=week.id, surgeon_id=doc.id, date=DAY, session=session,
                    baseline_state="assigned", effective_state="assigned",
                    baseline_location_id=clinic.id, effective_location_id=clinic.id, source="master",
                ))
            self.docs[last] = doc
        self.db.commit()
        with self.engine.begin() as conn:
            create_applicable_view(conn)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _row(self, last, patient, at, *, row=None, when=None):
        doc = self.docs[last]
        return ReviewedFaxRow(
            page=1, surgeon_initials=doc.initials, surgeon_name=doc.full_name, case_date=when or DAY,
            start_time=at, row_type="clinic", room="", patient_name=patient, procedure="",
            source_row_number=row,
        )

    def _apply(self, fax_id, rows, received_hour):
        staged = stage_reviewed_rows(
            self.db, external_fax_id=fax_id, source_label="t",
            source_received_at=datetime(2026, 10, 1, received_hour, 0), rows=rows,
        )
        self.db.commit()
        return apply_staged_snapshot(self.db, source_fax_id=fax_id, run_id=staged["runId"])

    def _active(self, last=None):
        q = self.db.query(ScheduleCardActivity).filter_by(is_active=True)
        if last:
            q = q.filter_by(surgeon_id=self.docs[last].id)
        return sorted(a.patient_name for a in q.all())

    def test_newer_fax_takes_away_what_it_no_longer_lists_and_undo_restores(self):
        self._apply(445, [
            self._row("Florin", "Visit A", time(13, 0), row=1),
            self._row("Florin", "Visit B", time(13, 10), row=2),
            self._row("Florin", "Visit C", time(14, 0), row=3),
            self._row("Woodley", "Visit W", time(9, 0), row=4),
        ], received_hour=8)
        self.assertEqual(self._active("Florin"), ["Visit A", "Visit B", "Visit C"])

        # Newer fax: Florin only has Visit A. Woodley is not on this fax at all
        # (faxes come in batches of doctors), so Woodley is left alone.
        result = self._apply(450, [self._row("Florin", "Visit A", time(13, 0), row=1)], received_hour=20)
        self.assertEqual(self._active("Florin"), ["Visit A"])
        self.assertEqual(self._active("Woodley"), ["Visit W"])
        self.assertEqual(result["linesDeactivated"], 2)

        # A manual line is never touched by a fax.
        card = self.db.query(ScheduleCard).filter_by(surgeon_id=self.docs["Woodley"].id, date=DAY, session="am").one()
        self.db.add(ScheduleCardActivity(
            schedule_card_id=card.id, surgeon_id=card.surgeon_id, activity_date=DAY, session="am",
            activity_type="clinic", patient_name="Manual Visit", procedure="", source_system="manual",
            source_record_key="manual|1", identity_key="manual1", is_active=True,
        ))
        self.db.commit()

        restore_fax_snapshot(self.db, source_fax_id=450)
        self.assertEqual(self._active("Florin"), ["Visit A", "Visit B", "Visit C"])
        self.assertEqual(self._active("Woodley"), ["Manual Visit", "Visit W"])

    def test_doctor_on_the_fax_but_not_on_a_date_goes_to_zero_that_date(self):
        later = _weekday(6)
        for doc in self.docs.values():
            week = self.db.query(ScheduleCardWeek).filter_by(surgeon_id=doc.id).first()
            for session in ("am", "pm"):
                if not self.db.query(ScheduleCard).filter_by(surgeon_id=doc.id, date=later, session=session).first():
                    self.db.add(ScheduleCard(week_id=week.id, surgeon_id=doc.id, date=later, session=session,
                                             baseline_state="na", effective_state="na", source="master"))
        self.db.commit()
        self._apply(445, [
            self._row("Florin", "Visit A", time(13, 0), row=1),
            self._row("Florin", "Visit Later", time(9, 0), row=2, when=later),
        ], received_hour=8)
        # Newer fax runs DAY..later (Woodley has a row on DAY) and lists Florin on
        # the later date only: Florin's DAY is taken away.
        self._apply(450, [
            self._row("Woodley", "Visit W", time(9, 0), row=1),
            self._row("Florin", "Visit Later", time(9, 0), row=2, when=later),
        ], received_hour=20)
        self.assertEqual(self._active("Florin"), ["Visit Later"])

    def test_doctor_day_with_a_held_row_keeps_its_lines(self):
        self._apply(445, [
            self._row("Florin", "Visit A", time(13, 0), row=1),
            self._row("Florin", "Visit B", time(13, 10), row=2),
        ], received_hour=8)
        held = ReviewedFaxRow(
            page=1, surgeon_initials="JF", surgeon_name="Jorge Florin", case_date=DAY,
            start_time=None, row_type="clinic", room="", patient_name="No Time", procedure="",
            source_row_number=9,
        )
        self._apply(450, [self._row("Florin", "Visit A", time(13, 0), row=1), held], received_hour=20)
        # Visit B stays: the newest fax has a Florin row for DAY that CAL could not place.
        self.assertEqual(self._active("Florin"), ["Visit A", "Visit B"])


if __name__ == "__main__":
    unittest.main()
