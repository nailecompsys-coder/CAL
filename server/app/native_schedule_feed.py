"""Read the native schedule from permanent master cards and source cases."""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import text


@lru_cache(maxsize=2)
def _statement(dialect: str):
    sql = Path(__file__).with_name("sql").joinpath("native_schedule.sql").read_text()
    if dialect == "postgresql":
        tokens = {
            "WEEKDAY_CARD": "extract(isodow FROM c.date) <= 5",
            "DATE_SQL": "DATE", "NEXT_DAY": "day + 1",
            "JSON_SEGMENTS": "LATERAL jsonb_array_elements(CASE WHEN d.segments IS JSON ARRAY THEN d.segments::jsonb ELSE '[]'::jsonb END)",
            "HAS_SEGMENTS": "coalesce(d.segments IS JSON ARRAY,FALSE)",
            "JSON_FULL": "j.value->>'isFullDay'", "JSON_START": "j.value->>'start'",
            "JSON_END": "j.value->>'end'", "JSON_DAY": "j.value->>'date'",
        }
    elif dialect == "sqlite":
        tokens = {
            "WEEKDAY_CARD": "strftime('%w', c.date) NOT IN ('0','6')",
            "DATE_SQL": "TEXT", "NEXT_DAY": "date(day, '+1 day')",
            "JSON_SEGMENTS": "json_each(CASE WHEN json_valid(d.segments) THEN d.segments ELSE '[]' END)",
            "HAS_SEGMENTS": "coalesce(json_type(CASE WHEN json_valid(d.segments) THEN d.segments ELSE 'null' END) = 'array',FALSE)",
            "JSON_FULL": "CAST(json_extract(j.value,'$.isFullDay') AS TEXT)",
            "JSON_START": "json_extract(j.value,'$.start')", "JSON_END": "json_extract(j.value,'$.end')",
            "JSON_DAY": "json_extract(j.value,'$.date')",
        }
    else:
        raise ValueError(f"Unsupported native schedule database: {dialect}")
    for token, expression in tokens.items():
        sql = sql.replace(token, expression)
    return text(sql)


def append_native_schedule(db, surgeon_id, start_date, end_date, by_date):
    """SQL determines included rows, conflicts, and order; this maps the API contract."""
    rows = db.execute(_statement(db.bind.dialect.name), {
        "surgeon_id": surgeon_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }).mappings()
    for row in rows:
        item = {
            "id": row["item_id"],
            "type": row["item_type"],
            "title": row["title"],
            "subtitle": row["subtitle"],
            "start": row["start_time"],
            "end": row["end_time"],
            "location": row["location"],
            "room": row["room"],
            "notes": row["notes"] or "",
            "source": row["source"],
            "needsReview": bool(row["needs_review"]),
            "color": row["color"],
        }
        if row["raw_id"] is not None:
            item.update({
                "rawId": row["raw_id"],
                "status": row["status"] or "scheduled",
                "surgeonNotes": row["surgeon_notes"] or "",
                "assistingSurgeon": row["assisting_surgeon"] or "",
                "readOnly": bool(row["assisting"]),
            })
        by_date[str(row["item_date"])]["items"].append(item)
