/**
 * Cal-BOT — in-app scheduling assistant for the CAL admin portal.
 *
 * Purple circular face with orbiting ring. Pupils track the mouse cursor
 * and scan the schedule grid in idle. Surfaces OFF-conflict insight bubbles
 * with concrete fix links. Quiet on a clean week.
 *
 * No React. No build step. Jinja2 + plain JS only.
 * Uses Clinical Trust CSS tokens from input.css :root.
 */
(function () {
  'use strict';

  // ─── Pages where Cal-BOT appears ─────────────────────────────────────────
  var RELEVANT_PATHS = [
    '/admin/dashboard',
    '/admin/calendar',
    '/admin/clinic-schedule',
    '/admin/call-schedule',
    '/admin/call-audit',
    '/admin/block-or',
    '/admin/notifications',
    '/admin/daysoff',
  ];

  var SEEN_KEY    = 'cal-seen-v1';
  var MAX_SEEN    = 200;
  var IDLE_MS     = 2800;    // ms still before idle grid-scan kicks in
  var MAX_OFFSET  = 2.2;     // max pupil translation in SVG units (face is 64×64)

  var idleTimer = null;
  var isIdle    = true;
  var pulseTO   = null;

  // ─── Bootstrap ────────────────────────────────────────────────────────────
  function init() {
    var path = window.location.pathname;
    var relevant = RELEVANT_PATHS.some(function (p) {
      return path === p || path.indexOf(p + '?') === 0 || path.indexOf(p + '/') === 0;
    });
    if (!relevant) return;

    injectStyles();
    document.body.appendChild(buildWidget());
    bindEvents();
    setTimeout(fetchConflicts, 900);
  }

  // ─── Styles ───────────────────────────────────────────────────────────────
  function injectStyles() {
    var s = document.createElement('style');
    s.id = 'cal-bot-styles';
    s.textContent = [
      /* ── Widget shell ── */
      '#cal-assist{',
      '  position:fixed;bottom:1.25rem;right:1.25rem;',
      '  z-index:9999;display:flex;flex-direction:column;',
      '  align-items:flex-end;gap:.5rem;pointer-events:none;',
      '}',

      /* ── Face button ── */
      '#cal-btn{',
      '  width:64px;height:64px;',
      '  background:none;border:none;padding:0;',
      '  cursor:pointer;pointer-events:all;border-radius:50%;display:block;',
      '  filter:drop-shadow(0 2px 10px rgba(109,40,217,.22));',
      '  transition:filter .2s,transform .2s;',
      '}',
      '#cal-btn:hover{filter:drop-shadow(0 4px 18px rgba(109,40,217,.44));}',
      '#cal-svg{width:64px;height:64px;display:block;overflow:visible;}',

      /* ── SVG face elements — CSS vars from input.css :root ── */
      '.cal-face{',
      '  fill:var(--cal-purple-soft,#ede9fe);',
      '  stroke:var(--cal-purple,#6d28d9);stroke-width:2;',
      '}',
      /* Subtle radial highlight — liquid-glass feel */
      '.cal-face-shine{fill:white;opacity:.09;}',
      '.cal-brow{',
      '  fill:none;stroke:var(--cal-purple,#6d28d9);',
      '  stroke-width:1.4;stroke-linecap:round;opacity:.38;',
      '}',
      '.cal-eye-white{fill:#fff;stroke:var(--cal-stroke,rgba(180,196,220,.55));stroke-width:.8;}',
      '.cal-iris{fill:var(--cal-purple,#6d28d9);}',
      '.cal-glint{fill:#fff;opacity:.78;}',
      '.cal-mouth{',
      '  fill:none;stroke:var(--cal-purple-mid,#8b5cf6);',
      '  stroke-width:1.5;stroke-linecap:round;opacity:.45;',
      '}',

      /* ── Orbit ring ──
         transform-box:view-box + transform-origin:50% 50% anchors rotation
         to the SVG viewport center (32,32) — avoids the bounding-box offset
         that would cause a wobble. */
      '.cal-orbit{',
      '  transform-box:view-box;transform-origin:50% 50%;',
      '  animation:cal-orbit-spin 13s linear infinite;',
      '}',
      '.cal-orbit-ring{',
      '  stroke:var(--cal-purple-mid,#8b5cf6);',
      '  stroke-width:1.5;stroke-dasharray:3 9;opacity:.42;',
      '}',
      '.cal-orbit-dot{fill:var(--cal-purple-mid,#8b5cf6);opacity:.65;}',
      '@keyframes cal-orbit-spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}',

      /* ── Pupils — smooth JS-driven tracking ── */
      '.cal-pupil-group{',
      '  transition:transform .11s ease-out;',
      '}',

      /* ── Idle grid-scan ──
         Simulates reading a schedule grid left-to-right, row by row.
         Per-keyframe animation-timing-function: linear for the sweep,
         steps(1) for the instant snap back to the start of the next row.
         Class toggled by JS; clearing style.transform returns control to CSS. */
      '.cal-pupil-group.cal-idle{',
      '  transition:none;',
      '  animation:cal-grid-scan 9s ease-in-out infinite;',
      '}',

      /* Three row-sweeps then a brief center rest.
         Row 1: upper-left → upper-right  (linear sweep)
         snap back → Row 2: mid-left → mid-right
         snap back → Row 3: lower-left → lower-right
         snap back → center rest → restart */
      '@keyframes cal-grid-scan{',
      '  /* Row 1 sweep */             ',
      '  0%  { transform:translate(-2px,-1.4px); animation-timing-function:linear; }',
      '  16% { transform:translate( 2px,-1.4px); animation-timing-function:steps(1,end); }',
      '  /* Row 2 sweep */             ',
      '  17% { transform:translate(-2px,  .1px); animation-timing-function:linear; }',
      '  33% { transform:translate( 2px,  .1px); animation-timing-function:steps(1,end); }',
      '  /* Row 3 sweep */             ',
      '  34% { transform:translate(-2px, 1.5px); animation-timing-function:linear; }',
      '  50% { transform:translate( 2px, 1.5px); animation-timing-function:steps(1,end); }',
      '  /* Center rest */             ',
      '  51% { transform:translate(0,0); }',
      '  85% { transform:translate(0,0); }',
      '  /* Pre-loop jump back to row-1 start */  ',
      '  86% { transform:translate(-2px,-1.4px); }',
      ' 100% { transform:translate(-2px,-1.4px); }',
      '}',

      /* ── Click pulse ── */
      '#cal-btn.cal-pulse{animation:cal-pulse-anim .28s ease-out;}',
      '@keyframes cal-pulse-anim{',
      '  0%{transform:scale(1)} 50%{transform:scale(1.13)} 100%{transform:scale(1)}',
      '}',

      /* ── Speech bubble ── */
      '#cal-bubble{',
      '  max-width:15.5rem;',
      '  background:var(--cal-mist,#f4f6fa);',
      '  border:1.5px solid rgba(109,40,217,.28);',
      '  border-radius:.9rem;',
      '  padding:.75rem .875rem;',
      '  box-shadow:0 4px 22px rgba(109,40,217,.13),0 1px 4px rgba(28,36,48,.07);',
      '  pointer-events:none;',          /* disabled until .cal-visible */
      '  font-size:.8125rem;line-height:1.5;',
      '  color:var(--cal-ink,#1c2430);',
      /* Fade-in transition — toggled via .cal-visible */
      '  opacity:0;transform:translateY(6px);',
      '  transition:opacity .22s ease-out,transform .22s ease-out;',
      '}',
      '#cal-bubble.cal-visible{opacity:1;transform:translateY(0);pointer-events:all;}',

      /* Bubble internals */
      '.cal-bubble-top{display:flex;align-items:center;gap:.4rem;margin-bottom:.4rem;}',
      '.cal-bot-name{',
      '  font-size:.68rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;',
      '  color:var(--cal-purple,#6d28d9);margin-right:auto;',
      '}',
      '.cal-badge{',
      '  font-size:.68rem;font-weight:700;padding:2px 8px;',
      '  border-radius:9999px;flex-shrink:0;letter-spacing:.01em;',
      '}',
      '.cal-badge-approved{background:#dcfce7;color:#166534;}',
      '.cal-badge-pending{background:var(--cal-amber,#ffe8c2);color:#92400e;}',
      '.cal-x{',
      '  background:none;border:none;cursor:pointer;',
      '  font-size:1.2rem;line-height:1;',
      '  color:var(--cal-muted,#6b7a8d);padding:0 3px;opacity:.65;',
      '  transition:opacity .15s;flex-shrink:0;',
      '}',
      '.cal-x:hover{opacity:1;}',
      '.cal-msg{margin:0 0 .45rem;font-weight:500;}',
      '.cal-more{color:var(--cal-muted,#6b7a8d);font-weight:400;font-size:.75rem;}',
      '.cal-actions{display:flex;flex-direction:column;gap:.28rem;margin-top:.35rem;}',
      '.cal-link{',
      '  color:var(--cal-purple-mid,#8b5cf6);font-weight:600;',
      '  text-decoration:none;font-size:.78rem;',
      '}',
      '.cal-link:hover{text-decoration:underline;}',
    ].join('\n');
    document.head.appendChild(s);
  }

  // ─── Widget DOM ───────────────────────────────────────────────────────────
  function buildWidget() {
    var div = document.createElement('div');
    div.id = 'cal-assist';
    // Bubble starts invisible (no hidden attr; CSS handles opacity:0 / .cal-visible)
    div.innerHTML =
      '<div id="cal-bubble"></div>' +
      '<button id="cal-btn" aria-label="Cal-BOT" type="button">' +
      buildFaceSVG() +
      '</button>';
    return div;
  }

  function buildFaceSVG() {
    // viewBox 64×64; face at (32,32) r=22; orbit ring r=30
    // Eyes at (23,29) left and (41,29) right; mouth curves below.
    return (
      '<svg id="cal-svg" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +

        /* Orbiting ring — single dot traces a circular path */
        '<g class="cal-orbit">' +
          '<circle cx="32" cy="32" r="30" fill="none" class="cal-orbit-ring"/>' +
          '<circle cx="32" cy="2.5" r="2.8" class="cal-orbit-dot"/>' +
        '</g>' +

        /* Face disc */
        '<circle cx="32" cy="32" r="22" class="cal-face"/>' +

        /* Liquid-glass face highlight */
        '<ellipse cx="26" cy="24" rx="9" ry="5.5" class="cal-face-shine"/>' +

        /* Eyebrows — very subtle arcs above eye sockets */
        '<path d="M 17.5 22.5 Q 23 20 28.5 22.5" class="cal-brow"/>' +
        '<path d="M 35.5 22.5 Q 41 20 46.5 22.5" class="cal-brow"/>' +

        /* Eye sockets (whites) */
        '<circle cx="23" cy="29" r="5.6" class="cal-eye-white"/>' +
        '<circle cx="41" cy="29" r="5.6" class="cal-eye-white"/>' +

        /* Left pupil — translated by JS for tracking; CSS animates in idle */
        '<g id="cal-pupil-l" class="cal-pupil-group cal-idle">' +
          '<circle cx="23" cy="29" r="3.3" class="cal-iris"/>' +
          '<circle cx="24.4" cy="27.7" r="1.1" class="cal-glint"/>' +
        '</g>' +

        /* Right pupil */
        '<g id="cal-pupil-r" class="cal-pupil-group cal-idle">' +
          '<circle cx="41" cy="29" r="3.3" class="cal-iris"/>' +
          '<circle cx="42.4" cy="27.7" r="1.1" class="cal-glint"/>' +
        '</g>' +

        /* Mouth — gentle smile */
        '<path d="M 24 40 Q 32 45.5 40 40" class="cal-mouth"/>' +

      '</svg>'
    );
  }

  // ─── Events ───────────────────────────────────────────────────────────────
  function bindEvents() {
    document.addEventListener('mousemove', onMouseMove, { passive: true });
    document.addEventListener('mousedown', onMouseDown, { passive: true });
    document.addEventListener('focusin', onFocusIn, { passive: true });
  }

  function onMouseMove(e) {
    setIdle(false);
    trackPoint(e.clientX, e.clientY);
    resetIdleTimer();
  }

  function onMouseDown() {
    triggerPulse();
  }

  function onFocusIn(e) {
    var t = e.target;
    if (!t) return;
    var tag = (t.tagName || '').toUpperCase();
    var isField = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    var isCell  = !isField && !!(t.closest && t.closest('td, th'));
    if (isField || isCell) {
      var r = t.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        setIdle(false);
        trackPoint(r.left + r.width / 2, r.top + r.height / 2);
        resetIdleTimer();
      }
    }
  }

  // ─── Idle management ──────────────────────────────────────────────────────
  function resetIdleTimer() {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () { setIdle(true); }, IDLE_MS);
  }

  function setIdle(idle) {
    if (isIdle === idle) return;
    isIdle = idle;
    var pl = document.getElementById('cal-pupil-l');
    var pr = document.getElementById('cal-pupil-r');
    if (!pl || !pr) return;
    if (idle) {
      // Clear inline transform so CSS keyframe animation takes over
      pl.style.transform = '';
      pr.style.transform = '';
      pl.classList.add('cal-idle');
      pr.classList.add('cal-idle');
    } else {
      pl.classList.remove('cal-idle');
      pr.classList.remove('cal-idle');
    }
  }

  // ─── Pupil tracking ───────────────────────────────────────────────────────
  function trackPoint(screenX, screenY) {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    var r = btn.getBoundingClientRect();
    if (!r.width) return;

    var fcx = r.left + r.width  / 2;
    var fcy = r.top  + r.height / 2;
    var dx  = screenX - fcx;
    var dy  = screenY - fcy;
    var dist = Math.sqrt(dx * dx + dy * dy);

    // Influence saturates at ~320 px from face center
    var influence = Math.min(1, dist / 320);
    var angle = Math.atan2(dy, dx);
    var ox = +(Math.cos(angle) * MAX_OFFSET * influence).toFixed(3);
    var oy = +(Math.sin(angle) * MAX_OFFSET * influence).toFixed(3);

    var pl = document.getElementById('cal-pupil-l');
    var pr = document.getElementById('cal-pupil-r');
    if (!pl || !pr) return;
    var t = 'translate(' + ox + 'px,' + oy + 'px)';
    pl.style.transform = t;
    pr.style.transform = t;
  }

  // ─── Click pulse ──────────────────────────────────────────────────────────
  function triggerPulse() {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    btn.classList.remove('cal-pulse');
    void btn.offsetWidth; // force reflow so animation restarts
    btn.classList.add('cal-pulse');
    clearTimeout(pulseTO);
    pulseTO = setTimeout(function () { btn.classList.remove('cal-pulse'); }, 320);
  }

  // ─── Conflict fetch ───────────────────────────────────────────────────────
  function fetchConflicts() {
    var offset = getWeekOffset();
    var url = '/api/cal-assistant/conflicts?week_offset=' + encodeURIComponent(offset);
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) renderConflicts(data); })
      .catch(function () {});
  }

  function getWeekOffset() {
    try {
      var v = new URLSearchParams(window.location.search).get('week_offset');
      return v !== null ? (parseInt(v, 10) || 0) : 0;
    } catch (e) { return 0; }
  }

  // ─── Seen tracking ────────────────────────────────────────────────────────
  function loadSeen() {
    try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '[]'); } catch (e) { return []; }
  }
  function markSeen(id) {
    var s = loadSeen();
    if (s.indexOf(id) === -1) {
      s.push(id);
      if (s.length > MAX_SEEN) s.splice(0, s.length - MAX_SEEN);
    }
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function isSeen(id) { return loadSeen().indexOf(id) !== -1; }
  function conflictId(c) { return c.surgeonId + '-' + c.date + '-' + c.dayOffId; }

  // ─── Bubble ───────────────────────────────────────────────────────────────
  function renderConflicts(data) {
    if (!data.conflicts || !data.conflicts.length) return;
    var unseen = data.conflicts.filter(function (c) { return !isSeen(conflictId(c)); });
    if (!unseen.length) return;
    showBubble(unseen[0], unseen.length);
  }

  function showBubble(c, totalUnseen) {
    var bubble = document.getElementById('cal-bubble');
    if (!bubble) return;

    var statusCls = c.dayOffStatus === 'approved' ? 'cal-badge-approved' : 'cal-badge-pending';
    var statusTxt = c.dayOffStatus === 'approved' ? 'Approved OFF' : 'Pending OFF';
    var moreTxt   = totalUnseen > 1
      ? ' <span class="cal-more">(+' + (totalUnseen - 1) + ' more)</span>'
      : '';
    var id = conflictId(c);

    var actionsHtml = '';
    if (c.actions && c.actions.length) {
      actionsHtml = '<div class="cal-actions">' +
        c.actions.map(function (a) {
          return '<a href="' + esc(a.href) + '" class="cal-link">' + esc(a.label) + '</a>';
        }).join('') +
        '</div>';
    }

    bubble.innerHTML =
      '<div class="cal-bubble-top">' +
        '<span class="cal-bot-name">Cal-BOT</span>' +
        '<span class="cal-badge ' + statusCls + '">' + statusTxt + '</span>' +
        '<button class="cal-x" aria-label="Dismiss" data-cid="' + esc(id) + '">\u00d7</button>' +
      '</div>' +
      '<p class="cal-msg">' + formatMessage(c) + moreTxt + '</p>' +
      actionsHtml;

    bubble.classList.add('cal-visible');

    bubble.querySelector('.cal-x').addEventListener('click', function (e) {
      var cid = e.currentTarget.getAttribute('data-cid');
      if (cid) markSeen(cid);
      bubble.classList.remove('cal-visible');
      // Show next unseen after transition finishes
      setTimeout(fetchConflicts, 260);
    });
  }

  /**
   * Format the conflict in Shannon's language:
   * "JF is approved OFF Thu Aug 27 with 1 clinic patient"
   * Uses structured fields (not the raw server message string).
   */
  function formatMessage(c) {
    // c.date is ISO "YYYY-MM-DD"; parse as local midnight
    var d = new Date(c.date + 'T00:00:00');
    var DAY   = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    var MONTH = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var dayLabel   = DAY[d.getDay()] + ' ' + MONTH[d.getMonth()] + ' ' + d.getDate();
    var statusVerb = c.dayOffStatus === 'approved'
      ? 'is approved OFF'
      : 'has requested OFF (pending)';
    var parts = [];
    if (c.caseCount === 1)    parts.push('1 surgical case');
    else if (c.caseCount > 1) parts.push(c.caseCount + ' surgical cases');
    if (c.patientCount === 1)    parts.push('1 clinic patient');
    else if (c.patientCount > 1) parts.push(c.patientCount + ' clinic patients');
    return esc(c.surgeonInitials) + ' ' + statusVerb + ' ' + dayLabel +
      (parts.length ? ' with ' + parts.join(' and ') : '');
  }

  // ─── Util ─────────────────────────────────────────────────────────────────
  var ESC_MAP = { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) { return ESC_MAP[ch]; });
  }

  // ─── Run ──────────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
