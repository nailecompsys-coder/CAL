"""Prod smoke: assign doc to disposable Block OR → in-app alert created, then cleanup."""
from datetime import date, time, timedelta

from app.database import SessionLocal
from app.models import Location, NativePushToken, NativeScheduleAlert, ORBlockAssignment, Surgeon
from app.or_block_service import (
    BlockORCreateInput,
    assign_block,
    create_or_blocks,
    delete_or_block_instance,
    remove_block_assignment,
)


def main() -> int:
    db = SessionLocal()
    try:
        tokens = db.query(NativePushToken).filter(NativePushToken.is_active == True).count()  # noqa: E712
        print("active_native_tokens", tokens)
        day = date.today() + timedelta(days=45)
        while day.weekday() > 4:
            day += timedelta(days=1)
        loc = db.query(Location).filter(Location.is_active == True).order_by(Location.id).first()  # noqa: E712
        surgeon = (
            db.query(Surgeon)
            .filter(Surgeon.is_active == True, Surgeon.staff_type == "physician")  # noqa: E712
            .order_by(Surgeon.id)
            .first()
        )
        print(
            "smoke_day",
            day,
            "loc",
            getattr(loc, "id", None),
            "surgeon",
            getattr(surgeon, "id", None),
            getattr(surgeon, "initials", None),
        )
        if not loc or not surgeon:
            print("FAIL missing loc/surgeon")
            return 1
        created = create_or_blocks(
            db,
            BlockORCreateInput(
                name="SMOKE notify block",
                start_date=day,
                end_date=day,
                weekdays=[day.weekday()],
                location_ids=[loc.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ),
        )
        block_id = created["instance_ids"][0]
        before = db.query(NativeScheduleAlert).filter(NativeScheduleAlert.surgeon_id == surgeon.id).count()
        block, warnings = assign_block(
            db,
            block_id,
            surgeon.id,
            assigned_start_time=time(7, 30),
            case_count=1,
            assignment_note="SMOKE TEST override — delete me",
        )
        after = (
            db.query(NativeScheduleAlert)
            .filter(NativeScheduleAlert.surgeon_id == surgeon.id)
            .order_by(NativeScheduleAlert.id.desc())
            .first()
        )
        print("assign_ok", block.status, "warnings", warnings)
        print(
            "alert_created",
            bool(after),
            "title",
            getattr(after, "title", None),
            "body",
            getattr(after, "body", None),
        )
        delta = db.query(NativeScheduleAlert).filter(NativeScheduleAlert.surgeon_id == surgeon.id).count() - before
        print("alert_count_delta", delta)
        asg = db.query(ORBlockAssignment).filter(ORBlockAssignment.block_instance_id == block_id).first()
        if asg:
            remove_block_assignment(db, block_id, asg.id)
        delete_or_block_instance(db, block_id)
        # remove smoke alerts we just created for this surgeon (title Block OR *)
        for row in (
            db.query(NativeScheduleAlert)
            .filter(
                NativeScheduleAlert.surgeon_id == surgeon.id,
                NativeScheduleAlert.title.in_(["Block OR updated", "Block OR removed"]),
            )
            .order_by(NativeScheduleAlert.id.desc())
            .limit(4)
            .all()
        ):
            db.delete(row)
        db.commit()
        print("cleaned")
        ok = block.status == "assigned" and delta >= 1 and after and after.title == "Block OR updated"
        print("SMOKE", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
