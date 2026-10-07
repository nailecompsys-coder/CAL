"""SQL-owned "who's where" day board for surgeons and PAs (locations only, no patients)."""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import text


@lru_cache(maxsize=2)
def _statement(dialect: str):
    sql = Path(__file__).with_name("sql").joinpath("native_whos_where.sql").read_text()
    if dialect == "postgresql":
        tokens = {
            "DAY_VALUE": "CAST(:day AS DATE)",
            "JSON_SEGMENTS": "LATERAL jsonb_array_elements(CASE WHEN d.segments IS JSON ARRAY THEN d.segments::jsonb ELSE '[]'::jsonb END)",
            "HAS_SEGMENTS": "coalesce(d.segments IS JSON ARRAY,FALSE)",
            "JSON_FULL": "j.value->>'isFullDay'", "JSON_START": "j.value->>'start'",
            "JSON_END": "j.value->>'end'", "JSON_DAY": "j.value->>'date'",
        }
    elif dialect == "sqlite":
        tokens = {
            "DAY_VALUE": ":day",
            "JSON_SEGMENTS": "json_each(CASE WHEN json_valid(d.segments) THEN d.segments ELSE '[]' END)",
            "HAS_SEGMENTS": "coalesce(json_type(CASE WHEN json_valid(d.segments) THEN d.segments ELSE 'null' END) = 'array',FALSE)",
            "JSON_FULL": "CAST(json_extract(j.value,'$.isFullDay') AS TEXT)",
            "JSON_START": "json_extract(j.value,'$.start')", "JSON_END": "json_extract(j.value,'$.end')",
            "JSON_DAY": "json_extract(j.value,'$.date')",
        }
    else:
        raise ValueError(f"Unsupported database: {dialect}")
    for token, expression in tokens.items():
        sql = sql.replace(token, expression)
    return text(sql)


def whos_where(db, day) -> list[dict]:
    """Serialize SQL-selected rows; no Python filtering or sorting."""
    rows = db.execute(_statement(db.bind.dialect.name), {"day": day.isoformat()}).mappings()
    return [{
        "session": row["session"],
        "groupId": row["group_id"],
        "group": row["group_name"] or "",
        "surgeonId": row["surgeon_id"],
        "name": row["name"],
        "initials": row["initials"],
        "staffType": row["staff_type"],
        "state": row["state"],
        "onLeave": bool(row["on_leave"]),
        "noCall": bool(row["no_call"]),
        "location": row["location_code"] or "",
        "locationName": row["location_name"] or "",
        "color": row["location_color"] or "",
    } for row in rows]
