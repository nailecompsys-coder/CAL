"""Rules engine: load config from DB, run enabled rules, return structured conflicts."""
import json
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from .registry import ALL_RULES, Conflict, RuleDef

log = logging.getLogger(__name__)


def get_rule_config(db: Session) -> dict[str, dict]:
    """
    Load per-rule config from DB. Returns dict: rule_id -> { "enabled": bool, "config": dict }.
    Missing rules use default from ALL_RULES; DB overrides.
    """
    from ..models import SchedulingRuleConfig
    stored = {}
    for row in db.query(SchedulingRuleConfig).all():
        config = {}
        if row.config:
            try:
                config = json.loads(row.config) if isinstance(row.config, str) else (row.config or {})
            except (TypeError, ValueError):
                pass
        stored[row.rule_id] = {"enabled": row.enabled, "config": config}
    out = {}
    for rule in ALL_RULES:
        r = stored.get(rule.rule_id)
        if r is not None:
            merged = dict(rule.default_config)
            merged.update(r.get("config") or {})
            out[rule.rule_id] = {"enabled": r["enabled"], "config": merged}
        else:
            out[rule.rule_id] = {"enabled": True, "config": dict(rule.default_config)}
    return out


def ensure_rule_config_seeded(db: Session) -> None:
    """Ensure every rule in ALL_RULES has a row in SchedulingRuleConfig (for settings UI)."""
    from ..models import SchedulingRuleConfig
    existing = {r.rule_id for r in db.query(SchedulingRuleConfig).all()}
    for rule in ALL_RULES:
        if rule.rule_id not in existing:
            db.add(SchedulingRuleConfig(
                rule_id=rule.rule_id,
                enabled=True,
                config=json.dumps(rule.default_config),
            ))
            existing.add(rule.rule_id)
    db.commit()


_DAY_OFF_RULES = {
    "OVERLAP_DAY_OFF",
    "OVERLAP_CALL",
    "OVERLAP_CLINIC",
    "OVERLAP_SURGERY",
    "OVERLAP_OR_BLOCK",
    "OVERLAP_MEETING",
    "CLINIC_GROUP_DAY_OFF_CAPACITY",
}

_AVAILABILITY_RULES = {
    "OVERLAP_DAY_OFF",
    "OVERLAP_CALL",
    "OVERLAP_CLINIC",
    "OVERLAP_SURGERY",
    "OVERLAP_OR_BLOCK",
    "OVERLAP_MEETING",
}

_MEETING_RULES = {
    "OVERLAP_DAY_OFF",
    "OVERLAP_CALL",
    "OVERLAP_CLINIC",
    "OVERLAP_SURGERY",
    "OVERLAP_OR_BLOCK",
    "OVERLAP_MEETING",
    "OVERLAP_UNAVAILABLE",
}

_CALL_RULES = {
    "OVERLAP_DAY_OFF",
    "OVERLAP_CALL",
    "OVERLAP_CLINIC",
    "OVERLAP_SURGERY",
    "OVERLAP_OR_BLOCK",
    "OVERLAP_MEETING",
    "OVERLAP_UNAVAILABLE",
}


def evaluate(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    exclude_entity: Optional[tuple[str, int]] = None,
    rule_config: Optional[dict[str, dict]] = None,
    target_entity: Optional[dict] = None,
) -> list[Conflict]:
    """
    Run all enabled rules for the surgeon over [start_date, end_date].
    Only evaluates today-forward (practice timezone). Past windows return [].
    """
    from ..scheduling_gate_service import clip_window_to_now, notify_missing_rule

    clipped = clip_window_to_now(start_date, end_date)
    if clipped is None:
        return []
    start_date, end_date = clipped

    if rule_config is None:
        rule_config = get_rule_config(db)
    results = []
    target_type = (target_entity or {}).get("type")
    applicable_rules = {
        "day_off": _DAY_OFF_RULES,
        "availability": _AVAILABILITY_RULES,
        "clinic_schedule": {rule.rule_id for rule in ALL_RULES},
        "surgical_case": {rule.rule_id for rule in ALL_RULES},
        "or_block": {rule.rule_id for rule in ALL_RULES},
        "meeting": _MEETING_RULES,
        "call_rotation": _CALL_RULES,
        "call_coverage": _CALL_RULES,
    }
    if target_type and target_type not in applicable_rules:
        notify_missing_rule(
            db,
            "TARGET_TYPE_MAP",
            f"No applicable rule set for target type {target_type!r} (surgeon {surgeon_id})",
        )

    for rule in ALL_RULES:
        if not rule.checker:
            notify_missing_rule(db, rule.rule_id, "Rule has no checker function")
            continue
        if target_type and rule.rule_id not in applicable_rules.get(target_type, set()):
            continue
        rc = rule_config.get(rule.rule_id)
        if rc is None or not rc.get("enabled", True):
            continue
        config = rc.get("config") or {}
        try:
            for c in rule.checker(
                surgeon_id,
                start_date,
                end_date,
                db,
                config,
                exclude_entity,
                target_entity,
            ):
                if c.date < start_date:
                    continue
                results.append(c)
        except Exception as exc:
            log.exception("Scheduling rule failed: %s", rule.rule_id)
            notify_missing_rule(db, rule.rule_id, f"{type(exc).__name__}: {exc}")
            continue
    return results


def conflicts_to_messages(conflicts: list[Conflict], surgeon_names: Optional[dict[int, str]] = None) -> list[str]:
    """Convert Conflict list to legacy list of display strings (for _warn_redirect)."""
    out = []
    for c in conflicts:
        name = surgeon_names.get(c.surgeon_id) if surgeon_names else None
        out.append(c.to_display_string(name))
    return out
