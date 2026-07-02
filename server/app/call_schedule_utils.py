"""Practice-wide call rotation indexing (per CallGroup + date)."""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import CallGroup, CallRotation


def orphan_target_group_ids(call_groups: list) -> tuple[int | None, int | None]:
    """
    Map legacy rows with call_group_id NULL to a group (same rules as reclaim_orphan_rotations).
    Primary → Winter Garden… name if present, else first group by sort order.
    Backup → Altamonte… if present, else second group or same as primary when only one row.
    """
    if not call_groups:
        return None, None
    from .migrate_call_groups import GROUP1_NAME, GROUP2_NAME

    by_name = {g.name: g.id for g in call_groups}
    ordered = sorted(call_groups, key=lambda g: (g.sort_order, g.name, g.id))
    g1 = by_name.get(GROUP1_NAME) or (ordered[0].id if ordered else None)
    g2 = by_name.get(GROUP2_NAME)
    if g2 is None and len(ordered) > 1:
        g2 = ordered[1].id
    elif g2 is None:
        g2 = g1
    return g1, g2


def index_rotations_by_group_date(
    rotations: list,
    call_groups: list | None = None,
) -> dict[int, dict[date, dict[str, Any]]]:
    """
    group_id -> date -> {"primary": CallRotation|None, "backup": CallRotation|None}
    Rows with call_group_id NULL are folded onto default groups (same as admin reclaim).
    """
    gid_primary_orphan: int | None = None
    gid_backup_orphan: int | None = None
    if call_groups:
        gid_primary_orphan, gid_backup_orphan = orphan_target_group_ids(call_groups)

    out: dict[int, dict[date, dict[str, Any]]] = {}
    for r in rotations:
        gid = r.call_group_id
        if gid is None:
            if r.rotation_type == "primary":
                gid = gid_primary_orphan
            elif r.rotation_type == "backup":
                gid = gid_backup_orphan
            else:
                continue
        if gid is None:
            continue
        by_date = out.setdefault(gid, {})
        slot = by_date.setdefault(r.date, {"primary": None, "backup": None})
        if r.rotation_type == "primary" and slot["primary"] is None:
            slot["primary"] = r
        elif r.rotation_type == "backup" and slot["backup"] is None:
            slot["backup"] = r
    return out


def initials_from_rotation(rot: Any | None) -> str | None:
    """Initials for display, or 'NC' when slot exists but no surgeon, or None if no row."""
    if rot is None:
        return None
    if not rot.surgeon_id:
        return "NC"
    if rot.surgeon:
        return rot.surgeon.initials
    return "NC"


def build_call_group_rows(call_groups: list) -> list[tuple[Any, list[int]]]:
    """
    One row per unique group name (same dedupe as admin call schedule).
    Returns (representative_group, contributing_db_ids) for merging rotations.
    """
    seen: set[str] = set()
    rows: list[tuple[Any, list[int]]] = []
    ordered = sorted(call_groups, key=lambda g: (g.sort_order, g.name, g.id))
    for g in ordered:
        if g.name in seen:
            continue
        seen.add(g.name)
        contrib = [x.id for x in ordered if x.name == g.name]
        rows.append((g, contrib))
    return rows


def merge_primary_backup_for_day(
    contrib_ids: list[int],
    index: dict[int, dict[date, dict[str, Any]]],
    day: date,
) -> tuple[Any | None, Any | None]:
    pr, bk = None, None
    for gid in contrib_ids:
        cell = index.get(gid, {}).get(day, {"primary": None, "backup": None})
        if pr is None:
            pr = cell.get("primary")
        if bk is None:
            bk = cell.get("backup")
    return pr, bk


def build_merged_slot_index(
    group_rows: list[tuple[Any, list[int]]],
    raw_index: dict[int, dict[date, dict[str, Any]]],
) -> dict[int, dict[date, dict[str, Any]]]:
    """representative_group.id -> date -> {"primary","backup"} merged across duplicate names."""
    out: dict[int, dict[date, dict[str, Any]]] = {}
    for rep_g, contrib_ids in group_rows:
        by_date: dict[date, dict[str, Any]] = {}
        dates: set[date] = set()
        for gid in contrib_ids:
            for d in raw_index.get(gid, {}):
                dates.add(d)
        for d in dates:
            pr, bk = merge_primary_backup_for_day(contrib_ids, raw_index, d)
            by_date[d] = {"primary": pr, "backup": bk}
        out[rep_g.id] = by_date
    return out


def build_call_rail_slot(rep_g: Any, pr: Any | None, bk: Any | None) -> dict[str, Any]:
    """
    Main line: primary if a primary row exists (even NC); else backup-only assignments
    show on the main line (matches admin single-cell behavior).
    Second line: backup initials when a primary row exists and backup exists.
    """
    main_i: str | None = None
    sub_i: str | None = None
    if pr is not None:
        main_i = initials_from_rotation(pr)
        if bk is not None:
            sub_i = initials_from_rotation(bk)
    elif bk is not None:
        main_i = initials_from_rotation(bk)
    return {
        "group_id": rep_g.id,
        "group_label": rep_g.name,
        "primary_initials": main_i,
        "backup_initials": sub_i,
    }


def build_call_rail_slots(
    group_rows: list[tuple[Any, list[int]]],
    index: dict[int, dict[date, dict[str, Any]]],
    day: date,
) -> list[dict]:
    """Ordered rail cells: one per logical call group (deduped name)."""
    slots: list[dict] = []
    for rep_g, contrib_ids in group_rows:
        pr, bk = merge_primary_backup_for_day(contrib_ids, index, day)
        slots.append(build_call_rail_slot(rep_g, pr, bk))
    return slots


def serialize_call_group_rail(slots: list[dict]) -> list[dict]:
    """Shape for week_json / JS."""
    return [
        {
            "groupName": s["group_label"],
            "primaryInitials": s["primary_initials"] or "",
            "backupInitials": s["backup_initials"] or "",
        }
        for s in slots
    ]
