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
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="admin")  # admin | superadmin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class SiteSettings(Base):
    __tablename__ = "site_settings"
    id = Column(Integer, primary_key=True)           # always row 1
    practice_name = Column(String(128), default="Mid Florida Surgical")
    logo_filename = Column(String(255))              # e.g. "logo.png" stored in static/uploads/
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
    room_text = Column(String(64))
    status = Column(String(16), default="scheduled", server_default="scheduled")  # scheduled | confirmed | completed | cancelled
    notes = Column(Text)  # scheduler notes
    surgeon_notes = Column(Text)  # surgeon's own notes (add from mobile)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    surgeon = relationship("Surgeon", back_populates="surgical_cases")
    location = relationship("Location")


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
