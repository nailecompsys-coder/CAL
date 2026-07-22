"""Service builder for the native iOS home payload."""
from datetime import date

from sqlalchemy.orm import Session

from .models import Surgeon
from .native_home_items import (
    append_clinic_items,
    append_meetings,
    append_aprima_surgery_items,
    append_block_or_items,
    append_my_call_items,
    append_my_day_off_items,
    append_personal_items,
    append_surgical_items,
    availability,
    call_groups as query_call_groups,
    empty_days,
    my_day_off_rows,
    requests,
    sort_day_items,
    surgeons,
)
from .native_support import (
    native_day_off_sections,
)
from .native_home_sections import build_native_call_schedule, native_alerts


class NativeHomeService:
    def __init__(self, db: Session, surgeon: Surgeon, start_date: date, end_date: date):
        self.db = db
        self.surgeon = surgeon
        self.start_date = start_date
        self.end_date = end_date
        self.today = date.today()
        self.days = empty_days(start_date, end_date)
        self.by_date = {d["date"]: d for d in self.days}
        self.my_day_off_rows = my_day_off_rows(db, surgeon, start_date, end_date)

    def build(self) -> dict:
        append_my_call_items(self.db, self.surgeon, self.start_date, self.end_date, self.by_date)
        append_my_day_off_items(self.my_day_off_rows, self.start_date, self.end_date, self.by_date)
        append_meetings(self.db, self.surgeon, self.start_date, self.end_date, self.by_date)
        append_clinic_items(self.db, self.surgeon, self.start_date, self.end_date, self.by_date, self.my_day_off_rows)
        append_block_or_items(self.db, self.surgeon, self.start_date, self.end_date, self.by_date, self.my_day_off_rows)
        append_surgical_items(self.db, self.surgeon, self.start_date, self.end_date, self.by_date, self.my_day_off_rows)
        append_aprima_surgery_items(self.db, self.surgeon, self.start_date, self.end_date, self.by_date, self.my_day_off_rows)
        append_personal_items(self.db, self.surgeon, self.start_date, self.end_date, self.by_date)
        sort_day_items(self.days)

        availability_rows = availability(self.db, self.surgeon, self.today)
        request_rows = requests(self.db, self.surgeon, self.today)
        call_group_rows = query_call_groups(self.db)
        call_schedule = build_native_call_schedule(self.db, self.surgeon, self.start_date, self.end_date, self.by_date)
        alerts = native_alerts(self.db, self.surgeon)

        return {
            "surgeon": {"id": self.surgeon.id, "name": self.surgeon.full_name, "staffType": self.surgeon.staff_type},
            "range": {"start": self.start_date.isoformat(), "end": self.end_date.isoformat()},
            "days": self.days,
            "availability": availability_rows,
            "requests": request_rows,
            "dayOffSections": native_day_off_sections(self.db, self.surgeon),
            "callGroups": [{"id": group.id, "name": group.name} for group in call_group_rows],
            "surgeons": surgeons(self.db),
            "callSchedule": call_schedule,
            "alerts": alerts,
        }

def build_native_home(db: Session, surgeon: Surgeon, start_date: date, end_date: date) -> dict:
    return NativeHomeService(db, surgeon, start_date, end_date).build()
