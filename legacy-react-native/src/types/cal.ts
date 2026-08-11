export type CalEvent = {
  id: string;
  title: string;
  start: string;
  end?: string | null;
  color?: string;
  textColor?: string;
  extendedProps?: {
    type?: string;
    location?: string;
    session?: string;
    [key: string]: unknown;
  };
};

export type OtpRequestResponse = {
  ok?: boolean;
  message?: string;
  sent?: boolean;
  devCode?: string;
};

export type OtpVerifyResponse = {
  token: string;
};

export type DayItem = {
  id: number;
  title: string;
  notes?: string | null;
  start?: string | null;
  end?: string | null;
  sortOrder?: number;
};

export type DayItemResponse = {
  ok: boolean;
  item: DayItem;
};

export type NativeScheduleItem = {
  id: string;
  rawId?: number;
  type:
    | "oncall"
    | "dayoff"
    | "meeting"
    | "clinic"
    | "surgery"
    | "personal";
  title: string;
  subtitle?: string;
  start?: string | null;
  end?: string | null;
  allDay?: boolean;
  location?: string;
  room?: string;
  status?: string;
  notes?: string;
  surgeonNotes?: string;
  color?: string;
};

export type NativeDay = {
  date: string;
  dayName: string;
  dayShort: string;
  dayFull: string;
  items: NativeScheduleItem[];
  offSurgeons: {
    initials: string;
    displayName: string;
    isSelf: boolean;
    sortOrder?: number;
    staffType?: string;
  }[];
  requestedOffSurgeons?: {
    initials: string;
    displayName: string;
    isSelf: boolean;
    sortOrder?: number;
    staffType?: string;
  }[];
  callAssignments: {
    rotationId: number;
    groupId?: number | null;
    group: string;
    surgeon: string;
    surgeonId?: number | null;
    initials?: string;
    isSelf: boolean;
    originalSurgeon?: string;
    originalSurgeonId?: number | null;
    originalInitials?: string;
    coveringSurgeon?: string | null;
    coveringSurgeonId?: number | null;
    coveringInitials?: string | null;
    isCovered?: boolean;
    coverageId?: number | null;
  }[];
};

export type NativeAvailabilityDay = {
  date: string;
  dayName: string;
  dayShort: string;
  dayFull: string;
  isAvailable: boolean;
  start?: string | null;
  end?: string | null;
};

export type NativeDayOffRequest = {
  id: number;
  surgeonId?: number;
  surgeonName?: string;
  surgeonInitials?: string;
  surgeonSortOrder?: number;
  startDate: string;
  endDate: string;
  reason: string;
  notes: string;
  adminNote: string;
  status: "pending" | "approved" | "denied";
  isFullDay?: boolean;
  start?: string | null;
  end?: string | null;
  segments?: {
    date: string;
    isFullDay: boolean;
    start?: string | null;
    end?: string | null;
  }[];
};

export type NativeCallDay = {
  date: string;
  dayName: string;
  dayShort: string;
  dayFull: string;
  assignments: {
    rotationId: number;
    groupId?: number | null;
    group: string;
    surgeon: string;
    surgeonId?: number | null;
    initials?: string;
    isSelf: boolean;
    originalSurgeon?: string;
    originalSurgeonId?: number | null;
    originalInitials?: string;
    coveringSurgeon?: string | null;
    coveringSurgeonId?: number | null;
    coveringInitials?: string | null;
    isCovered?: boolean;
    coverageId?: number | null;
  }[];
};

export type NativeScheduleAlert = {
  id: number;
  title: string;
  body: string;
  kind: string;
  payload: Record<string, unknown>;
  isRead: boolean;
  createdAt: string;
};

export type NativeHome = {
  surgeon: {
    id: number;
    name: string;
    staffType: string;
  };
  range: {
    start: string;
    end: string;
  };
  days: NativeDay[];
  availability: NativeAvailabilityDay[];
  requests: NativeDayOffRequest[];
  dayOffSections: {
    header: string;
    isCurrentMonth?: boolean;
    requests: NativeDayOffRequest[];
  }[];
  callSchedule: NativeCallDay[];
  alerts: {
    unreadCount: number;
    recent: NativeScheduleAlert[];
  };
  surgeons: {
    id: number;
    name: string;
    initials: string;
    staffType: string;
    sortOrder?: number;
  }[];
};

export type PatientAppointment = {
  id: string;
  date: string;
  start: string;
  end: string;
  surgeonInitials: string;
  surgeonName: string;
  patientName: string;
  mrn: string;
  appointmentType: string;
  status: string;
  reason: string;
  serviceSite: string;
  room: string;
};

export type NativePatientScheduleResponse = {
  range: {
    start: string;
    end: string;
  };
  appointments: PatientAppointment[];
  warning?: string;
};

export type NativeRequestOffResponse = {
  ok: boolean;
  request: NativeDayOffRequest | null;
  warnings: string[];
};

export type NativeCallCoverageResponse = {
  ok: boolean;
  assignment: NativeDay["callAssignments"][number];
};

export type NativeSaveResponse = {
  ok: boolean;
  warnings?: string[];
};
