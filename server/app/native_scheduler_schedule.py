"""SQL-owned, all-surgeon schedule facts for the native Scheduler view."""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import text


@lru_cache(maxsize=2)
def _statement(dialect: str):
    sql = Path(__file__).with_name("sql").joinpath("native_scheduler_schedule.sql").read_text()
    core_sql = Path(__file__).with_name("sql").joinpath("native_schedule.sql").read_text().rstrip().rstrip(";")
    if dialect == "postgresql":
        tokens = {
            "DATE_SQL": "DATE", "NEXT_DAY": "day + 1",
            "WEEKDAY_CAL": "extract(isodow FROM cal.day) <= 5",
            "WEEKDAY_CARD": "extract(isodow FROM c.date) <= 5",
            "JSON_SEGMENTS": "LATERAL jsonb_array_elements(CASE WHEN d.segments IS JSON ARRAY THEN d.segments::jsonb ELSE '[]'::jsonb END)",
            "HAS_SEGMENTS": "coalesce(d.segments IS JSON ARRAY,FALSE)",
            "JSON_FULL": "j.value->>'isFullDay'", "JSON_START": "j.value->>'start'",
            "JSON_END": "j.value->>'end'", "JSON_DAY": "j.value->>'date'",
        }
    elif dialect == "sqlite":
        tokens = {
            "DATE_SQL": "TEXT", "NEXT_DAY": "date(day, '+1 day')",
            "WEEKDAY_CAL": "strftime('%w', cal.day) NOT IN ('0','6')",
            "WEEKDAY_CARD": "strftime('%w', c.date) NOT IN ('0','6')",
            "JSON_SEGMENTS": "json_each(CASE WHEN json_valid(d.segments) THEN d.segments ELSE '[]' END)",
            "HAS_SEGMENTS": "coalesce(json_type(CASE WHEN json_valid(d.segments) THEN d.segments ELSE 'null' END) = 'array',FALSE)",
            "JSON_FULL": "CAST(json_extract(j.value,'$.isFullDay') AS TEXT)",
            "JSON_START": "json_extract(j.value,'$.start')", "JSON_END": "json_extract(j.value,'$.end')",
            "JSON_DAY": "json_extract(j.value,'$.date')",
        }
    else:
        raise ValueError(f"Unsupported scheduler database: {dialect}")
    for token, expression in tokens.items():
        sql = sql.replace(token, expression)
        core_sql = core_sql.replace(token, expression)
    core_sql = core_sql.replace(":surgeon_id", "r.id")
    if dialect == "postgresql":
        core_rows = f"SELECT r.id AS surgeon_id, core.* FROM roster r CROSS JOIN LATERAL ({core_sql}) core"
    else:
        fields = ("item_id", "item_date", "item_type", "title", "subtitle", "start_time",
                  "end_time", "location", "room", "needs_review")
        json_fields = ", ".join(f"'{field}', core.{field}" for field in fields)
        extracted = ", ".join(
            f"json_extract(packed.value, '$.{field}') AS {field}" for field in fields
        )
        core_rows = (
            f"SELECT r.id AS surgeon_id, {extracted} FROM roster r CROSS JOIN "
            f"json_each((SELECT json_group_array(json_object({json_fields})) "
            f"FROM ({core_sql}) core)) packed"
        )
    sql = sql.replace("CORE_ROWS", core_rows)
    return text(sql)


def scheduler_schedule(db, start_date, end_date) -> list[dict]:
    """Serialize SQL-selected rows; no Python filtering, counting, or sorting."""
    rows = db.execute(_statement(db.bind.dialect.name), {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }).mappings()
    return [{
        "surgeonId": row["surgeon_id"],
        "surgeon": row["surgeon"],
        "date": str(row["item_date"]),
        "id": row["item_id"],
        "session": row["session"],
        "type": row["item_type"],
        "title": row["title"],
        "subtitle": row["subtitle"] or "",
        "start": row["start_time"] or "",
        "end": row["end_time"] or "",
        "location": row["location"] or "",
        "room": row["room"] or "",
        "needsReview": bool(row["needs_review"]),
        "dayCaseCount": row["day_case_count"],
        "dayVisitCount": row["day_visit_count"],
        "dayOffCount": row["day_off_count"],
    } for row in rows]
