"""Native on-call coverage serialization helpers."""

from .models import CallCoverage, CallRotation
from .surgeon_visibility import surgeon_is_visible


def active_coverage_for_rotation(rotation: CallRotation) -> CallCoverage | None:
    for coverage in rotation.coverages or []:
        if coverage.status == "active" and surgeon_is_visible(coverage.covering_surgeon):
            return coverage
    return None


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
        "backupInitials": backup.initials if backup else None,
        "backupNote": rotation.backup.note if backup else None,
    }
