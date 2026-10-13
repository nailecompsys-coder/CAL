"""Native on-call coverage serialization helpers."""

from .models import CallCoverage, CallDraftAssignment, CallRotation
from .surgeon_visibility import surgeon_is_visible


def active_coverage_for_rotation(rotation: CallRotation) -> CallCoverage | None:
    for coverage in rotation.coverages or []:
        if coverage.status == "active" and surgeon_is_visible(coverage.covering_surgeon):
            return coverage
    return None


def serialize_draft_call_assignment(draft: CallDraftAssignment, viewer_id: int) -> dict:
    """Calendar Call chip for a Call Builder draft cell (not yet published).

    rotationId is 0 (not null) so older iOS clients that require Int still decode the day.
    Cover stays disabled client-side when rotationId is nil/0.
    """
    group = draft.call_group
    surgeon = draft.surgeon if draft.surgeon_id and surgeon_is_visible(draft.surgeon) else None
    return {
        "rotationId": 0,
        "groupId": draft.call_group_id,
        "group": group.name if group else "Call",
        "surgeon": surgeon.full_name if surgeon else "No call",
        "surgeonId": surgeon.id if surgeon else None,
        "initials": surgeon.initials if surgeon else "NC",
        "isSelf": bool(surgeon and surgeon.id == viewer_id),
        "originalSurgeon": surgeon.full_name if surgeon else "No call",
        "originalSurgeonId": surgeon.id if surgeon else None,
        "originalInitials": surgeon.initials if surgeon else "NC",
        "coveringSurgeon": None,
        "coveringSurgeonId": None,
        "coveringInitials": None,
        "isCovered": False,
        "coverageId": None,
        "backupSurgeon": None,
        "backupSurgeonId": None,
        "isBackup": False,
        "backupInitials": None,
        "backupNote": None,
        "source": "draft",
    }


def serialize_call_assignment(rotation: CallRotation, viewer_id: int) -> dict:
    coverage = active_coverage_for_rotation(rotation)
    original = rotation.surgeon
    covering = coverage.covering_surgeon if coverage else None
    active_surgeon = covering or (original if surgeon_is_visible(original) else None)
    backup = rotation.backup.surgeon if rotation.backup and not coverage else None
    if not surgeon_is_visible(backup):
        backup = None
    return {
        "rotationId": rotation.id,
        "groupId": rotation.call_group_id,
        "group": rotation.call_group.name if rotation.call_group else "Call",
        "surgeon": active_surgeon.full_name if active_surgeon else "No call",
        "surgeonId": active_surgeon.id if active_surgeon else None,
        "initials": active_surgeon.initials if active_surgeon else "NC",
        "isSelf": bool(active_surgeon and active_surgeon.id == viewer_id),
        "originalSurgeon": original.full_name if surgeon_is_visible(original) else "No call",
        "originalSurgeonId": original.id if surgeon_is_visible(original) else None,
        "originalInitials": original.initials if surgeon_is_visible(original) else "NC",
        "coveringSurgeon": covering.full_name if covering else None,
        "coveringSurgeonId": covering.id if covering else None,
        "coveringInitials": covering.initials if covering else None,
        "isCovered": coverage is not None,
        "coverageId": coverage.id if coverage else None,
        "backupSurgeon": backup.full_name if backup else None,
        "backupSurgeonId": backup.id if backup else None,
        "isBackup": bool(backup and backup.id == viewer_id),
        "backupInitials": backup.initials if backup else None,
        "backupNote": rotation.backup.note if backup else None,
        "source": "live",
    }
