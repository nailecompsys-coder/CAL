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
    status.textContent = message;
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
      controller = new AbortController();
      const owner = select.value;
      setStatus('Loading schedule…');
      host.setAttribute('aria-busy', 'true');
      // Clear previous scope immediately, including when the new result is empty.
      calendar?.removeAllEvents();
      const query = new URLSearchParams({start:info.startStr, end:info.endStr});
      if (owner) query.set('surgeon_id', owner);
      try {
        const response = await fetch(`/api/events?${query}`, {signal:controller.signal, cache:'no-store', headers:{Accept:'application/json'}});
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('feed');
        const events = await response.json();
        if (!Array.isArray(events)) throw new Error('feed');
        if (sequence !== requestNumber) { success([]); return; }
        success(events);
        const count = events.length;
        setStatus(count ? `${count} schedule entries · select an event for details` : 'No scheduled events in this date range.');
      } catch (error) {
        if (sequence !== requestNumber) { success([]); return; }
        failure(error);
        setStatus('Schedule could not load. Retry to see the current schedule.', true);
      } finally {
        if (sequence === requestNumber) host.setAttribute('aria-busy', 'false');
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
      info.el.setAttribute('role', 'button');
      info.el.setAttribute('aria-label', [info.event.extendedProps.surgeon, info.event.title, info.event.extendedProps.count_label].filter(Boolean).join(' · '));
      info.el.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showDetail(info.event); }});
    }
  });
  select.addEventListener('change', () => {
    dialog.close();
    scope.textContent = select.selectedOptions[0].textContent;
    calendar.removeAllEvents();
    saveView();
    calendar.refetchEvents();
  });
  retry.onclick = () => calendar.refetchEvents();
  calendar.render();
  saveView();
})();
