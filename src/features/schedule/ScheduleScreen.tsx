import { ActivityIndicator, FlatList, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useEffect, useState } from "react";
import DateTimePicker from "@react-native-community/datetimepicker";
import type { NativeDay, NativeDayOffRequest, NativeHome, NativeScheduleAlert, NativeScheduleItem } from "../../types/cal";

type TabKey = "schedule" | "request" | "patients";

type RequestDraft = {
  startDate: string;
  endDate: string;
  reason: string;
  notes: string;
  isFullDay: boolean;
  start: string;
  end: string;
  segments: RequestSegment[];
};

type RequestSegment = {
  date: string;
  isFullDay: boolean;
  start?: string | null;
  end?: string | null;
};

type ScheduleScreenProps = {
  home: NativeHome | null;
  busy: boolean;
  message: string;
  lastSync: string;
  activeTab: TabKey;
  weekOffset: number;
  requestDraft: RequestDraft;
  onTabChange: (tab: TabKey) => void;
  onWeekChange: (weekOffset: number) => void;
  onRequestDraftChange: (draft: RequestDraft) => void;
  onSubmitRequestOff: () => void;
  onUpdateRequestOff: (requestId: number) => void;
  onCancelRequestOff: (requestId: number) => void;
  onSubmitCallCoverage: (rotationId: number, coveringSurgeonId?: number) => void;
  onMarkAlertsRead: () => void;
  onCreateDayItem: (date: string, title: string, notes: string, start?: string | null, end?: string | null) => void;
  onUpdateDayItem: (itemId: number, title: string, notes: string, start?: string | null, end?: string | null) => void;
  onDeleteDayItem: (itemId: number) => void;
};

const tabs: { key: TabKey; label: string; icon: string }[] = [
  { key: "schedule", label: "Schedule", icon: "▦" },
  { key: "request", label: "Days Off", icon: "▲" },
  { key: "patients", label: "Patients", icon: "♟" },
];

export function ScheduleScreen(props: ScheduleScreenProps) {
  const {
    home,
    busy,
    message,
    lastSync,
    activeTab,
    weekOffset,
    requestDraft,
    onTabChange,
    onWeekChange,
    onRequestDraftChange,
    onSubmitRequestOff,
    onUpdateRequestOff,
    onCancelRequestOff,
    onSubmitCallCoverage,
    onMarkAlertsRead,
    onCreateDayItem,
    onUpdateDayItem,
    onDeleteDayItem,
  } = props;
  const [sheetDay, setSheetDay] = useState<NativeDay | null>(null);
  const [coverageRotationId, setCoverageRotationId] = useState<number | null>(null);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const unreadCount = home?.alerts?.unreadCount ?? 0;

  return (
    <View style={styles.shell}>
      <ScrollView style={styles.body} contentContainerStyle={styles.bodyContent}>
        <View style={styles.header}>
          <View>
            <Text style={styles.eyebrow}>{greetingForNow()},</Text>
            <Text style={styles.surgeonName}>{home?.surgeon.name ?? "CAL"}</Text>
            {lastSync ? <Text style={styles.subtle}>Last sync {lastSync}</Text> : null}
          </View>
        </View>

        {busy || importantMessage(message) ? (
          <View style={styles.status}>
            <Text style={styles.statusText}>{busy ? "Loading..." : message}</Text>
          </View>
        ) : null}

        {!home && !busy ? <Text style={styles.empty}>No CAL data loaded yet.</Text> : null}
        {home && activeTab === "schedule" ? (
          <ScheduleTab
            home={home}
            weekOffset={weekOffset}
            onWeekChange={onWeekChange}
            onOpenDay={setSheetDay}
            onCoverCall={setCoverageRotationId}
          />
        ) : null}
        {home && activeTab === "request" ? (
          <RequestOffTab
            home={home}
            draft={requestDraft}
            onDraftChange={onRequestDraftChange}
            onSubmit={onSubmitRequestOff}
            onUpdate={onUpdateRequestOff}
            onCancel={onCancelRequestOff}
            busy={busy}
          />
        ) : null}
        {home && activeTab === "patients" ? <PatientsTab home={home} /> : null}
      </ScrollView>

      <View style={styles.bottomNav}>
        {tabs.map((tab) => (
          <Pressable
            key={tab.key}
            style={styles.navItem}
            onPress={() => {
              if (tab.key === "schedule" && activeTab === "schedule" && unreadCount > 0) {
                setAlertsOpen(true);
                onMarkAlertsRead();
                return;
              }
              onTabChange(tab.key);
            }}
          >
            <View>
              <Text style={[styles.navIcon, activeTab === tab.key && styles.navActive]}>{tab.icon}</Text>
              {tab.key === "schedule" && unreadCount > 0 ? (
                <View style={styles.navBadge}>
                  <Text style={styles.navBadgeText}>{unreadCount > 9 ? "9+" : unreadCount}</Text>
                </View>
              ) : null}
            </View>
            <Text style={[styles.navLabel, activeTab === tab.key && styles.navActive]}>{tab.label}</Text>
          </Pressable>
        ))}
      </View>

      {busy && (
        <View style={styles.loading}>
          <ActivityIndicator />
        </View>
      )}

      {sheetDay ? (
        <DaySheet
          day={sheetDay}
          onClose={() => setSheetDay(null)}
          onCoverCall={(rotationId) => setCoverageRotationId(rotationId)}
          onCreateDayItem={onCreateDayItem}
          onUpdateDayItem={onUpdateDayItem}
          onDeleteDayItem={onDeleteDayItem}
        />
      ) : null}
      {coverageRotationId && home ? (
        <CoverageSheet
          home={home}
          rotationId={coverageRotationId}
          onClose={() => setCoverageRotationId(null)}
          onSave={(surgeonId) => {
            onSubmitCallCoverage(coverageRotationId, surgeonId);
            setCoverageRotationId(null);
          }}
        />
      ) : null}
      {alertsOpen && home ? (
        <AlertsSheet
          alerts={home.alerts?.recent ?? []}
          onClose={() => setAlertsOpen(false)}
        />
      ) : null}
    </View>
  );
}

function AlertsSheet({
  alerts,
  onClose,
}: {
  alerts: NativeScheduleAlert[];
  onClose: () => void;
}) {
  return (
    <Modal animationType="slide" presentationStyle="pageSheet" visible onRequestClose={onClose}>
      <View style={styles.alertSheet}>
        <View style={styles.sheetHandle} />
        <View style={styles.itemHeader}>
          <View>
            <Text style={styles.detailTitle}>Schedule Alerts</Text>
            <Text style={styles.meta}>Recent changes from the portal</Text>
          </View>
          <Pressable onPress={onClose}>
            <Text style={styles.sheetCloseText}>×</Text>
          </Pressable>
        </View>
        {alerts.length === 0 ? <Text style={styles.sheetEmpty}>No schedule alerts yet.</Text> : null}
        <ScrollView contentContainerStyle={styles.alertList}>
          {alerts.map((alert) => (
            <View key={alert.id} style={[styles.alertRow, !alert.isRead && styles.alertRowUnread]}>
              <Text style={styles.alertRowTitle}>{alert.title}</Text>
              <Text style={styles.alertRowBody}>{alert.body}</Text>
              {alert.createdAt ? <Text style={styles.alertRowDate}>{formatDateTime(alert.createdAt)}</Text> : null}
            </View>
          ))}
        </ScrollView>
      </View>
    </Modal>
  );
}

function ScheduleTab({
  home,
  weekOffset,
  onWeekChange,
  onOpenDay,
  onCoverCall,
}: {
  home: NativeHome;
  weekOffset: number;
  onWeekChange: (weekOffset: number) => void;
  onOpenDay: (day: NativeDay) => void;
  onCoverCall: (rotationId: number) => void;
}) {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const todayKey = new Date().toISOString().slice(0, 10);
  const today = home.days.find((day) => day.date === todayKey) ?? home.days.find((day) => day.items.length > 0) ?? home.days[0];
  const selectedDay = home.days.find((day) => day.date === selectedDate) ?? today;
  const heroItem = today ? heroItemForDay(today) : undefined;

  useEffect(() => {
    setSelectedDate(today?.date ?? home.days[0]?.date ?? null);
  }, [home.range.start, home.range.end, today?.date, home.days]);

  return (
    <View>
      <View style={styles.hero}>
        <Text style={styles.heroEyebrow}>TODAY SCHEDULED EVENTS</Text>
        <Text style={styles.heroDate}>{today ? formatDisplayDate(today.date) : "Today"}</Text>
        {heroItem ? (
          <View style={styles.heroEvent}>
            <View style={styles.heroIcon}>
              <Text style={styles.heroIconText}>{labelForType(heroItem.type).slice(0, 1)}</Text>
            </View>
            <View>
              <Text style={styles.heroTitle}>{heroItem.title}</Text>
              <Text style={styles.heroSub}>{heroItem.subtitle || timeLabel(heroItem)}</Text>
            </View>
          </View>
        ) : (
          <Text style={styles.heroSub}>No scheduled events today.</Text>
        )}
      </View>

      <View style={styles.weekHeader}>
        <Pressable style={styles.arrowButton} onPress={() => onWeekChange(weekOffset - 1)}>
          <Text style={styles.arrowButtonText}>‹</Text>
        </Pressable>
        <View>
          <Text style={styles.weekTitle}>This Week</Text>
          <Text style={styles.weekRange}>{formatDisplayDate(home.range.start)} - {formatDisplayDate(home.range.end)}</Text>
        </View>
        <Pressable style={styles.arrowButton} onPress={() => onWeekChange(weekOffset + 1)}>
          <Text style={styles.arrowButtonText}>›</Text>
        </Pressable>
      </View>

      {home.days.slice(0, 7).map((day) => (
        <View key={day.date}>
          <WeekDayCard
            day={day}
            selected={selectedDay?.date === day.date}
            onCoverCall={onCoverCall}
            onPress={() => {
              setSelectedDate(day.date);
              onOpenDay(day);
            }}
          />
        </View>
      ))}
    </View>
  );
}

function WeekDayCard({
  day,
  selected,
  onPress,
  onCoverCall,
}: {
  day: NativeDay;
  selected: boolean;
  onPress: () => void;
  onCoverCall: (rotationId: number) => void;
}) {
  const amItems = day.items.filter((item) => periodForItem(item) === "am");
  const pmItems = day.items.filter((item) => periodForItem(item) === "pm");
  const meetings = day.items.filter((item) => item.type === "meeting");
  const offSurgeons = day.offSurgeons ?? [];
  const callAssignments = day.callAssignments ?? [];

  return (
    <View style={styles.weekRow}>
      <Pressable style={[styles.dayCard, selected && styles.dayCardSelected]} onPress={onPress}>
        <Text style={styles.cardEyebrow}>WHO IS OFF</Text>
        {meetings.length > 0 ? (
          <View style={styles.meetingHeaderPill}>
            <Text style={styles.meetingHeaderEyebrow}>MEETING</Text>
            <Text style={styles.meetingHeaderTitle}>{meetings[0].title}</Text>
            <Text style={styles.meetingHeaderTime}>{timeLabel(meetings[0])}{meetings.length > 1 ? ` +${meetings.length - 1} more` : ""}</Text>
          </View>
        ) : null}
        <View style={styles.chipRow}>
          {offSurgeons.length === 0 ? <Text style={styles.emptyChip}>None</Text> : null}
          {offSurgeons.slice(0, 6).map((surgeon, idx) => (
            <Text key={`${surgeon.displayName}-${surgeon.initials}-${idx}`} style={[styles.chip, surgeon.isSelf && styles.selfChip]}>
              {surgeon.initials}{surgeon.isSelf ? " - you" : ""}
            </Text>
          ))}
        </View>

        <View style={styles.dayContent}>
          <View style={styles.dateColumn}>
            <Text style={styles.dayShort}>{day.dayShort.toUpperCase()}</Text>
            <Text style={styles.dayNum}>{day.date.slice(-2)}</Text>
          </View>
          <View style={styles.periods}>
            <PeriodRow label="AM" items={amItems} />
            <PeriodRow label="PM" items={pmItems} />
          </View>
        </View>
      </Pressable>

      <View style={styles.callRail}>
        {callAssignments.length === 0 ? <Text style={styles.railEmpty}>No call</Text> : null}
        {callAssignments.slice(0, 2).map((assignment, idx) => (
          <Pressable key={`${assignment.group}-${idx}`} style={styles.railCard} onPress={() => onCoverCall(assignment.rotationId)}>
            <Text style={styles.railGroup}>{shortGroup(assignment.group)}</Text>
            {assignment.isCovered ? (
              <Text style={styles.railSurgeon}>
                <Text style={styles.railStruck}>{assignment.originalInitials || "NC"}</Text>
                <Text> {assignment.coveringInitials || assignment.initials || initialsFromName(assignment.surgeon)}</Text>
              </Text>
            ) : (
              <Text style={[styles.railSurgeon, assignment.isSelf && styles.navActive]}>
                {assignment.initials || initialsFromName(assignment.surgeon)}
              </Text>
            )}
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function DaySheet({
  day,
  onClose,
  onCoverCall,
  onCreateDayItem,
  onUpdateDayItem,
  onDeleteDayItem,
}: {
  day: NativeDay;
  onClose: () => void;
  onCoverCall: (rotationId: number) => void;
  onCreateDayItem: (date: string, title: string, notes: string, start?: string | null, end?: string | null) => void;
  onUpdateDayItem: (itemId: number, title: string, notes: string, start?: string | null, end?: string | null) => void;
  onDeleteDayItem: (itemId: number) => void;
}) {
  const [personalEditor, setPersonalEditor] = useState<NativeScheduleItem | null | "new">(null);
  const allDay = day.items.filter((item) => item.allDay);
  const personal = day.items.filter((item) => item.type === "personal");
  const timelineItems = day.items.filter((item) => !item.allDay && item.type !== "personal");

  return (
    <View style={styles.sheet}>
      <View style={styles.sheetHeader}>
        <View>
          <Text style={styles.sheetDayName}>{day.dayName}</Text>
          <Text style={styles.sheetDate}>{formatDisplayDate(day.date)}</Text>
        </View>
        <Pressable style={styles.sheetClose} onPress={onClose}>
          <Text style={styles.sheetCloseText}>×</Text>
        </Pressable>
      </View>

      <ScrollView style={styles.sheetBody} contentContainerStyle={styles.sheetContent}>
        <View style={styles.sheetSectionHeader}>
          <Text style={styles.sheetSectionTitle}>PERSONAL ITEMS</Text>
          <Pressable onPress={() => setPersonalEditor("new")}>
            <Text style={styles.sheetAdd}>+ Add</Text>
          </Pressable>
        </View>
        {personal.length > 0 ? (
          personal.map((item) => (
            <Pressable key={item.id} onPress={() => setPersonalEditor(item)}>
              <SheetBanner item={item} />
            </Pressable>
          ))
        ) : null}

        {day.callAssignments.map((assignment, idx) => (
          <Pressable
            key={`${assignment.group}-${idx}`}
            style={styles.sheetCallCard}
            onPress={() => onCoverCall(assignment.rotationId)}
          >
            <Text style={styles.sheetCallGroup}>{assignment.group}</Text>
            {assignment.isCovered ? (
              <Text style={styles.sheetCallSurgeon}>
                <Text style={styles.struckInitials}>{assignment.originalInitials}</Text>
                <Text>  {assignment.coveringInitials}</Text>
              </Text>
            ) : (
              <Text style={[styles.sheetCallSurgeon, assignment.isSelf && styles.navActive]}>
                {assignment.initials || initialsFromName(assignment.surgeon)}
              </Text>
            )}
            <Text style={styles.sheetCallHint}>Tap to cover this assignment</Text>
          </Pressable>
        ))}

        {allDay.map((item) => (
          <SheetBanner key={item.id} item={item} />
        ))}

        <Timeline items={timelineItems} />
      </ScrollView>
      {personalEditor ? (
        <PersonalItemSheet
          day={day}
          item={personalEditor === "new" ? null : personalEditor}
          onClose={() => setPersonalEditor(null)}
          onSave={(title, notes, start, end) => {
            if (personalEditor === "new") {
              onCreateDayItem(day.date, title, notes, start, end);
            } else if (personalEditor.rawId) {
              onUpdateDayItem(personalEditor.rawId, title, notes, start, end);
            }
            setPersonalEditor(null);
          }}
          onDelete={() => {
            if (personalEditor !== "new" && personalEditor.rawId) {
              onDeleteDayItem(personalEditor.rawId);
            }
            setPersonalEditor(null);
          }}
        />
      ) : null}
    </View>
  );
}

function PersonalItemSheet({
  day,
  item,
  onClose,
  onSave,
  onDelete,
}: {
  day: NativeDay;
  item: NativeScheduleItem | null;
  onClose: () => void;
  onSave: (title: string, notes: string, start?: string | null, end?: string | null) => void;
  onDelete: () => void;
}) {
  const [title, setTitle] = useState(item?.title ?? "");
  const [notes, setNotes] = useState(item?.notes ?? item?.subtitle ?? "");
  const [hasTime, setHasTime] = useState(Boolean(item?.start));
  const [start, setStart] = useState(item?.start ?? "07:00");
  const [end, setEnd] = useState(item?.end ?? "08:00");
  const [picker, setPicker] = useState<"start" | "end" | null>(null);
  const canSave = title.trim().length > 0;

  return (
    <Modal animationType="slide" presentationStyle="pageSheet" visible onRequestClose={onClose}>
      <View style={styles.requestSheet}>
        <View style={styles.sheetHandle} />
        <View style={styles.itemHeader}>
          <View>
            <Text style={styles.detailTitle}>{item ? "Edit Personal Item" : "Add Personal Item"}</Text>
            <Text style={styles.meta}>{formatDisplayDate(day.date)}</Text>
          </View>
          <Pressable onPress={onClose}>
            <Text style={styles.sheetCloseText}>×</Text>
          </Pressable>
        </View>
        <Text style={styles.formLabel}>Title</Text>
        <TextInput style={styles.input} value={title} onChangeText={setTitle} placeholder="Personal item" />
        <Pressable style={styles.toggleRow} onPress={() => setHasTime(!hasTime)}>
          <Text style={styles.itemTitle}>Add time</Text>
          <Text style={styles.statusPill}>{hasTime ? "ON" : "OFF"}</Text>
        </Pressable>
        {hasTime ? (
          <View style={styles.dateButtonRow}>
            <Pressable style={styles.dateButton} onPress={() => setPicker("start")}>
              <Text style={styles.dateButtonLabel}>Starts</Text>
              <Text style={styles.dateButtonValue}>{displayTime(start)}</Text>
            </Pressable>
            <Pressable style={styles.dateButton} onPress={() => setPicker("end")}>
              <Text style={styles.dateButtonLabel}>Ends</Text>
              <Text style={styles.dateButtonValue}>{displayTime(end)}</Text>
            </Pressable>
          </View>
        ) : null}
        <Text style={styles.formLabel}>Notes</Text>
        <TextInput style={[styles.input, styles.textArea]} value={notes} onChangeText={setNotes} placeholder="Optional note" multiline />
        {picker ? (
          <DateTimePicker
            mode="time"
            display="spinner"
            value={timeToDate(picker === "start" ? start : end)}
            onChange={(_, selectedDate) => {
              if (!selectedDate) return;
              if (picker === "start") setStart(timeToString(selectedDate));
              if (picker === "end") setEnd(timeToString(selectedDate));
            }}
          />
        ) : null}
        <Pressable
          style={[styles.primaryButton, !canSave && styles.disabled]}
          disabled={!canSave}
          onPress={() => onSave(title.trim(), notes.trim(), hasTime ? start : null, hasTime ? end : null)}
        >
          <Text style={styles.primaryButtonText}>{item ? "Save Personal Item" : "Add Personal Item"}</Text>
        </Pressable>
        {item ? (
          <Pressable style={styles.cancelDayOffButton} onPress={onDelete}>
            <Text style={styles.cancelDayOffText}>Delete Personal Item</Text>
          </Pressable>
        ) : null}
      </View>
    </Modal>
  );
}

function CoverageSheet({
  home,
  rotationId,
  onClose,
  onSave,
}: {
  home: NativeHome;
  rotationId: number;
  onClose: () => void;
  onSave: (surgeonId: number) => void;
}) {
  const assignment = home.days.flatMap((day) => day.callAssignments).find((row) => row.rotationId === rotationId);
  const originalSurgeonId = assignment?.originalSurgeonId ?? assignment?.surgeonId ?? home.surgeon.id;
  const originalSurgeon = home.surgeons.find((surgeon) => surgeon.id === originalSurgeonId);
  const targetStaffType = originalSurgeon?.staffType ?? home.surgeon.staffType;
  const eligibleSurgeons = home.surgeons.filter((surgeon) => surgeon.staffType === targetStaffType);
  const initialSelectedId = eligibleSurgeons.some((surgeon) => surgeon.id === home.surgeon.id)
    ? home.surgeon.id
    : eligibleSurgeons[0]?.id ?? home.surgeon.id;
  const [selectedId, setSelectedId] = useState(initialSelectedId);
  return (
    <Modal animationType="slide" presentationStyle="pageSheet" visible onRequestClose={onClose}>
      <View style={styles.coverageNativeSheet}>
        <View style={styles.itemHeader}>
          <View>
            <Text style={styles.detailTitle}>Cover On Call</Text>
          </View>
          <Pressable onPress={onClose}>
            <Text style={styles.sheetCloseText}>×</Text>
          </Pressable>
        </View>
        <Text style={styles.meta}>
          {assignment?.group}: {assignment?.originalInitials || assignment?.initials || "NC"} will be covered by:
        </Text>
        <FlatList
          data={eligibleSurgeons}
          style={styles.coverageList}
          contentContainerStyle={styles.coverageListContent}
          keyExtractor={(surgeon) => String(surgeon.id)}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item: surgeon }) => (
              <Pressable
                style={[styles.coverageOption, selectedId === surgeon.id && styles.coverageOptionSelected]}
                onPress={() => setSelectedId(surgeon.id)}
              >
                <Text style={styles.coverageInitials}>{surgeon.initials}</Text>
                <View style={styles.coverageTextBlock}>
                  <Text style={styles.coverageName}>{surgeon.name}</Text>
                  <Text style={styles.coverageRole}>{surgeon.staffType === "physician" ? "Surgeon" : "PA / Staff"}</Text>
                </View>
              </Pressable>
          )}
          showsVerticalScrollIndicator
        />
        <View style={styles.coverageFooter}>
          <Pressable style={styles.primaryButton} onPress={() => onSave(selectedId)}>
            <Text style={styles.primaryButtonText}>Save Coverage</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

function SheetBanner({ item }: { item: NativeScheduleItem }) {
  return (
    <View style={styles.sheetBanner}>
      <Text style={styles.sheetBannerTitle}>{labelForType(item.type)} — {item.title}</Text>
      {item.subtitle ? <Text style={styles.sheetBannerSub}>{item.subtitle}</Text> : null}
    </View>
  );
}

function Timeline({ items }: { items: NativeScheduleItem[] }) {
  const hours = Array.from({ length: 13 }, (_, idx) => 7 + idx);
  return (
    <View style={styles.timelineWrap}>
      {hours.map((hour) => (
        <View key={hour} style={styles.timelineHourRow}>
          <Text style={styles.timelineHour}>{formatHour(hour)}</Text>
          <View style={styles.timelineLine} />
        </View>
      ))}
      <View style={styles.timelineBlocks}>
        {items.map((item) => (
          <View
            key={item.id}
            style={[
              styles.timelineBlock,
              {
                top: timelineTop(item),
                height: timelineHeight(item),
                backgroundColor: item.color || colorForType(item.type),
              },
            ]}
          >
            <Text style={styles.timelineTitle}>{item.title}</Text>
            <Text style={styles.timelineSub}>{timelineSub(item)}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function PeriodRow({ label, items }: { label: string; items: NativeScheduleItem[] }) {
  return (
    <View style={styles.periodRow}>
      <Text style={styles.periodLabel}>{label}</Text>
      <View style={styles.eventPills}>
        {items.length === 0 ? <Text style={styles.dash}>-</Text> : null}
        {items.slice(0, 3).map((item) => (
          <Text key={item.id} style={[styles.schedulePill, { backgroundColor: item.color || colorForType(item.type) }]}>
            {shortTitle(item)}
          </Text>
        ))}
      </View>
    </View>
  );
}

function RequestOffTab({
  home,
  draft,
  onDraftChange,
  onSubmit,
  onUpdate,
  onCancel,
  busy,
}: {
  home: NativeHome;
  draft: RequestDraft;
  onDraftChange: (draft: RequestDraft) => void;
  onSubmit: () => void;
  onUpdate: (requestId: number) => void;
  onCancel: (requestId: number) => void;
  busy: boolean;
}) {
  const [requestOpen, setRequestOpen] = useState(false);
  const [editingRequest, setEditingRequest] = useState<NativeDayOffRequest | null>(null);
  const currentMonthIndex = Math.max(0, home.dayOffSections.findIndex((section) => section.isCurrentMonth));
  const orderedSections = [
    ...home.dayOffSections.slice(currentMonthIndex),
    ...home.dayOffSections.slice(0, currentMonthIndex),
  ];

  function openNewRequest() {
    setEditingRequest(null);
    setRequestOpen(true);
  }

  function handleOwnedRowPress(request: NativeDayOffRequest) {
    if (request.surgeonId !== home.surgeon.id) return;
    onDraftChange(dayOffRequestToDraft(request));
    setEditingRequest(request);
    setRequestOpen(true);
  }

  return (
    <View style={styles.daysOffScreen}>
      <View style={styles.daysOffTopBar}>
        <View>
          <Text style={styles.daysOffTitle}>Days Off</Text>
        </View>
        <Pressable style={styles.requestFabInline} onPress={openNewRequest}>
          <Text style={styles.requestFabText}>+ Request</Text>
        </Pressable>
      </View>

      {orderedSections.map((section, sectionIndex) => (
        <View key={`${section.header}-${sectionIndex}`} style={styles.daysOffSection}>
          <Text style={styles.daysOffHeader}>{section.header}</Text>
          {section.requests.map((request) => (
            <Pressable
              key={request.id}
              onPress={() => handleOwnedRowPress(request)}
              style={[styles.dayOffRow, request.surgeonId === home.surgeon.id && styles.myDayOffRow]}
            >
              <Text style={styles.statusPill}>{request.status === "approved" ? "✓" : "•"}</Text>
              <Text style={styles.dayOffText}>
                {request.surgeonInitials} {compactDateRange(request)}
                {request.notes ? ` · ${request.notes}` : ""}
              </Text>
              {request.surgeonId === home.surgeon.id ? <Text style={styles.youText}>You</Text> : null}
            </Pressable>
          ))}
          {section.requests.length === 0 ? <Text style={styles.emptySmall}>No requests</Text> : null}
        </View>
      ))}

      <Pressable style={styles.requestFab} onPress={openNewRequest}>
        <Text style={styles.requestFabPlus}>+</Text>
      </Pressable>

      <RequestOffSheet
        visible={requestOpen}
        draft={draft}
        busy={busy}
        editingRequest={editingRequest}
        onClose={() => setRequestOpen(false)}
        onDraftChange={onDraftChange}
        onSubmit={() => {
          if (editingRequest) {
            onUpdate(editingRequest.id);
          } else {
            onSubmit();
          }
          setRequestOpen(false);
        }}
        onCancel={() => {
          if (!editingRequest) return;
          onCancel(editingRequest.id);
          setRequestOpen(false);
        }}
      />
    </View>
  );
}

function RequestOffSheet({
  visible,
  draft,
  busy,
  editingRequest,
  onClose,
  onDraftChange,
  onSubmit,
  onCancel,
}: {
  visible: boolean;
  draft: RequestDraft;
  busy: boolean;
  editingRequest: NativeDayOffRequest | null;
  onClose: () => void;
  onDraftChange: (draft: RequestDraft) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const requestTypes = ["Day Off", "No Call", "Vacation", "CME", "Partial Day", "Medical"];
  const selectedType = draft.reason || "Day Off";
  const segments = normalizedRequestSegments(draft);
  const [datePicker, setDatePicker] = useState<"start" | "end" | null>(null);

  function setRequestStartDate(value: Date) {
    const startDate = dateToString(value);
    const endDate = dateStringToDate(draft.endDate) < dateStringToDate(startDate) ? startDate : draft.endDate;
    const next = { ...draft, startDate, endDate };
    onDraftChange({ ...next, segments: normalizedRequestSegments(next) });
  }

  function setRequestEndDate(value: Date) {
    const endDate = dateToString(value);
    const startDate = dateStringToDate(endDate) < dateStringToDate(draft.startDate) ? endDate : draft.startDate;
    const next = { ...draft, startDate, endDate };
    onDraftChange({ ...next, segments: normalizedRequestSegments(next) });
  }

  function addRequestDay() {
    const endDate = addDaysIso(draft.endDate, 1);
    onDraftChange({ ...draft, endDate, segments: normalizedRequestSegments({ ...draft, endDate }) });
  }

  function removeLastRequestDay() {
    if (segments.length <= 1) return;
    const endDate = addDaysIso(draft.endDate, -1);
    onDraftChange({ ...draft, endDate, segments: normalizedRequestSegments({ ...draft, endDate }) });
  }

  function setSegment(date: string, preset: "full" | "am" | "pm") {
    const next = segments.map((segment) => {
      if (segment.date !== date) return segment;
      if (preset === "full") return { ...segment, isFullDay: true, start: "07:00", end: "17:00" };
      if (preset === "am") return { ...segment, isFullDay: false, start: "07:00", end: "12:00" };
      return { ...segment, isFullDay: false, start: "12:00", end: "17:00" };
    });
    onDraftChange({
      ...draft,
      isFullDay: next.every((segment) => segment.isFullDay),
      start: next.find((segment) => !segment.isFullDay)?.start ?? draft.start,
      end: next.find((segment) => !segment.isFullDay)?.end ?? draft.end,
      segments: next,
    });
  }

  return (
    <Modal animationType="slide" presentationStyle="pageSheet" visible={visible} onRequestClose={onClose}>
      <View style={styles.requestSheet}>
        <View style={styles.sheetHandle} />
        <View style={styles.itemHeader}>
          <Text style={styles.detailTitle}>{editingRequest ? "Edit Time Off" : "Request Time Off"}</Text>
          <Pressable onPress={onClose}>
            <Text style={styles.sheetCloseText}>×</Text>
          </Pressable>
        </View>

        <ScrollView style={styles.requestSheetScroll} contentContainerStyle={styles.requestSheetContent} keyboardShouldPersistTaps="handled">
          <Text style={styles.formLabel}>Dates</Text>
          <View style={styles.dateButtonRow}>
            <Pressable
              style={[styles.dateButton, datePicker === "start" && styles.dateButtonActive]}
              onPress={() => setDatePicker(datePicker === "start" ? null : "start")}
            >
              <Text style={styles.dateButtonLabel}>Start Date</Text>
              <Text style={styles.dateButtonValue}>{displayDayOffDate(draft.startDate)}</Text>
            </Pressable>
            <Pressable
              style={[styles.dateButton, datePicker === "end" && styles.dateButtonActive]}
              onPress={() => setDatePicker(datePicker === "end" ? null : "end")}
            >
              <Text style={styles.dateButtonLabel}>End Date</Text>
              <Text style={styles.dateButtonValue}>{displayDayOffDate(draft.endDate)}</Text>
            </Pressable>
          </View>
          {datePicker ? (
            <View style={styles.datePickerPanel}>
              <View style={styles.datePickerHeader}>
                <Text style={styles.datePickerTitle}>{datePicker === "start" ? "Start Date" : "End Date"}</Text>
                <Pressable onPress={() => setDatePicker(null)} hitSlop={10}>
                  <Text style={styles.datePickerDone}>Done</Text>
                </Pressable>
              </View>
              <DateTimePicker
                mode="date"
                display="inline"
                value={dateStringToDate(datePicker === "start" ? draft.startDate : draft.endDate)}
                onChange={(_, selectedDate) => {
                  if (!selectedDate) return;
                  if (datePicker === "start") setRequestStartDate(selectedDate);
                  if (datePicker === "end") setRequestEndDate(selectedDate);
                  setDatePicker(null);
                }}
              />
            </View>
          ) : null}
          {segments.map((segment, idx) => (
            <View key={segment.date} style={styles.segmentRow}>
              <View style={styles.segmentHeader}>
                <View style={styles.segmentDateActions}>
                  <Text style={styles.segmentDate}>{displayDayOffDate(segment.date)}</Text>
                  {idx === 0 ? (
                    <>
                      <Pressable style={styles.inlineDayButton} onPress={addRequestDay}>
                        <Text style={styles.inlineDayButtonText}>+</Text>
                      </Pressable>
                      {segments.length > 1 ? (
                        <Pressable style={styles.inlineDayButton} onPress={removeLastRequestDay}>
                          <Text style={styles.inlineDayButtonText}>-</Text>
                        </Pressable>
                      ) : null}
                    </>
                  ) : null}
                </View>
                <Text style={styles.segmentSummary}>{segment.isFullDay ? "Full day" : `${displayTime(segment.start || "07:00")} - ${displayTime(segment.end || "11:00")}`}</Text>
              </View>
              <View style={styles.segmentChips}>
                {[
                  ["full", "Full"],
                  ["am", "AM"],
                  ["pm", "PM"],
                ].map(([preset, label]) => {
                  const active = preset === "full" ? segment.isFullDay : !segment.isFullDay && segmentPreset(segment) === preset;
                  return (
                    <Pressable key={preset} style={[styles.segmentChip, active && styles.segmentChipActive]} onPress={() => setSegment(segment.date, preset as "full" | "am" | "pm")}>
                      <Text style={[styles.segmentChipText, active && styles.segmentChipTextActive]}>{label}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
          ))}

          <Text style={styles.formLabel}>Type</Text>
          <View style={styles.requestTypeGrid}>
            {requestTypes.map((type) => (
              <Pressable
                key={type}
                style={[styles.requestTypeChip, selectedType === type && styles.requestTypeChipActive]}
                onPress={() => onDraftChange({ ...draft, reason: type })}
              >
                <Text style={[styles.requestTypeText, selectedType === type && styles.requestTypeTextActive]}>{type}</Text>
              </Pressable>
            ))}
          </View>

          <Text style={styles.formLabel}>Notes</Text>
          <TextInput
            style={[styles.input, styles.textArea]}
            value={draft.notes}
            onChangeText={(notes) => onDraftChange({ ...draft, notes })}
            placeholder="Optional note"
            multiline
          />

        </ScrollView>

        <View style={styles.requestSheetFooter}>
          <Pressable style={[styles.primaryButton, busy && styles.disabled]} onPress={onSubmit} disabled={busy}>
            <Text style={styles.primaryButtonText}>{editingRequest ? "Save Changes" : "Submit Request"}</Text>
          </Pressable>
          {editingRequest ? (
            <Pressable style={[styles.cancelDayOffButton, busy && styles.disabled]} onPress={onCancel} disabled={busy}>
              <Text style={styles.cancelDayOffText}>Cancel Days Off And Restore Schedule</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}

function PatientsTab({ home }: { home: NativeHome }) {
  return (
    <View>
      <Text style={styles.sectionTitle}>Today</Text>
      <View style={styles.listCard}>
        <Text style={styles.itemTitle}>{home.patients.today.count} patients</Text>
        {home.patients.today.location ? <Text style={styles.meta}>{home.patients.today.location}</Text> : null}
        {home.patients.today.notes ? <Text style={styles.note}>{home.patients.today.notes}</Text> : null}
      </View>

      <Text style={styles.sectionTitle}>Upcoming</Text>
      {home.patients.upcoming.length === 0 ? <Text style={styles.emptySmall}>No upcoming patient assignments.</Text> : null}
      {home.patients.upcoming.map((row) => (
        <View key={row.date} style={styles.listCard}>
          <Text style={styles.itemTitle}>{formatDisplayDate(row.date)}: {row.count} patients</Text>
          {row.location ? <Text style={styles.meta}>{row.location}</Text> : null}
          {row.notes ? <Text style={styles.note}>{row.notes}</Text> : null}
        </View>
      ))}
    </View>
  );
}

function periodForItem(item: NativeScheduleItem): "am" | "pm" {
  if (item.allDay || !item.start) return "am";
  return Number(item.start.slice(0, 2)) < 12 ? "am" : "pm";
}

function heroItemForDay(day: NativeDay): NativeScheduleItem | undefined {
  return day.items.find((item) => item.type === "meeting")
    ?? day.items.find((item) => item.type === "dayoff")
    ?? day.items[0];
}

function shortTitle(item: NativeScheduleItem): string {
  if (item.type === "dayoff") return "Day off";
  if (item.type === "meeting") return `Mtg: ${item.title.length > 12 ? `${item.title.slice(0, 11)}...` : item.title}`;
  if (item.type === "surgery") return "Surgery";
  if (item.type === "patients") return item.title;
  return item.title.length > 18 ? `${item.title.slice(0, 17)}...` : item.title;
}

function timeLabel(item: NativeScheduleItem): string {
  if (item.allDay) return "All day";
  if (item.start && item.end) return `${item.start} - ${item.end}`;
  return item.start || "No time";
}

function formatDisplayDate(value: string): string {
  const [year, month, day] = value.slice(0, 10).split("-");
  if (!year || !month || !day) return value;
  return `${month}-${day}-${year}`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const yyyy = date.getFullYear();
  return `${mm}-${dd}-${yyyy} ${date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

function greetingForNow(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "GOOD MORNING";
  if (hour < 17) return "GOOD AFTERNOON";
  return "GOOD EVENING";
}

function importantMessage(message: string): boolean {
  const normalized = message.trim().toLowerCase();
  if (!normalized) return false;
  return !["ready", "schedule loaded.", "schedule loaded"].includes(normalized);
}

function labelForType(type: NativeScheduleItem["type"]): string {
  const labels: Record<NativeScheduleItem["type"], string> = {
    oncall: "Call",
    dayoff: "Off",
    meeting: "Meeting",
    patients: "Patients",
    clinic: "Clinic",
    surgery: "Surgery",
    personal: "Personal",
  };
  return labels[type];
}

function colorForType(type: NativeScheduleItem["type"]): string {
  const colors: Record<NativeScheduleItem["type"], string> = {
    oncall: "#f59e0b",
    dayoff: "#dbeafe",
    meeting: "#ddd6fe",
    patients: "#bae6fd",
    clinic: "#f8d9c7",
    surgery: "#fecaca",
    personal: "#e2e8f0",
  };
  return colors[type];
}

function shortGroup(group: string): string {
  return group.split("/").map((part) => part.trim().split(" ").map((word) => word[0]).join("")).slice(0, 3).join(" / ");
}

function initialsFromName(name: string): string {
  if (name === "No call") return "NC";
  return name.split(" ").filter(Boolean).map((part) => part[0]).join("").slice(0, 3).toUpperCase();
}

function compactDateRange(request: NativeDayOffRequest): string {
  const start = displayDayOffDate(request.startDate);
  const end = displayDayOffDate(request.endDate);
  const base = start === end ? start : `${start} - ${end}`;
  const segments = request.segments ?? [];
  const partials = segments.filter((segment) => !segment.isFullDay);
  if (partials.length) {
    return `${base} · ${partials.length} partial`;
  }
  if (request.isFullDay === false && request.start && request.end) {
    return `${base} ${request.start}-${request.end}`;
  }
  return base;
}

function dayOffRequestToDraft(request: NativeDayOffRequest): RequestDraft {
  const segments = request.segments?.map((segment) => ({
    date: segment.date,
    isFullDay: segment.isFullDay,
    start: segment.start || request.start || "07:00",
    end: segment.end || request.end || "11:00",
  })) ?? [];
  const isFullDay = segments.length ? segments.every((segment) => segment.isFullDay) : request.isFullDay !== false;
  return {
    startDate: request.startDate,
    endDate: request.endDate,
    reason: request.reason || "Day Off",
    notes: request.notes || "",
    isFullDay,
    start: request.start || "07:00",
    end: request.end || "11:00",
    segments,
  };
}

function addDaysIso(value: string, days: number): string {
  const date = dateStringToDate(value);
  date.setDate(date.getDate() + days);
  return dateToString(date);
}

function datesBetween(startDate: string, endDate: string): string[] {
  const dates = [];
  let current = dateStringToDate(startDate);
  const end = dateStringToDate(endDate);
  while (current <= end) {
    dates.push(dateToString(current));
    current.setDate(current.getDate() + 1);
  }
  return dates;
}

function normalizedRequestSegments(draft: RequestDraft): RequestSegment[] {
  const existing = new Map(draft.segments.map((segment) => [segment.date, segment]));
  return datesBetween(draft.startDate, draft.endDate).map((date) => {
    const found = existing.get(date);
    if (found) return found;
    return { date, isFullDay: draft.isFullDay, start: draft.start || "07:00", end: draft.end || "11:00" };
  });
}

function segmentPreset(segment: RequestSegment): string {
  const start = segment.start || "";
  const end = segment.end || "";
  if (start === "07:00" && end === "12:00") return "am";
  if (start === "12:00" && end === "17:00") return "pm";
  return "";
}

function dateStringToDate(value: string): Date {
  const [year, month, day] = value.split("-").map((part) => Number(part));
  if (!year || !month || !day) return new Date();
  return new Date(year, month - 1, day);
}

function dateToString(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function timeToDate(value: string): Date {
  const [hour, minute] = value.split(":").map((part) => Number(part));
  const date = new Date();
  date.setHours(Number.isFinite(hour) ? hour : 7, Number.isFinite(minute) ? minute : 0, 0, 0);
  return date;
}

function timeToString(value: Date): string {
  return `${String(value.getHours()).padStart(2, "0")}:${String(value.getMinutes()).padStart(2, "0")}`;
}

function displayDate(value: string): string {
  return formatDisplayDate(value);
}

function displayDayOffDate(value: string): string {
  const [year, month, day] = value.split("-");
  if (!year || !month || !day) return value;
  return `${month}/${day}`;
}

function displayTime(value: string): string {
  return timeToDate(value).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function parseMinutes(value?: string | null): number {
  if (!value) return 8 * 60;
  const [hour, minute] = value.split(":").map((part) => Number(part));
  if (Number.isNaN(hour) || Number.isNaN(minute)) return 8 * 60;
  return hour * 60 + minute;
}

function timelineTop(item: NativeScheduleItem): number {
  const start = Math.max(parseMinutes(item.start), 7 * 60);
  return ((start - 7 * 60) / 60) * 54;
}

function timelineHeight(item: NativeScheduleItem): number {
  const start = parseMinutes(item.start);
  const end = item.end ? parseMinutes(item.end) : start + 60;
  return Math.max(36, ((end - start) / 60) * 54);
}

function formatHour(hour: number): string {
  if (hour === 12) return "12 PM";
  if (hour > 12) return `${hour - 12} PM`;
  return `${hour} AM`;
}

function timelineSub(item: NativeScheduleItem): string {
  const time = timeLabel(item);
  const label = item.subtitle || item.location || "";
  return label ? `${label} ${time}` : time;
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: "#eaf6ff",
    borderRadius: 24,
    overflow: "hidden",
  },
  body: {
    flex: 1,
  },
  bodyContent: {
    padding: 14,
    paddingBottom: 86,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10,
    marginBottom: 14,
    backgroundColor: "#ffffff8f",
    borderColor: "#ffffffcc",
    borderWidth: 1,
    borderRadius: 22,
    padding: 12,
    shadowColor: "#88b7e8",
    shadowOpacity: 0.16,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
  },
  eyebrow: {
    color: "#6f86a4",
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 2,
  },
  surgeonName: {
    color: "#18375f",
    fontSize: 19,
    fontWeight: "800",
    marginTop: 2,
  },
  subtle: {
    color: "#6f86a4",
    fontSize: 11,
    marginTop: 3,
  },
  headerActions: {
    gap: 6,
    alignItems: "flex-end",
  },
  alertButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffffcc",
    borderColor: "#d8e5f3",
    borderWidth: 1,
    shadowColor: "#7aa7d9",
    shadowOpacity: 0.18,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
  },
  alertButtonActive: {
    backgroundColor: "#fff7ed",
    borderColor: "#fdba74",
  },
  alertIcon: {
    color: "#1c66d8",
    fontSize: 18,
    fontWeight: "900",
  },
  alertBadge: {
    position: "absolute",
    right: -4,
    top: -5,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: "#ef4444",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 4,
  },
  alertBadgeText: {
    color: "#fff",
    fontSize: 10,
    fontWeight: "900",
  },
  refreshButton: {
    backgroundColor: "#1c66d8",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  refreshText: {
    color: "#fff",
    fontWeight: "800",
    fontSize: 12,
  },
  logoutButton: {
    backgroundColor: "#fff",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  logoutText: {
    color: "#1c66d8",
    fontWeight: "800",
    fontSize: 12,
  },
  status: {
    backgroundColor: "#ffffffb8",
    borderRadius: 16,
    borderColor: "#ffffffdd",
    borderWidth: 1,
    padding: 10,
    marginBottom: 12,
    shadowColor: "#9cc4ed",
    shadowOpacity: 0.1,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  statusText: {
    color: "#4b6485",
    fontSize: 12,
  },
  hero: {
    backgroundColor: "#145fdb",
    borderRadius: 24,
    padding: 16,
    marginBottom: 16,
    shadowColor: "#145fdb",
    shadowOpacity: 0.28,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
  },
  heroEyebrow: {
    color: "#b9d5ff",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1.8,
  },
  heroDate: {
    color: "#fff",
    fontWeight: "800",
    marginTop: 3,
    marginBottom: 14,
  },
  heroEvent: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  heroIcon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: "#ffffff2a",
    alignItems: "center",
    justifyContent: "center",
  },
  heroIconText: {
    color: "#fff",
    fontWeight: "900",
  },
  heroTitle: {
    color: "#fff",
    fontSize: 17,
    fontWeight: "900",
  },
  heroSub: {
    color: "#d8e7ff",
    fontSize: 12,
    marginTop: 2,
  },
  weekHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 10,
  },
  weekTitle: {
    color: "#18375f",
    fontWeight: "900",
    textAlign: "center",
  },
  weekRange: {
    color: "#6f86a4",
    fontSize: 12,
    textAlign: "center",
  },
  arrowButton: {
    backgroundColor: "#fff",
    borderRadius: 10,
    overflow: "hidden",
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
  },
  arrowButtonText: {
    color: "#6180a5",
    fontSize: 26,
    lineHeight: 30,
    textAlign: "center",
  },
  weekRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 12,
  },
  dayCard: {
    flex: 1,
    backgroundColor: "#ffffffcc",
    borderColor: "#ffffffdd",
    borderWidth: 1,
    borderRadius: 22,
    padding: 12,
    shadowColor: "#8ebcea",
    shadowOpacity: 0.14,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 7 },
  },
  dayCardSelected: {
    borderColor: "#8bc5ff",
    backgroundColor: "#f3f9ffdd",
  },
  cardEyebrow: {
    color: "#7890ad",
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.2,
    marginBottom: 5,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 5,
    marginBottom: 9,
  },
  chip: {
    backgroundColor: "#e8f1fc",
    color: "#244465",
    borderRadius: 7,
    overflow: "hidden",
    paddingHorizontal: 7,
    paddingVertical: 3,
    fontSize: 10,
    fontWeight: "800",
  },
  selfChip: {
    backgroundColor: "#d4ebff",
    color: "#0759b8",
  },
  meetingHeaderPill: {
    backgroundColor: "#145fdb",
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 9,
    marginBottom: 9,
    shadowColor: "#145fdb",
    shadowOpacity: 0.18,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 4 },
  },
  meetingHeaderEyebrow: {
    color: "#b9d5ff",
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 1.2,
  },
  meetingHeaderTitle: {
    color: "#fff",
    fontWeight: "900",
    fontSize: 13,
    marginTop: 2,
  },
  meetingHeaderTime: {
    color: "#d8e7ff",
    fontSize: 11,
    marginTop: 2,
    fontWeight: "700",
  },
  emptyChip: {
    color: "#8aa0bb",
    fontSize: 10,
  },
  dayContent: {
    flexDirection: "row",
    gap: 10,
  },
  dateColumn: {
    width: 36,
    alignItems: "center",
  },
  dayShort: {
    color: "#2f6dc2",
    fontSize: 10,
    fontWeight: "900",
  },
  dayNum: {
    color: "#18375f",
    fontSize: 23,
    fontWeight: "900",
  },
  periods: {
    flex: 1,
    gap: 7,
  },
  periodRow: {
    minHeight: 28,
  },
  periodLabel: {
    color: "#7288a5",
    fontSize: 10,
    fontWeight: "900",
    marginBottom: 3,
  },
  eventPills: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 5,
  },
  schedulePill: {
    color: "#18375f",
    borderRadius: 8,
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontSize: 10,
    fontWeight: "800",
  },
  dash: {
    color: "#adc0d4",
    fontWeight: "900",
  },
  callRail: {
    width: 76,
    gap: 8,
  },
  railCard: {
    backgroundColor: "#f8fbff",
    borderColor: "#d8e5f3",
    borderWidth: 1,
    borderRadius: 12,
    padding: 8,
    minHeight: 60,
    justifyContent: "center",
    alignItems: "center",
  },
  railGroup: {
    color: "#54708f",
    fontSize: 7,
    fontWeight: "900",
    textAlign: "center",
    textTransform: "uppercase",
  },
  railSurgeon: {
    color: "#18375f",
    fontSize: 14,
    fontWeight: "900",
    marginTop: 4,
  },
  railStruck: {
    color: "#dc2626",
    textDecorationLine: "line-through",
  },
  railEmpty: {
    color: "#7890ad",
    fontSize: 10,
    textAlign: "center",
  },
  sheet: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 20,
    backgroundColor: "#f6f9fd",
  },
  sheetHeader: {
    backgroundColor: "#fff",
    borderBottomColor: "#e4ebf4",
    borderBottomWidth: 1,
    paddingHorizontal: 14,
    paddingTop: 16,
    paddingBottom: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  sheetDayName: {
    color: "#18375f",
    fontSize: 18,
    fontWeight: "900",
  },
  sheetDate: {
    color: "#4b6485",
    fontSize: 12,
    marginTop: 2,
  },
  sheetClose: {
    backgroundColor: "#f1f6fb",
    borderRadius: 999,
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
  },
  sheetCloseText: {
    color: "#18375f",
    fontSize: 24,
    lineHeight: 28,
    fontWeight: "600",
  },
  sheetBody: {
    flex: 1,
  },
  sheetContent: {
    paddingBottom: 82,
  },
  sheetSectionHeader: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#f0f5fb",
  },
  sheetSectionTitle: {
    color: "#566f91",
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 1,
  },
  sheetAdd: {
    color: "#006ee6",
    fontSize: 12,
    fontWeight: "900",
  },
  sheetEmpty: {
    color: "#7890ad",
    fontSize: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  alertSheet: {
    flex: 1,
    backgroundColor: "#f7fbff",
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  alertList: {
    paddingBottom: 32,
  },
  alertRow: {
    backgroundColor: "#fff",
    borderColor: "#d8e5f3",
    borderWidth: 1,
    borderRadius: 16,
    padding: 12,
    marginBottom: 10,
    shadowColor: "#8fb8e8",
    shadowOpacity: 0.12,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 5 },
  },
  alertRowUnread: {
    borderColor: "#fdba74",
    backgroundColor: "#fffaf0",
  },
  alertRowTitle: {
    color: "#18375f",
    fontWeight: "900",
    fontSize: 14,
  },
  alertRowBody: {
    color: "#4b6485",
    fontSize: 12,
    marginTop: 4,
  },
  alertRowDate: {
    color: "#7890ad",
    fontSize: 10,
    marginTop: 8,
    fontWeight: "700",
  },
  sheetCallCard: {
    marginHorizontal: 14,
    marginTop: 8,
    borderColor: "#d2deeb",
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
    backgroundColor: "#f8fbff",
  },
  sheetCallGroup: {
    color: "#566f91",
    fontSize: 9,
    fontWeight: "900",
    textTransform: "uppercase",
  },
  sheetCallSurgeon: {
    color: "#18375f",
    fontSize: 14,
    fontWeight: "900",
    marginTop: 4,
  },
  sheetCallHint: {
    color: "#7890ad",
    fontSize: 10,
    marginTop: 4,
  },
  struckInitials: {
    color: "#dc2626",
    textDecorationLine: "line-through",
  },
  modalOverlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 40,
    backgroundColor: "rgba(15,23,42,0.35)",
    justifyContent: "flex-end",
  },
  coverageCard: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    padding: 16,
    height: "82%",
  },
  coverageNativeSheet: {
    flex: 1,
    backgroundColor: "#fff",
    paddingHorizontal: 16,
    paddingTop: 18,
  },
  coverageCount: {
    color: "#7890ad",
    fontSize: 12,
    fontWeight: "700",
    marginTop: 2,
  },
  coverageList: {
    flex: 1,
    marginVertical: 12,
  },
  coverageListContent: {
    paddingBottom: 12,
  },
  coverageFooter: {
    borderTopWidth: 1,
    borderTopColor: "#e2e8f0",
    paddingTop: 12,
    backgroundColor: "#fff",
  },
  coverageOption: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderWidth: 1,
    borderColor: "#e2e8f0",
    borderRadius: 12,
    padding: 10,
    marginBottom: 6,
  },
  coverageOptionSelected: {
    borderColor: "#1c66d8",
    backgroundColor: "#eff6ff",
  },
  coverageInitials: {
    width: 34,
    height: 34,
    borderRadius: 17,
    overflow: "hidden",
    textAlign: "center",
    lineHeight: 34,
    backgroundColor: "#334155",
    color: "#fff",
    fontWeight: "900",
  },
  coverageName: {
    color: "#18375f",
    fontWeight: "800",
  },
  coverageTextBlock: {
    flex: 1,
  },
  coverageRole: {
    color: "#7890ad",
    fontSize: 11,
    fontWeight: "700",
    marginTop: 2,
  },
  sheetBanner: {
    marginHorizontal: 14,
    marginTop: 8,
    borderColor: "#d2deeb",
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
    backgroundColor: "#f8fbff",
  },
  sheetBannerTitle: {
    color: "#36506f",
    fontSize: 13,
    fontWeight: "900",
  },
  sheetBannerSub: {
    color: "#7890ad",
    fontSize: 11,
    marginTop: 2,
  },
  timelineWrap: {
    marginTop: 10,
    marginHorizontal: 14,
    minHeight: 690,
    position: "relative",
  },
  timelineHourRow: {
    height: 54,
    flexDirection: "row",
    alignItems: "flex-start",
  },
  timelineHour: {
    width: 36,
    color: "#7890ad",
    fontSize: 10,
    marginTop: -1,
  },
  timelineLine: {
    flex: 1,
    borderTopColor: "#dfe8f2",
    borderTopWidth: 1,
  },
  timelineBlocks: {
    position: "absolute",
    left: 44,
    right: 0,
    top: 0,
    bottom: 0,
  },
  timelineBlock: {
    position: "absolute",
    left: 0,
    right: 0,
    borderRadius: 10,
    padding: 10,
    opacity: 0.9,
  },
  timelineTitle: {
    color: "#fff",
    fontWeight: "900",
    fontSize: 12,
  },
  timelineSub: {
    color: "#fff",
    fontWeight: "700",
    fontSize: 11,
    marginTop: 2,
  },
  detailPanel: {
    backgroundColor: "#fff",
    borderColor: "#c9dff7",
    borderWidth: 1,
    borderRadius: 14,
    padding: 12,
    marginTop: 2,
    marginBottom: 14,
  },
  detailTitle: {
    color: "#18375f",
    fontWeight: "900",
    fontSize: 16,
    marginBottom: 2,
  },
  detailDate: {
    color: "#6f86a4",
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 10,
  },
  detailItem: {
    borderWidth: 1,
    borderColor: "#e3e9f5",
    borderLeftWidth: 5,
    borderRadius: 10,
    padding: 10,
    marginBottom: 8,
    backgroundColor: "#fbfcff",
  },
  detailSubhead: {
    color: "#18375f",
    fontWeight: "900",
    marginTop: 8,
    marginBottom: 4,
  },
  detailLine: {
    color: "#4b6485",
    fontSize: 12,
    marginTop: 3,
  },
  bottomNav: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: 64,
    backgroundColor: "#fff",
    borderTopColor: "#dbe6f4",
    borderTopWidth: 1,
    flexDirection: "row",
    justifyContent: "space-around",
    alignItems: "center",
  },
  navItem: {
    alignItems: "center",
    flex: 1,
  },
  navIcon: {
    color: "#6f86a4",
    fontSize: 19,
    fontWeight: "900",
  },
  navBadge: {
    position: "absolute",
    right: -14,
    top: -8,
    minWidth: 17,
    height: 17,
    borderRadius: 8.5,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ef4444",
    paddingHorizontal: 4,
  },
  navBadgeText: {
    color: "#fff",
    fontSize: 9,
    fontWeight: "900",
  },
  navLabel: {
    color: "#6f86a4",
    fontSize: 10,
    fontWeight: "800",
  },
  navActive: {
    color: "#006ee6",
  },
  listCard: {
    backgroundColor: "#fff",
    borderRadius: 12,
    borderColor: "#d8e5f3",
    borderWidth: 1,
    padding: 10,
    marginBottom: 8,
  },
  sectionTitle: {
    color: "#18375f",
    fontWeight: "900",
    marginBottom: 8,
  },
  daysOffScreen: {
    paddingBottom: 80,
  },
  daysOffTopBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
  },
  daysOffTitle: {
    color: "#18375f",
    fontSize: 18,
    fontWeight: "900",
  },
  daysOffSubtitle: {
    color: "#7890ad",
    fontSize: 12,
    fontWeight: "700",
    marginTop: 2,
  },
  daysOffHint: {
    color: "#7890ad",
    fontSize: 12,
    fontWeight: "700",
    marginBottom: 10,
  },
  requestFabInline: {
    backgroundColor: "#1c66d8",
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  requestFabText: {
    color: "#fff",
    fontWeight: "900",
    fontSize: 12,
  },
  requestFab: {
    position: "absolute",
    right: 6,
    bottom: 10,
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: "#1c66d8",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#0046c8",
    shadowOpacity: 0.28,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
  },
  requestFabPlus: {
    color: "#fff",
    fontSize: 26,
    fontWeight: "900",
    marginTop: -2,
  },
  requestSheet: {
    flex: 1,
    backgroundColor: "#f7fbff",
    paddingHorizontal: 18,
    paddingTop: 12,
    paddingBottom: 22,
  },
  requestSheetScroll: {
    flex: 1,
  },
  requestSheetContent: {
    paddingBottom: 18,
  },
  requestSheetFooter: {
    borderTopColor: "#dbe6f4",
    borderTopWidth: 1,
    paddingTop: 12,
    backgroundColor: "#f7fbff",
  },
  sheetHandle: {
    alignSelf: "center",
    width: 42,
    height: 5,
    borderRadius: 999,
    backgroundColor: "#cbd5e1",
    marginBottom: 12,
  },
  formLabel: {
    color: "#64748b",
    fontSize: 12,
    fontWeight: "900",
    marginBottom: 6,
    marginTop: 10,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  dateButtonRow: {
    flexDirection: "row",
    gap: 10,
    marginBottom: 10,
  },
  dateButton: {
    flex: 1,
    backgroundColor: "#fff",
    borderColor: "#d3dbea",
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
  },
  dateButtonActive: {
    borderColor: "#1c66d8",
    backgroundColor: "#eaf3ff",
  },
  dateButtonLabel: {
    color: "#7890ad",
    fontSize: 11,
    fontWeight: "800",
    marginBottom: 3,
  },
  dateButtonValue: {
    color: "#18375f",
    fontSize: 15,
    fontWeight: "900",
  },
  datePickerPanel: {
    backgroundColor: "#fff",
    borderColor: "#d3dbea",
    borderWidth: 1,
    borderRadius: 16,
    marginBottom: 12,
    overflow: "hidden",
  },
  datePickerHeader: {
    alignItems: "center",
    borderBottomColor: "#e4eaf3",
    borderBottomWidth: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  datePickerTitle: {
    color: "#18375f",
    fontSize: 13,
    fontWeight: "900",
  },
  datePickerDone: {
    color: "#1c66d8",
    fontSize: 13,
    fontWeight: "900",
  },
  requestTypeGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 8,
  },
  requestTypeChip: {
    width: "31%",
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#d3dbea",
    backgroundColor: "#fff",
  },
  requestTypeChipActive: {
    borderColor: "#1c66d8",
    backgroundColor: "#eaf3ff",
  },
  requestTypeText: {
    color: "#52677f",
    fontSize: 12,
    fontWeight: "800",
    textAlign: "center",
  },
  requestTypeTextActive: {
    color: "#075ec7",
  },
  sectionHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 10,
    marginBottom: 8,
  },
  dayCountControls: {
    flexDirection: "row",
    gap: 8,
  },
  dayCountButton: {
    width: 38,
    height: 34,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#eaf3ff",
    borderColor: "#cfe0ff",
    borderWidth: 1,
  },
  dayCountButtonText: {
    color: "#075ec7",
    fontSize: 20,
    fontWeight: "900",
  },
  rangeStepperRow: {
    gap: 10,
    marginBottom: 12,
  },
  rangeStepper: {
    backgroundColor: "#fff",
    borderColor: "#d3dbea",
    borderWidth: 1,
    borderRadius: 14,
    padding: 12,
  },
  stepperControls: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  stepperButton: {
    width: 38,
    height: 34,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#eaf3ff",
    borderColor: "#cfe0ff",
    borderWidth: 1,
  },
  stepperText: {
    color: "#075ec7",
    fontSize: 20,
    fontWeight: "900",
  },
  segmentRow: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#d3dbea",
    borderRadius: 16,
    padding: 12,
    marginBottom: 10,
  },
  segmentHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  segmentDate: {
    color: "#173760",
    fontSize: 14,
    fontWeight: "900",
  },
  segmentDateActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  inlineDayButton: {
    width: 30,
    height: 28,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#eaf3ff",
    borderColor: "#cfe0ff",
    borderWidth: 1,
  },
  inlineDayButtonText: {
    color: "#075ec7",
    fontSize: 17,
    fontWeight: "900",
  },
  segmentSummary: {
    color: "#52677f",
    fontSize: 12,
    fontWeight: "800",
  },
  segmentChips: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 7,
  },
  segmentChip: {
    paddingHorizontal: 11,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: "#d3dbea",
    backgroundColor: "#f8fbff",
  },
  segmentChipActive: {
    backgroundColor: "#1c66d8",
    borderColor: "#1c66d8",
  },
  segmentChipText: {
    color: "#52677f",
    fontSize: 12,
    fontWeight: "900",
  },
  segmentChipTextActive: {
    color: "#fff",
  },
  input: {
    borderWidth: 1,
    borderColor: "#d3dbea",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    backgroundColor: "#fff",
    marginBottom: 8,
  },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: "#d3dbea",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    backgroundColor: "#fff",
    marginBottom: 8,
  },
  textArea: {
    minHeight: 78,
    textAlignVertical: "top",
  },
  primaryButton: {
    backgroundColor: "#1c66d8",
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: "center",
  },
  primaryButtonText: {
    color: "#fff",
    fontWeight: "900",
  },
  disabled: {
    opacity: 0.6,
  },
  itemHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 8,
  },
  itemTitle: {
    color: "#18375f",
    fontWeight: "900",
    flex: 1,
  },
  statusPill: {
    backgroundColor: "#e8f1fc",
    color: "#244465",
    borderRadius: 8,
    overflow: "hidden",
    paddingHorizontal: 7,
    paddingVertical: 3,
    fontSize: 10,
    fontWeight: "900",
    textTransform: "uppercase",
  },
  meta: {
    color: "#4b6485",
    fontSize: 12,
    marginTop: 3,
  },
  note: {
    color: "#667a98",
    fontSize: 12,
    marginTop: 6,
  },
  empty: {
    color: "#6c7e9a",
    textAlign: "center",
    marginTop: 24,
  },
  emptySmall: {
    color: "#7890ad",
    fontSize: 12,
    marginBottom: 8,
  },
  daysOffSection: {
    backgroundColor: "#fff",
    borderColor: "#d8e5f3",
    borderWidth: 1,
    borderRadius: 14,
    overflow: "hidden",
    marginBottom: 10,
  },
  daysOffHeader: {
    backgroundColor: "#f0f5fb",
    color: "#566f91",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 1,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  dayOffRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderTopColor: "#eef2f7",
    borderTopWidth: 1,
  },
  myDayOffRow: {
    backgroundColor: "#ecf7ff",
    borderLeftColor: "#9bd0ff",
    borderLeftWidth: 4,
  },
  dayOffText: {
    flex: 1,
    color: "#334155",
    fontSize: 13,
    fontWeight: "700",
  },
  youText: {
    color: "#2563eb",
    fontSize: 10,
    fontWeight: "900",
    textTransform: "uppercase",
  },
  loading: {
    position: "absolute",
    right: 16,
    bottom: 76,
    backgroundColor: "#fff",
    borderRadius: 999,
    padding: 8,
  },
  cancelDayOffButton: {
    borderColor: "#fecaca",
    borderWidth: 1,
    borderRadius: 14,
    paddingVertical: 12,
    alignItems: "center",
    backgroundColor: "#fff5f5",
    marginTop: 10,
  },
  cancelDayOffText: {
    color: "#b91c1c",
    fontWeight: "900",
    fontSize: 12,
  },
});
