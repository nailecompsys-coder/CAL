/**
 * Cal-BOT — in-app scheduling assistant for the CAL admin portal.
 *
 * A purple circular avatar with:
 *  - Orbiting ring (idle spin)
 *  - Eyes that track the mouse cursor and look toward focused inputs/clicked cells
 *  - Idle eye-scan animation when the cursor is still
 *  - Speech bubble surfacing OFF conflicts with a concrete fix link
 *  - Dismiss/seen tracking via localStorage so it stays quiet on clean weeks
 *
 * Clinical Trust tokens: uses CSS variables from input.css (:root).
 * No React, no build step, no hardcoded hex — a single self-contained IIFE.
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

  // ─── Constants ───────────────────────────────────────────────────────────
  var SEEN_KEY = 'cal-seen-v1';
  var MAX_SEEN = 200;
  var IDLE_MS = 2600;         // ms of no mouse movement before idle scan
  var MAX_PUPIL_PX = 2.3;     // max pupil offset in SVG units (face is 64×64)

  // ─── State ───────────────────────────────────────────────────────────────
  var idleTimer = null;
  var isIdle = true;
  var pulseTO = null;

  // ─── Entry ───────────────────────────────────────────────────────────────
  function init() {
    var path = window.location.pathname;
    var relevant = RELEVANT_PATHS.some(function (p) {
      return path === p || path.indexOf(p + '?') === 0 || path.indexOf(p + '/') === 0;
    });
    if (!relevant) return;

    injectStyles();
    var widget = buildWidget();
    document.body.appendChild(widget);
    bindEvents();
    scheduleConflictFetch();
  }

  // ─── Styles (inline — no extra HTTP request) ─────────────────────────────
  function injectStyles() {
    var el = document.createElement('style');
    el.id = 'cal-assist-styles';
    el.textContent = [
      /* Widget container */
      '#cal-assist{',
      '  position:fixed;bottom:1.25rem;right:1.25rem;',
      '  z-index:9999;display:flex;flex-direction:column;',
      '  align-items:flex-end;gap:.5rem;pointer-events:none;',
      '}',
      /* Face button */
      '#cal-btn{',
      '  width:64px;height:64px;background:none;border:none;padding:0;',
      '  cursor:pointer;pointer-events:all;border-radius:50%;display:block;',
      '  filter:drop-shadow(0 2px 10px rgba(109,40,217,.22));',
      '  transition:filter .2s,transform .2s;',
      '}',
      '#cal-btn:hover{filter:drop-shadow(0 4px 18px rgba(109,40,217,.44));}',
      '#cal-svg{width:64px;height:64px;display:block;}',
      /* Face elements — use CSS vars set in input.css :root */
      '.cal-face{fill:var(--cal-purple-soft,#ede9fe);stroke:var(--cal-purple,#6d28d9);stroke-width:2;}',
      '.cal-eye-white{fill:#fff;stroke:var(--cal-stroke,rgba(180,196,220,.55));stroke-width:.8;}',
      '.cal-iris{fill:var(--cal-purple,#6d28d9);}',
      '.cal-glint{fill:#fff;opacity:.78;}',
      '.cal-mouth{fill:none;stroke:var(--cal-purple-mid,#8b5cf6);stroke-width:1.5;stroke-linecap:round;opacity:.45;}',
      /* Orbiting ring */
      '.cal-orbit{transform-origin:32px 32px;animation:cal-orbit-spin 13s linear infinite;}',
      '.cal-orbit-ring{stroke:var(--cal-purple-mid,#8b5cf6);stroke-width:1.5;stroke-dasharray:3 9;opacity:.42;}',
      '.cal-orbit-dot{fill:var(--cal-purple-mid,#8b5cf6);opacity:.65;}',
      '@keyframes cal-orbit-spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}',
      /* Pupils — smooth JS tracking */
      '.cal-pupil-group{transition:transform .11s ease-out;}',
      /* Idle scan (CSS animation; toggled via class) */
      '.cal-pupil-group.cal-idle{',
      '  transition:none;',
      '  animation:cal-scan 10s ease-in-out infinite;',
      '}',
      '@keyframes cal-scan{',
      '  0%,100%{transform:translate(0,0)}',
      '  10%{transform:translate(1.8px,-.9px)}',
      '  25%{transform:translate(2.2px,.6px)}',
      '  42%{transform:translate(.8px,1.9px)}',
      '  57%{transform:translate(-2.2px,.7px)}',
      '  72%{transform:translate(-1.9px,-.8px)}',
      '  88%{transform:translate(-.4px,-2px)}',
      '}',
      /* Click pulse */
      '#cal-btn.cal-pulse{animation:cal-pulse-anim .28s ease-out;}',
      '@keyframes cal-pulse-anim{0%{transform:scale(1)}50%{transform:scale(1.13)}100%{transform:scale(1)}}',
      /* Speech bubble */
      '#cal-bubble{',
      '  max-width:15.5rem;',
      '  background:var(--cal-mist,#f4f6fa);',
      '  border:1.5px solid rgba(109,40,217,.28);',
      '  border-radius:.9rem;',
      '  padding:.75rem .875rem;',
      '  box-shadow:0 4px 22px rgba(109,40,217,.13),0 1px 4px rgba(28,36,48,.07);',
      '  pointer-events:all;',
      '  font-size:.8125rem;line-height:1.5;',
      '  color:var(--cal-ink,#1c2430);',
      '}',
      '.cal-bubble-top{display:flex;align-items:center;gap:.4rem;margin-bottom:.4rem;}',
      '.cal-bot-name{font-size:.7rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;',
      '  color:var(--cal-purple,#6d28d9);margin-right:auto;}',
      '.cal-badge{font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:9999px;flex-shrink:0;letter-spacing:.01em;}',
      '.cal-badge-approved{background:#dcfce7;color:#166534;}',
      '.cal-badge-pending{background:var(--cal-amber,#ffe8c2);color:#92400e;}',
      '.cal-x{background:none;border:none;cursor:pointer;font-size:1.2rem;line-height:1;',
      '  color:var(--cal-muted,#6b7a8d);padding:0 3px;opacity:.65;transition:opacity .15s;}',
      '.cal-x:hover{opacity:1;}',
      '.cal-msg{margin:0 0 .45rem;font-weight:500;}',
      '.cal-more{color:var(--cal-muted,#6b7a8d);font-weight:400;font-size:.75rem;}',
      '.cal-actions{display:flex;flex-direction:column;gap:.28rem;margin-top:.35rem;}',
      '.cal-link{color:var(--cal-purple-mid,#8b5cf6);font-weight:600;text-decoration:none;font-size:.78rem;}',
      '.cal-link:hover{text-decoration:underline;}',
    ].join('\n');
    document.head.appendChild(el);
  }

  // ─── Widget DOM ───────────────────────────────────────────────────────────
  function buildWidget() {
    var div = document.createElement('div');
    div.id = 'cal-assist';
    div.innerHTML =
      '<div id="cal-bubble" hidden></div>' +
      '<button id="cal-btn" aria-label="Cal-BOT" type="button">' +
      buildFaceSVG() +
      '</button>';
    return div;
  }

  function buildFaceSVG() {
    // viewBox 64×64; face centered at (32,32) r=22; orbit ring r=30
    return (
      '<svg id="cal-svg" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
        // Orbit ring + dot (rotates as a group around center 32,32)
        '<g class="cal-orbit">' +
          '<circle cx="32" cy="32" r="30" fill="none" class="cal-orbit-ring"/>' +
          '<circle cx="32" cy="2.5" r="2.8" class="cal-orbit-dot"/>' +
        '</g>' +
        // Face disc
        '<circle cx="32" cy="32" r="22" class="cal-face"/>' +
        // Left eye socket
        '<circle cx="23" cy="29" r="5.6" class="cal-eye-white"/>' +
        // Right eye socket
        '<circle cx="41" cy="29" r="5.6" class="cal-eye-white"/>' +
        // Left pupil group (translated by JS for tracking; animated in idle)
        '<g id="cal-pupil-l" class="cal-pupil-group cal-idle">' +
          '<circle cx="23" cy="29" r="3.3" class="cal-iris"/>' +
          '<circle cx="24.4" cy="27.7" r="1.1" class="cal-glint"/>' +
        '</g>' +
        // Right pupil group
        '<g id="cal-pupil-r" class="cal-pupil-group cal-idle">' +
          '<circle cx="41" cy="29" r="3.3" class="cal-iris"/>' +
          '<circle cx="42.4" cy="27.7" r="1.1" class="cal-glint"/>' +
        '</g>' +
        // Gentle mouth
        '<path d="M 24 40 Q 32 45.5 40 40" class="cal-mouth"/>' +
      '</svg>'
    );
  }

  // ─── Event bindings ───────────────────────────────────────────────────────
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

  function onMouseDown(e) {
    // Brief pulse on any click; pupils already track via mousemove
    triggerPulse();
  }

  function onFocusIn(e) {
    var t = e.target;
    if (!t) return;
    var tag = t.tagName || '';
    var isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    var isCell = !isInput && (t.closest ? t.closest('td, th') : false);
    if (isInput || isCell) {
      var rect = t.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setIdle(false);
        trackPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        resetIdleTimer();
      }
    }
  }

  // ─── Idle management ─────────────────────────────────────────────────────
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

  // ─── Eye tracking ─────────────────────────────────────────────────────────
  function trackPoint(screenX, screenY) {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    var rect = btn.getBoundingClientRect();
    if (!rect.width) return;

    var fcx = rect.left + rect.width / 2;
    var fcy = rect.top + rect.height / 2;
    var dx = screenX - fcx;
    var dy = screenY - fcy;
    var dist = Math.sqrt(dx * dx + dy * dy);

    // Influence: 0 when on top of face, saturates at ~320px
    var influence = Math.min(1, dist / 320);
    var angle = Math.atan2(dy, dx);
    var ox = +(Math.cos(angle) * MAX_PUPIL_PX * influence).toFixed(3);
    var oy = +(Math.sin(angle) * MAX_PUPIL_PX * influence).toFixed(3);

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
    // Force reflow so the animation restarts
    void btn.offsetWidth; // eslint-disable-line no-unused-expressions
    btn.classList.add('cal-pulse');
    clearTimeout(pulseTO);
    pulseTO = setTimeout(function () { btn.classList.remove('cal-pulse'); }, 320);
  }

  // ─── Conflict fetch ───────────────────────────────────────────────────────
  function scheduleConflictFetch() {
    // Small delay so it doesn't race with page paint
    setTimeout(function () {
      var offset = getWeekOffset();
      var url = '/api/cal-assistant/conflicts?week_offset=' + encodeURIComponent(offset);
      fetch(url, { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { if (data) renderConflicts(data); })
        .catch(function () {});
    }, 800);
  }

  function getWeekOffset() {
    var params = new URLSearchParams(window.location.search);
    var v = params.get('week_offset');
    return v !== null ? parseInt(v, 10) || 0 : 0;
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

  // ─── Bubble render ────────────────────────────────────────────────────────
  function renderConflicts(data) {
    if (!data.conflicts || !data.conflicts.length) return;
    var unseen = data.conflicts.filter(function (c) { return !isSeen(conflictId(c)); });
    if (!unseen.length) return;
    showBubble(unseen[0], unseen.length, data.weekOffset || 0);
  }

  function showBubble(c, totalUnseen, weekOffset) {
    var bubble = document.getElementById('cal-bubble');
    if (!bubble) return;

    var statusCls = c.dayOffStatus === 'approved' ? 'cal-badge-approved' : 'cal-badge-pending';
    var statusTxt = c.dayOffStatus === 'approved' ? 'Approved OFF' : 'Pending OFF';
    var moreTxt = totalUnseen > 1
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
      '<p class="cal-msg">' + esc(c.message) + moreTxt + '</p>' +
      actionsHtml;

    bubble.hidden = false;

    bubble.querySelector('.cal-x').addEventListener('click', function (e) {
      var cid = e.currentTarget.getAttribute('data-cid');
      if (cid) markSeen(cid);
      bubble.hidden = true;
      // Reload to show the next unseen conflict (if any)
      scheduleConflictFetch();
    });
  }

  // ─── Helpers ─────────────────────────────────────────────────────────────
  var ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) { return ESC_MAP[ch]; });
  }

  // ─── Bootstrap ───────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
