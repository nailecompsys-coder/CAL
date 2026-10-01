"""Execute one parameterized SQL calendar read and return its JSON result."""
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text


@lru_cache(maxsize=2)
def calendar_statement(dialect):
    sql = Path(__file__).with_name("sql").joinpath("master_calendar.sql").read_text()
    if dialect == "postgresql":
        tokens = {
            "DATE_SQL": "DATE", "NEXT_DAY": "day + 1",
            "JSON_SEGMENTS": "LATERAL jsonb_array_elements(CASE WHEN d.segments IS JSON ARRAY THEN d.segments::jsonb ELSE '[]'::jsonb END)",
            "HAS_SEGMENTS": "coalesce(d.segments IS JSON ARRAY,FALSE)",
            "JSON_FULL": "j.value->>'isFullDay'", "JSON_START": "j.value->>'start'",
            "JSON_END": "j.value->>'end'", "JSON_DAY": "j.value->>'date'",
            "WEEKDAY_CARD": "extract(isodow FROM c.date) <= 5",
            "JOBJ": "jsonb_build_object", "JAGG": "jsonb_agg", "JARRAY": "jsonb_build_array",
            "JVAL(coalesce(c.roster,'[]'))": "coalesce(c.roster,'[]'::jsonb)",
            "JVAL(props)": "props",
        }
    elif dialect == "sqlite":
        tokens = {
            "DATE_SQL": "TEXT", "NEXT_DAY": "date(day, '+1 day')",
            "JSON_SEGMENTS": "json_each(CASE WHEN json_valid(d.segments) THEN d.segments ELSE '[]' END)",
            "HAS_SEGMENTS": "coalesce(json_type(CASE WHEN json_valid(d.segments) THEN d.segments ELSE 'null' END) = 'array',FALSE)",
            "JSON_FULL": "CAST(json_extract(j.value,'$.isFullDay') AS TEXT)",
            "JSON_START": "json_extract(j.value,'$.start')", "JSON_END": "json_extract(j.value,'$.end')",
            "JSON_DAY": "json_extract(j.value,'$.date')", "WEEKDAY_CARD": "strftime('%w', c.date) NOT IN ('0','6')",
            "JOBJ": "json_object", "JAGG": "json_group_array", "JARRAY": "json_array", "JVAL": "json",
        }
    else:
        raise ValueError(f"Unsupported calendar database: {dialect}")
    for token, expression in tokens.items():
        sql = sql.replace(token, expression)
    return text(sql)


def build_master_calendar_events(db, start, end, surgeon_id=None):
    payload = db.execute(calendar_statement(db.bind.dialect.name), {
        "start_date": start.isoformat(), "end_date": end.isoformat(), "surgeon_id": surgeon_id,
    }).scalar_one()
    # SQLite returns JSON text; PostgreSQL returns the already-decoded JSONB value.
    return json.loads(payload) if isinstance(payload, str) else payload
