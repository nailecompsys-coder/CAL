/* Master calendar: one server-scoped feed, no hidden or hand-painted events. */
(() => {
  'use strict';
  const root = document.querySelector('.master-calendar');
  const host = document.getElementById('master-calendar');
  const select = document.getElementById('calendar-surgeon');
  const status = document.getElementById('calendar-status');
  const scope = document.getElementById('calendar-scope');
  const retry = document.getElementById('calendar-retry');
  const dialog = document.getElementById('calendar-detail');
  const params = new URLSearchParams(location.search);
  const requested = params.get('surgeon_id');
  if ([...select.options].some(option => option.value === requested)) select.value = requested;
  scope.textContent = select.selectedOptions[0].textContent;
  const setStatus = (message, error = false) => {
    if (status.textContent !== message) status.textContent = message;
    status.classList.toggle('is-error', error);
    retry.hidden = !error;
  };
  if (!window.FullCalendar) {
    setStatus('Calendar could not load. Please reload the page.', true);
    retry.onclick = () => location.reload();
    return;
  }
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const formatTime = raw => {
    if (!raw) return '';
    const [hour, minute] = raw.split(':');
    return `${Number(hour) % 12 || 12}:${minute} ${Number(hour) >= 12 ? 'PM' : 'AM'}`;
  };
  const types = {block: 'Master block', clinic: 'Clinic / OR', surgery:'OR case', oncall:'Call', dayoff:'Time off', meeting:'Meeting', personal:'Personal schedule', unavailable:'Unavailable'};
  function showDetail(event) {
    const props = event.extendedProps;
    document.getElementById('calendar-detail-title').textContent = event.title;
    document.getElementById('calendar-detail-kind').textContent = types[props.type] || 'Schedule';
    const body = document.getElementById('calendar-detail-body');
    body.replaceChildren();
    const detail = (label, value) => {
      if (!value) return;
      const row = node('div', null, 'calendar-detail-row');
      row.append(node('span', label, 'calendar-detail-label'), node('span', value, 'calendar-detail-value'));
      body.append(row);
    };
    detail('Date', event.start?.toLocaleDateString(undefined, {weekday:'long', month:'long',day:'numeric', year:'numeric'}));
    detail('Clinician', props.surgeon || (props.practice_wide ? 'Practice-wide meeting' : 'Invited clinicians'));
    detail('Time', props.session ? props.session.toUpperCase() : event.allDay ? 'All day' : `${event.start.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}${event.end ? ' – ' + event.end.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}) : ''}`);
    detail('Location', props.location || props.call_group);
    detail('Status', props.status);
    detail('Reason', props.reason);
    detail('Notes', props.notes || props.message);
    detail('Procedure', props.procedure);
    detail('Patient', props.patient_name);
    detail('Source', props.source);
    if (props.is_covered) detail('Coverage', `${props.covering_surgeon} covering for ${props.original_surgeon}`);
    if (props.has_conflict) body.append(node('p', props.conflict_reasons.join(' · '), 'calendar-warning'));
    if (props.roster?.length) {
      detail('Activity', props.count_label);
      props.roster.forEach(item => {
        const row = node('div', null, 'calendar-roster');
        row.append(node('strong', [formatTime(item.time), item.patient].filter(Boolean).join(' · ')),
                   node('p', item.procedure), node('small', [item.role, item.location, item.room, item.source].filter(Boolean).join(' · ')));
        body.append(row);
      });
    }
    dialog.showModal();
  }
  document.getElementById('calendar-detail-close').onclick = () => dialog.close();
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }});
  let requestNumber = 0;
  let controller;
  let calendar;
  let currentRange;
  let loadedScope;
  let snapshot = new Map();
  let foregroundLoading = false;
  let backgroundController;
  let lastCheck = 0;
  let stopped = false;
  const refreshInterval = 60000;
  const scopeKey = (info, owner) => `${info.startStr}|${info.endStr}|${owner}`;
  const summarize = count => setStatus(count ? `${count} schedule entries · select an event for details` : 'No scheduled events in this date range.');
  const remember = events => new Map(events.map(event => [String(event.id), JSON.stringify(event)]));
  async function readEvents(info, owner, signal) {
    const query = new URLSearchParams({start:info.startStr, end:info.endStr});
    if (owner) query.set('surgeon_id', owner);
    const response = await fetch(`/api/events?${query}`, {signal, cache:'no-store', headers:{Accept:'application/json'}});
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('feed');
    const events = await response.json();
    if (!Array.isArray(events)) throw new Error('feed');
    return events;
  }
  function detailOpen() {
    return dialog.open || !!host.querySelector('.fc-popover');
  }
  async function refreshQuietly(force = false) {
    if (stopped || document.hidden || foregroundLoading || backgroundController || !loadedScope || detailOpen()) return;
    if (!force && Date.now() - lastCheck < refreshInterval) return;
    const expectedScope = loadedScope;
    const sequence = requestNumber;
    const request = new AbortController();
    backgroundController = request;
    lastCheck = Date.now();
    try {
      const events = await readEvents(currentRange, select.value, request.signal);
      if (stopped || request.signal.aborted || sequence !== requestNumber || loadedScope !== expectedScope) return;
      // Do not disturb a detail panel or focused event opened during the request.
      if (detailOpen()) { lastCheck = 0; return; }
      const next = remember(events);
      const changed = events.filter(event => next.get(String(event.id)) !== snapshot.get(String(event.id)));
      const removed = [...snapshot.keys()].filter(id => !next.has(id));
      if (changed.length || removed.length) {
        const main = document.querySelector('main');
        const scrollTop = main?.scrollTop;
        const focused = host.contains(document.activeElement) ? document.activeElement?.closest('.fc-event') : null;
        const focusedId = focused?.dataset.calendarEventId;
        const source = calendar.getEventSources()[0];
        calendar.batchRendering(() => {
          removed.forEach(id => calendar.getEventById(id)?.remove());
          changed.forEach(event => {
            calendar.getEventById(String(event.id))?.remove();
            calendar.addEvent(event, source);
          });
        });
        if (focusedId && !focused.isConnected) {
          const replacement = [...host.querySelectorAll('[data-calendar-event-id]')].find(el => el.dataset.calendarEventId === focusedId);
          if (replacement) replacement.focus({preventScroll:true});
          else { host.setAttribute('tabindex', '-1'); host.focus({preventScroll:true}); }
        }
        if (main && scrollTop !== undefined) main.scrollTop = scrollTop;
        snapshot = next;
      }
      summarize(events.length);
    } catch (error) {
      if (sequence !== requestNumber || stopped || request.signal.aborted) return;
      setStatus('Update delayed. Showing the last loaded schedule.', true);
    } finally {
      if (backgroundController === request) backgroundController = null;
    }
  }
  const views = ['dayGridMonth', 'listWeek', 'listDay'];
  const dateParam = params.get('date');
  function saveView() {
    const url = new URL(location.href);
    if (select.value) url.searchParams.set('surgeon_id', select.value); else url.searchParams.delete('surgeon_id');
    url.searchParams.set('view', calendar.view.type);
    const day = calendar.getDate();
    url.searchParams.set('date', `${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,'0')}-${String(day.getDate()).padStart(2,'0')}`);
    history.replaceState(null, '', url);
  }
  calendar = new FullCalendar.Calendar(host, {
    initialView: views.includes(params.get('view')) ? params.get('view') : matchMedia('(max-width:600px)').matches ? 'listWeek' : 'dayGridMonth',
    initialDate: /^\d{4}-\d{2}-\d{2}$/.test(dateParam || '') ? dateParam : root.dataset.today,
    headerToolbar: {left:'prev,next today', center:'title', right:'dayGridMonth,listWeek,listDay'},
    buttonText: {today:'Today', dayGridMonth:'Month', listWeek:'Week', listDay:'Day'},
    lazyFetching:false, height:'auto', fixedWeekCount:false, dayMaxEvents:4, eventDisplay:'block',
    eventOrder:'sort_key,start,title', eventOrderStrict:true, now:root.dataset.today,
    noEventsContent:'No scheduled events for this view.', navLinks:true,
    listDayFormat:{weekday:'long',month:'short',day:'numeric'}, listDaySideFormat:false,
    navLinkDayClick: date => calendar.changeView('listDay', date),
    datesSet: () => { if (calendar) saveView(); },
    events: async (info, success, failure) => {
      const sequence = ++requestNumber;
      controller?.abort();
      backgroundController?.abort();
      backgroundController = null;
      controller = new AbortController();
      const owner = select.value;
      const requestedScope = scopeKey(info, owner);
      currentRange = info;
      foregroundLoading = true;
      setStatus('Loading schedule…');
      host.setAttribute('aria-busy', 'true');
      // Only a user-selected scope change clears the previous doctor's records.
      if (requestedScope !== loadedScope) {
        loadedScope = null;
        snapshot = new Map();
        calendar?.removeAllEvents();
      }
      try {
        const events = await readEvents(info, owner, controller.signal);
        if (sequence !== requestNumber) { success([]); return; }
        success(events);
        loadedScope = requestedScope;
        snapshot = remember(events);
        lastCheck = Date.now();
        summarize(events.length);
      } catch (error) {
        if (sequence !== requestNumber) { success([]); return; }
        failure(error);
        setStatus('Schedule could not load. Retry to see the current schedule.', true);
      } finally {
        if (sequence === requestNumber) {
          foregroundLoading = false;
          host.setAttribute('aria-busy', 'false');
        }
      }
    },
    eventClassNames: info => [`event-${info.event.extendedProps.type}`, ...(info.event.extendedProps.has_conflict ? ['event-conflict'] : [])],
    eventContent: info => {
      const event = info.event, props = event.extendedProps;
      const wrapper = node('div');
      const owner = !select.value && props.surgeon ? `${props.initials || props.surgeon} · ` : '';
      const clock = !event.allDay && info.timeText ? `${info.timeText} · ` : '';
      wrapper.append(node('span', `${props.has_conflict ? '⚠ ' : ''}${owner}${clock}${event.title}`, 'calendar-event-line'));
      if (props.count_label || props.has_conflict) wrapper.append(node('span', [props.count_label, props.has_conflict ? 'Review conflict' : ''].filter(Boolean).join(' · '), 'calendar-event-line calendar-event-note'));
      return {domNodes:[wrapper]};
    },
    eventClick: info => { info.jsEvent.preventDefault(); showDetail(info.event); },
    eventDidMount: info => {
      const timeCell = info.el.querySelector('.fc-list-event-time');
      if (timeCell && info.event.extendedProps.session) timeCell.textContent = info.event.extendedProps.session.toUpperCase();
      info.el.setAttribute('tabindex', '0');
      info.el.dataset.calendarEventId = info.event.id;
      info.el.setAttribute('role', 'button');
      info.el.setAttribute('aria-label', [info.event.extendedProps.surgeon, info.event.title, info.event.extendedProps.count_label].filter(Boolean).join(' · '));
      info.el.title = info.el.getAttribute('aria-label');
      info.el.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showDetail(info.event); }});
    }
  });
  select.addEventListener('change', () => {
    dialog.close();
    scope.textContent = select.selectedOptions[0].textContent;
    loadedScope = null;
    saveView();
    calendar.refetchEvents();
  });
  retry.onclick = () => loadedScope ? refreshQuietly(true) : calendar.refetchEvents();
  calendar.render();
  saveView();
  let timer = setInterval(refreshQuietly, refreshInterval);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshQuietly();
  });
  dialog.addEventListener('close', () => refreshQuietly());
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearInterval(timer);
    controller?.abort();
    backgroundController?.abort();
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    stopped = false;
    backgroundController = null;
    timer = setInterval(refreshQuietly, refreshInterval);
    refreshQuietly(true);
  });
})();
