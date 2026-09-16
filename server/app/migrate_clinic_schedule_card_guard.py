from sqlalchemy import text

from .database import engine


def run_migration():
    with engine.begin() as conn:
        # `full` cards render as both AM and PM. Convert stored rows to the
        # concrete AM/PM cards so the database can enforce the two-card limit.
        full_rows = conn.execute(text("""
            SELECT id, surgeon_id, location_id, date, assignment_type, notes
            FROM clinic_schedules
            WHERE lower(coalesce(session, '')) = 'full'
            ORDER BY id
        """)).mappings().all()
        for row in full_rows:
            exists_am = conn.execute(text("""
                SELECT id FROM clinic_schedules
                WHERE surgeon_id = :surgeon_id AND date = :date AND lower(coalesce(session, '')) = 'am'
                ORDER BY id LIMIT 1
            """), {"surgeon_id": row["surgeon_id"], "date": row["date"]}).first()
            exists_pm = conn.execute(text("""
                SELECT id FROM clinic_schedules
                WHERE surgeon_id = :surgeon_id AND date = :date AND lower(coalesce(session, '')) = 'pm'
                ORDER BY id LIMIT 1
            """), {"surgeon_id": row["surgeon_id"], "date": row["date"]}).first()

            if exists_am:
                conn.execute(text("DELETE FROM clinic_schedules WHERE id = :id"), {"id": row["id"]})
            else:
                conn.execute(text("UPDATE clinic_schedules SET session = 'am' WHERE id = :id"), {"id": row["id"]})

            if not exists_pm:
                conn.execute(text("""
                    INSERT INTO clinic_schedules
                        (surgeon_id, location_id, date, session, assignment_type, notes)
                    VALUES
                        (:surgeon_id, :location_id, :date, 'pm', :assignment_type, :notes)
                """), {
                    "surgeon_id": row["surgeon_id"],
                    "location_id": row["location_id"],
                    "date": row["date"],
                    "assignment_type": row["assignment_type"] or "assigned",
                    "notes": row["notes"],
                })

        duplicates = conn.execute(text("""
            SELECT surgeon_id, date, lower(coalesce(session, 'am')) AS session_key, MIN(id) AS keep_id
            FROM clinic_schedules
            GROUP BY surgeon_id, date, lower(coalesce(session, 'am'))
            HAVING COUNT(*) > 1
        """)).mappings().all()
        for row in duplicates:
            conn.execute(text("""
                DELETE FROM clinic_schedules
                WHERE surgeon_id = :surgeon_id
                  AND date = :date
                  AND lower(coalesce(session, 'am')) = :session_key
                  AND id <> :keep_id
            """), {
                "surgeon_id": row["surgeon_id"],
                "date": row["date"],
                "session_key": row["session_key"],
                "keep_id": row["keep_id"],
            })

        if engine.dialect.name == "sqlite":
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_clinic_schedules_surgeon_date_session
                ON clinic_schedules (surgeon_id, date, session)
            """))
        else:
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_clinic_schedules_surgeon_date_session
                ON clinic_schedules (surgeon_id, date, session)
            """))
