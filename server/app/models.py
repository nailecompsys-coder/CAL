from datetime import date, datetime, time
from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer,
    String, Text, Time, UniqueConstraint, func
)
from sqlalchemy.orm import relationship
from .database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    first_name = Column(String(64))
    last_name = Column(String(64))
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(32))
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="admin")  # admin | superadmin
    notify_day_off_requests = Column(Boolean, default=True, server_default="true")
    notify_schedule_changes = Column(Boolean, default=True, server_default="true")
    sms_fallback_enabled = Column(Boolean, default=False, server_default="false")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    @property
    def full_name(self) -> str:
        name = f"{self.first_name or ''} {self.last_name or ''}".strip()
        return name or self.username


class AdminOtpChallenge(Base):
    __tablename__ = "admin_otp_challenges"
    id = Column(Integer, primary_key=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False)
    token_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    admin_user = relationship("AdminUser")


class SiteSettings(Base):
    __tablename__ = "site_settings"
    id = Column(Integer, primary_key=True)           # always row 1
    practice_name = Column(String(128), default="Mid Florida Surgical")
    practice_address = Column(String(255))
    practice_city = Column(String(64))
    practice_state = Column(String(32))
    practice_zip = Column(String(16))
    practice_phone = Column(String(32))
    practice_email = Column(String(255))
    logo_filename = Column(String(255))              # e.g. "logo.png" stored in static/uploads/
    show_or_patient_procedure_form = Column(Boolean, default=False, server_default="false")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SchedulingRuleConfig(Base):
    """Per-rule config for the scheduling rules engine. One row per rule_id."""
    __tablename__ = "scheduling_rule_config"
    id = Column(Integer, primary_key=True)
    rule_id = Column(String(64), unique=True, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    config = Column(Text)  # JSON object: e.g. {"minutes": 30}
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Location(Base):
    __tablename__ = "locations"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    abbreviation = Column(String(12), nullable=False, default="LOC", server_default="LOC")
    address = Column(String(255))
    city = Column(String(64))
    phone = Column(String(32))
    location_type = Column(String(16), default="clinic", server_default="clinic")  # clinic | hospital
    color = Column(String(16), default="#0ea5e9")  # color for calendar
    is_active = Column(Boolean, default=True)


class Surgeon(Base):
    __tablename__ = "surgeons"
    id = Column(Integer, primary_key=True)
    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    specialty = Column(String(128))
    suffix = Column(String(32))   # MD, DO, MD FACS, PA-C, NP, etc.
    staff_type = Column(String(16), default="physician", server_default="physician")  # physician | staff
    email = Column(String(255), unique=True)
    phone = Column(String(32))
    color = Column(String(16), default="#ffffff", server_default="#ffffff")  # reserved; calendar uses facility colors only
    sort_order = Column(Integer, default=0, server_default="0")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    devices = relationship("SurgeonDevice", back_populates="surgeon", cascade="all, delete-orphan")
    magic_links = relationship("MagicLink", back_populates="surgeon", cascade="all, delete-orphan")
    call_rotations = relationship("CallRotation", back_populates="surgeon", cascade="all, delete-orphan")
    days_off = relationship("DayOff", back_populates="surgeon", cascade="all, delete-orphan")
    meeting_attendees = relationship("MeetingAttendee", back_populates="surgeon", cascade="all, delete-orphan")
    availability = relationship("Availability", back_populates="surgeon", cascade="all, delete-orphan")
    push_subscriptions = relationship("PushSubscription", back_populates="surgeon", cascade="all, delete-orphan")
    native_push_tokens = relationship("NativePushToken", back_populates="surgeon", cascade="all, delete-orphan")
    native_schedule_alerts = relationship("NativeScheduleAlert", back_populates="surgeon", cascade="all, delete-orphan")
    location_schedules = relationship("SurgeonLocationSchedule", back_populates="surgeon", cascade="all, delete-orphan")
    location_overrides = relationship("LocationOverride", back_populates="surgeon", cascade="all, delete-orphan")
    clinic_schedules = relationship("ClinicSchedule", back_populates="surgeon", cascade="all, delete-orphan")
    surgical_cases = relationship("SurgicalCase", back_populates="surgeon", cascade="all, delete-orphan")
    day_items = relationship("SurgeonDayItem", back_populates="surgeon", cascade="all, delete-orphan")
    clinic_group_memberships = relationship("ClinicGroupMember", back_populates="surgeon", cascade="all, delete-orphan")
    surgical_blocks = relationship("SurgicalBlock", back_populates="surgeon", cascade="all, delete-orphan")
    or_block_instances = relationship("ORBlockInstance", foreign_keys="ORBlockInstance.assigned_surgeon_id", back_populates="assigned_surgeon")

    def _strip_dr(self, name: str) -> str:
        """Remove leading 'Dr.' or 'Dr ' for display; do not store prefix in DB."""
        if not name:
            return name
        s = name.strip()
        if s.upper().startswith("DR."):
            return s[3:].strip()
        if s.upper().startswith("DR "):
            return s[2:].strip()
        return s

    @property
    def full_name(self) -> str:
        first = self._strip_dr(self.first_name or "")
        last = self._strip_dr(self.last_name or "")
        return f"{first} {last}".strip() or f"{self.first_name or ''} {self.last_name or ''}".strip()

    @property
    def initials(self):
        f = (self.first_name or "").strip()
        l = (self.last_name or "").strip()
        return f"{f[0] if f else '?'}{l[0] if l else '?'}".upper()


class MagicLink(Base):
    __tablename__ = "magic_links"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon", back_populates="magic_links")


class SurgeonOtpAuditLog(Base):
    __tablename__ = "surgeon_otp_audit_logs"
    id = Column(Integer, primary_key=True)
    action = Column(String(16), nullable=False)  # request | verify
    submitted_email = Column(String(255), nullable=False)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=True)
    matched = Column(Boolean, default=False, nullable=False)
    delivery_channel = Column(String(16))  # sms | email | none
    delivery_success = Column(Boolean)
    result = Column(String(32), nullable=False)  # requested | verified | invalid_email | invalid_code | delivery_failed
    failure_reason = Column(Text)
    client_ip = Column(String(64))
    user_agent = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon")


class SurgeonDevice(Base):
    __tablename__ = "surgeon_devices"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    device_name = Column(String(128))  # e.g. "iPhone 15 Pro"
    user_agent = Column(Text)
    token_hash = Column(String(255), unique=True, nullable=False)  # session token
    registered_at = Column(DateTime, server_default=func.now())
    last_seen = Column(DateTime)
    is_active = Column(Boolean, default=True)

    surgeon = relationship("Surgeon", back_populates="devices")
    push_subscriptions = relationship("PushSubscription", back_populates="device")


class SurgeonLocationSchedule(Base):
    """Default weekly schedule template: what a surgeon does each AM/PM session Mon-Fri."""
    __tablename__ = "surgeon_location_schedules"
    __table_args__ = (UniqueConstraint("surgeon_id", "day_of_week", "session"),)
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)  # null when float/off
    day_of_week = Column(Integer, nullable=False)  # 0=Mon ... 4=Fri
    session = Column(String(4), nullable=False, default="am")  # am | pm
    # assigned = has location; float = available wherever needed; off = not working that session
    assignment_type = Column(String(16), nullable=False, default="assigned", server_default="assigned")

    surgeon = relationship("Surgeon", back_populates="location_schedules")
    location = relationship("Location")


class CallRotationTemplate(Base):
    """Ordered surgeon rotation for a call group — used to auto-fill call schedule."""
    __tablename__ = "call_rotation_templates"
    __table_args__ = (
        UniqueConstraint("call_group_id", "surgeon_id"),
        UniqueConstraint("call_group_id", "position"),
    )
    id = Column(Integer, primary_key=True)
    call_group_id = Column(Integer, ForeignKey("call_groups.id"), nullable=False)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    position = Column(Integer, nullable=False)  # 1 = first in rotation

    call_group = relationship("CallGroup")
    surgeon = relationship("Surgeon")


class LocationOverride(Base):
    """Manual per-day location override for a surgeon."""
    __tablename__ = "location_overrides"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"))  # null = no clinic that day
    date = Column(Date, nullable=False)
    notes = Column(Text)

    surgeon = relationship("Surgeon", back_populates="location_overrides")
    location = relationship("Location")


class CallGroup(Base):
    __tablename__ = "call_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    sort_order = Column(Integer, default=0, server_default="0")

    locations = relationship(
        "CallGroupLocation",
        back_populates="call_group",
        cascade="all, delete-orphan",
    )
    rotations = relationship("CallRotation", back_populates="call_group")


class CallGroupLocation(Base):
    """Many-to-many: a call group can cover multiple locations (hospitals/clinics)."""
    __tablename__ = "call_group_locations"
    __table_args__ = (UniqueConstraint("call_group_id", "location_id"),)
    id = Column(Integer, primary_key=True)
    call_group_id = Column(Integer, ForeignKey("call_groups.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)

    call_group = relationship("CallGroup", back_populates="locations")
    location = relationship("Location")


class CallRotation(Base):
    __tablename__ = "call_rotations"
    id = Column(Integer, primary_key=True)
    call_group_id = Column(Integer, ForeignKey("call_groups.id"), nullable=True)  # nullable for migration
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=True)  # null = NO call
    date = Column(Date, nullable=False)
    rotation_type = Column(String(16), default="primary")  # always primary; kept for legacy compat
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon", back_populates="call_rotations")
    call_group = relationship("CallGroup", back_populates="rotations")
    coverages = relationship("CallCoverage", back_populates="rotation", cascade="all, delete-orphan")

    @property
    def active_coverage(self):
        for coverage in self.coverages or []:
            if coverage.status == "active":
                return coverage
        return None


class CallCoverage(Base):
    """One-day on-call coverage overlay: original assignee stays visible, covering surgeon handles that day."""
    __tablename__ = "call_coverages"
    id = Column(Integer, primary_key=True)
    call_rotation_id = Column(Integer, ForeignKey("call_rotations.id"), nullable=False)
    original_surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=True)
    covering_surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    requested_by_surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=True)
    status = Column(String(16), default="active", server_default="active")  # active | canceled
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    canceled_at = Column(DateTime)

    rotation = relationship("CallRotation", back_populates="coverages")
    original_surgeon = relationship("Surgeon", foreign_keys=[original_surgeon_id])
    covering_surgeon = relationship("Surgeon", foreign_keys=[covering_surgeon_id])
    requested_by_surgeon = relationship("Surgeon", foreign_keys=[requested_by_surgeon_id])


class Availability(Base):
    __tablename__ = "availability"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    date = Column(Date, nullable=False)
    is_available = Column(Boolean, default=True)
    start_time = Column(Time)
    end_time = Column(Time)
    notes = Column(Text)

    surgeon = relationship("Surgeon", back_populates="availability")


class DayOff(Base):
    __tablename__ = "days_off"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(String(255))
    start_time = Column(Time)
    end_time = Column(Time)
    is_full_day = Column(Boolean, default=True, server_default="true")
    segments = Column(Text)
    status = Column(String(16), default="pending")  # pending | approved | denied
    notes = Column(Text)  # surgeon's note
    admin_note = Column(Text)  # admin's response
    review_findings = Column(Text)  # JSON list of system findings for scheduler approval review
    approved_by = Column(Integer, ForeignKey("admin_users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    surgeon = relationship("Surgeon", back_populates="days_off")


class SurgeonDayItem(Base):
    """Surgeon-entered reminders / personal blocks for a calendar day (PWA schedule)."""
    __tablename__ = "surgeon_day_items"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time)
    end_time = Column(Time)
    title = Column(String(255), nullable=False)
    notes = Column(Text)
    sort_order = Column(Integer, default=0, server_default="0")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    surgeon = relationship("Surgeon", back_populates="day_items")


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time)
    end_time = Column(Time)
    location_id = Column(Integer, ForeignKey("locations.id"))
    location_text = Column(String(255))  # free-text if not an Advent Health location
    recurrence_rule = Column(String(64))  # none | weekly | biweekly | monthly
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("admin_users.id"))
    created_at = Column(DateTime, server_default=func.now())

    attendees = relationship("MeetingAttendee", back_populates="meeting", cascade="all, delete-orphan")
    location = relationship("Location")


class MeetingAttendee(Base):
    __tablename__ = "meeting_attendees"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    status = Column(String(16), default="invited")  # invited | confirmed | declined

    meeting = relationship("Meeting", back_populates="attendees")
    surgeon = relationship("Surgeon", back_populates="meeting_attendees")


class ClinicSchedule(Base):
    """Specific-date clinic assignment: which doctor is at which clinic on a given day."""
    __tablename__ = "clinic_schedules"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    date = Column(Date, nullable=False)
    session = Column(String(8), default="full")  # am | pm | full
    assignment_type = Column(String(16), default="assigned", server_default="assigned")  # assigned | off
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon", back_populates="clinic_schedules")
    location = relationship("Location")


class SurgicalCase(Base):
    """One row per surgery (hospital schedule). Scheduler adds; surgeon sees on schedule and can add notes."""
    __tablename__ = "surgical_cases"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time)
    patient_name = Column(String(255), nullable=False)
    patient_dob = Column(String(32))
    patient_phone = Column(String(32))
    procedure = Column(Text, nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"))
    or_block_instance_id = Column(Integer, ForeignKey("or_block_instances.id"))
    room_text = Column(String(64))
    status = Column(String(16), default="scheduled", server_default="scheduled")  # scheduled | confirmed | completed | cancelled
    notes = Column(Text)  # scheduler notes
    surgeon_notes = Column(Text)  # surgeon's own notes (add from mobile)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    surgeon = relationship("Surgeon", back_populates="surgical_cases")
    location = relationship("Location")
    or_block_instance = relationship("ORBlockInstance", back_populates="cases")


class ClinicGroup(Base):
    """Flexible groups for day-off capacity, sorting, and scheduling rules.

    group_type:
      - people: assign physicians and/or staff
      - locations: assign OR/clinic locations
    """
    __tablename__ = "clinic_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True)
    abbreviation = Column(String(12), nullable=False)
    group_type = Column(String(16), default="people", server_default="people", nullable=False)  # people | locations
    enforce_day_off_limit = Column(Boolean, default=False, server_default="false", nullable=False)
    max_approved_off_per_day = Column(Integer, default=1, server_default="1", nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    members = relationship("ClinicGroupMember", back_populates="clinic_group", cascade="all, delete-orphan")
    locations = relationship("ClinicGroupLocation", back_populates="clinic_group", cascade="all, delete-orphan")


class ClinicGroupMember(Base):
    __tablename__ = "clinic_group_members"
    __table_args__ = (UniqueConstraint("clinic_group_id", "surgeon_id"),)
    id = Column(Integer, primary_key=True)
    clinic_group_id = Column(Integer, ForeignKey("clinic_groups.id", ondelete="CASCADE"), nullable=False)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id", ondelete="CASCADE"), nullable=False)

    clinic_group = relationship("ClinicGroup", back_populates="members")
    surgeon = relationship("Surgeon", back_populates="clinic_group_memberships")


class ClinicGroupLocation(Base):
    """Many-to-many: a clinic group can include OR/clinic locations for rules/sorting."""
    __tablename__ = "clinic_group_locations"
    __table_args__ = (UniqueConstraint("clinic_group_id", "location_id"),)
    id = Column(Integer, primary_key=True)
    clinic_group_id = Column(Integer, ForeignKey("clinic_groups.id", ondelete="CASCADE"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False)

    clinic_group = relationship("ClinicGroup", back_populates="locations")
    location = relationship("Location")


class SurgicalBlock(Base):
    __tablename__ = "surgical_blocks"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"))
    day_of_week = Column(Integer)  # 0=Mon ... 6=Sun for weekly blocks
    block_date = Column(Date)  # optional one-day block override
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    recurrence = Column(String(16), default="weekly", server_default="weekly")  # weekly | once
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon", back_populates="surgical_blocks")
    location = relationship("Location")


class ORBlockSeries(Base):
    """Recurring or one-time OR capacity definition; concrete inventory lives on ORBlockInstance."""
    __tablename__ = "or_block_series"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    recurrence = Column(String(16), default="weekly", server_default="weekly")  # weekly | once
    weekday = Column(Integer)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    session = Column(String(16), default="am", server_default="am")  # am | pm | both | custom
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    owner_type = Column(String(16), default="practice", server_default="practice")  # practice | surgeon
    owner_surgeon_id = Column(Integer, ForeignKey("surgeons.id"))
    release_policy_days = Column(Integer, default=3, server_default="3")
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    notes = Column(Text)
    created_by_admin_id = Column(Integer, ForeignKey("admin_users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    owner_surgeon = relationship("Surgeon", foreign_keys=[owner_surgeon_id])
    instances = relationship("ORBlockInstance", back_populates="series", cascade="all, delete-orphan")


class ORBlockInstance(Base):
    """Dated OR capacity for one location/time block."""
    __tablename__ = "or_block_instances"
    id = Column(Integer, primary_key=True)
    series_id = Column(Integer, ForeignKey("or_block_series.id"))
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    date = Column(Date, nullable=False)
    session = Column(String(16), default="am", server_default="am")
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    # OR room within the hospital (e.g. S03 / S08). Blank allowed but flagged immediately.
    # Same day+location+overlapping time+same room (or both blank) = duplicate; different rooms = dual capacity OK.
    room_text = Column(String(64))
    status = Column(String(24), default="open", server_default="open")  # open | assigned
    assigned_surgeon_id = Column(Integer, ForeignKey("surgeons.id"))
    assigned_by_admin_id = Column(Integer, ForeignKey("admin_users.id"))
    assigned_at = Column(DateTime)
    assigned_start_time = Column(Time)
    assigned_case_count = Column(Integer)
    assignment_note = Column(Text)
    release_deadline = Column(DateTime)
    released_at = Column(DateTime)
    released_by_admin_id = Column(Integer, ForeignKey("admin_users.id"))
    release_reason = Column(Text)
    advent_report_status = Column(String(24), default="not_sent", server_default="not_sent")  # not_sent | sent | changed_after_sent
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    series = relationship("ORBlockSeries", back_populates="instances")
    location = relationship("Location")
    assigned_surgeon = relationship("Surgeon", foreign_keys=[assigned_surgeon_id], back_populates="or_block_instances")
    assignments = relationship("ORBlockAssignment", back_populates="block_instance", cascade="all, delete-orphan")
    cases = relationship("SurgicalCase", back_populates="or_block_instance")
    audit_events = relationship("ORBlockAuditEvent", back_populates="block_instance", cascade="all, delete-orphan")


class ORBlockAssignment(Base):
    """Surgeon placement inside a dated OR block capacity row."""
    __tablename__ = "or_block_assignments"
    id = Column(Integer, primary_key=True)
    block_instance_id = Column(Integer, ForeignKey("or_block_instances.id"), nullable=False)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    assigned_by_admin_id = Column(Integer, ForeignKey("admin_users.id"))
    start_time = Column(Time, nullable=False)
    case_count = Column(Integer, default=1, server_default="1")
    note = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    block_instance = relationship("ORBlockInstance", back_populates="assignments")
    surgeon = relationship("Surgeon")
    assigned_by_admin = relationship("AdminUser")


class ORBlockAuditEvent(Base):
    __tablename__ = "or_block_audit_events"
    id = Column(Integer, primary_key=True)
    block_instance_id = Column(Integer, ForeignKey("or_block_instances.id"), nullable=False)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"))
    event_type = Column(String(32), nullable=False)
    detail = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    block_instance = relationship("ORBlockInstance", back_populates="audit_events")
    admin_user = relationship("AdminUser")


class ScheduleChangeEvent(Base):
    """Non-PHI audit stream used for scheduler availability digests."""
    __tablename__ = "schedule_change_events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(64), nullable=False)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"))
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"))
    date = Column(Date)
    title = Column(String(255), nullable=False)
    body = Column(Text)
    payload = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon")
    admin_user = relationship("AdminUser")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("surgeon_devices.id"))
    endpoint = Column(Text, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth_key = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon", back_populates="push_subscriptions")
    device = relationship("SurgeonDevice", back_populates="push_subscriptions")


class NativePushToken(Base):
    __tablename__ = "native_push_tokens"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("surgeon_devices.id"))
    token = Column(Text, nullable=False, unique=True)
    platform = Column(String(32), default="ios")
    provider = Column(String(32), default="expo", server_default="expo")
    device_name = Column(String(128))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    surgeon = relationship("Surgeon", back_populates="native_push_tokens")
    device = relationship("SurgeonDevice")


class NativeScheduleAlert(Base):
    __tablename__ = "native_schedule_alerts"
    id = Column(Integer, primary_key=True)
    surgeon_id = Column(Integer, ForeignKey("surgeons.id"), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    kind = Column(String(64), default="schedule")
    payload = Column(Text)
    read_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    surgeon = relationship("Surgeon", back_populates="native_schedule_alerts")


class AdminNotification(Base):
    __tablename__ = "admin_notifications"
    id = Column(Integer, primary_key=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    kind = Column(String(64), default="schedule")
    payload = Column(Text)
    read_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    admin_user = relationship("AdminUser")


class AprimaCachedAppointment(Base):
    """Snapshot of an Aprima appointment row (patient or meeting). Read-only from Aprima."""
    __tablename__ = "aprima_cached_appointments"
    appointment_id = Column(String(36), primary_key=True)
    kind = Column(String(16), nullable=False, index=True)  # patient | meeting
    date = Column(Date, nullable=False, index=True)
    surgeon_initials = Column(String(16), index=True)
    content_hash = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    synced_at = Column(DateTime, nullable=False, server_default=func.now())


class AprimaSyncState(Base):
    """Singleton-ish sync fingerprint for portal soft-refresh + ops."""
    __tablename__ = "aprima_sync_state"
    id = Column(Integer, primary_key=True)
    last_started_at = Column(DateTime)
    last_finished_at = Column(DateTime)
    last_status = Column(String(32), default="never")  # ok | error | never
    last_error = Column(Text)
    patient_count = Column(Integer, default=0)
    meeting_count = Column(Integer, default=0)
    window_start = Column(Date)
    window_end = Column(Date)
    content_fingerprint = Column(String(64), default="")
