/**
 * Cal-BOT — in-app scheduling assistant for the CAL admin portal.
 *
 * Grok Bot tablet avatar (violet, portrait rounded-rect).
 * Comet trail + 3D spin only while thinking. Idle: eyes + mood (smile vs worry).
 * Surfaces OFF-conflict insight bubbles with fix links. Quiet on a clean week.
 *
 * No React. No build step. Jinja2 + plain JS only.
 * Uses Clinical Trust CSS tokens from input.css :root.
 *
 * Drag: pointer events on #cal-btn; #cal-assist repositioned via left/top.
 *   Position persisted in localStorage (DRAG_KEY). Clamped to viewport.
 *   Real drag (≥ DRAG_THRESHOLD px) suppresses the click-to-think handler.
 *
 * Notif focus: clicking any [data-cal-notif] card on the dashboard focuses
 *   that issue — eyes track it, comet fires briefly, bubble restates it.
 *   A second click on the same focused card follows the data-cal-href.
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

  var SEEN_KEY       = 'cal-seen-v1';
  var MAX_SEEN       = 200;
  var IDLE_MS        = 2800;   // ms still before idle grid-scan kicks in
  var MAX_OFFSET     = 6.2;    // max pupil translation in SVG units (face is 64×64)
  var DRAG_KEY       = 'cal-bot-pos-v1';
  var DRAG_THRESHOLD = 5;      // px — minimum move to count as a real drag

  var idleTimer = null;
  var isIdle    = true;
  var pulseTO   = null;

  // Drag state
  var dragState         = null;  // {startX,startY,startLeft,startTop,moved}
  var suppressNextClick = false; // suppresses fetchConflicts after a real drag
  var focusedNotif      = null;  // the DOM element of the currently-focused notif card

  // ─── Bootstrap ────────────────────────────────────────────────────────────
  function init() {
    var path = window.location.pathname;
    var relevant = RELEVANT_PATHS.some(function (p) {
      return path === p || path.indexOf(p + '?') === 0 || path.indexOf(p + '/') === 0;
    });
    if (!relevant) return;

    injectStyles();
    document.body.appendChild(buildWidget());
    initPosition();
    setMood('ok');
    bindEvents();
    setTimeout(fetchConflicts, 900);
  }

  // ─── Styles ───────────────────────────────────────────────────────────────
  function injectStyles() {
    var s = document.createElement('style');
    s.id = 'cal-bot-styles';
    s.textContent = [
      '#cal-assist{',
      '  position:fixed;top:1.1rem;right:1.1rem;left:auto;',
      '  z-index:9999;display:flex;flex-direction:column;',
      '  align-items:flex-end;gap:.5rem;pointer-events:none;',
      '  touch-action:none;user-select:none;width:max-content;',
      '}',
      '#cal-btn{',
      '  width:88px;height:88px;background:none;border:none;padding:0;',
      '  cursor:grab;pointer-events:all;display:block;position:relative;',
      '  perspective:260px;filter:drop-shadow(0 6px 16px rgba(109,40,217,.38));',
      '}',
      '#cal-btn.cal-dragging{cursor:grabbing;}',
      '#cal-comet-svg{',
      '  position:absolute;inset:0;width:88px;height:88px;',
      '  overflow:visible;pointer-events:none;opacity:0;',
      '  transition:opacity .18s ease-out;',
      '}',
      '#cal-btn.cal-thinking #cal-comet-svg{opacity:1;}',
      '.cal-comet{',
      '  transform-origin:44px 44px;',
      '  animation:cal-comet-spin 1.7s linear infinite;',
      '  animation-play-state:paused;',
      '}',
      '#cal-btn.cal-thinking .cal-comet{animation-play-state:running;}',
      '@keyframes cal-comet-spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}',
      '.cal-comet-trail{',
      '  fill:none;stroke:#c4b5fd;stroke-width:3.2;stroke-linecap:round;',
      '  stroke-dasharray:46 192;',
      '  filter:drop-shadow(0 0 5px #a78bfa);',
      '}',
      '.cal-comet-head{fill:#fff;filter:drop-shadow(0 0 7px #e9d5ff) drop-shadow(0 0 12px #a78bfa);}',
      '.cal-comet-spark{fill:#ddd6fe;opacity:.4;}',
      '.cal-comet-dust{fill:#a78bfa;}',
      '#cal-yaw{',
      '  position:absolute;left:12px;top:12px;width:64px;height:64px;',
      '  transform-style:preserve-3d;',
      '}',
      '#cal-btn.cal-thinking #cal-yaw{animation:cal-spin 2.8s linear infinite;}',
      '@keyframes cal-spin{from{transform:rotateY(0deg)}to{transform:rotateY(360deg)}}',
      '#cal-svg{width:64px;height:64px;display:block;overflow:visible;}',
      '.cal-face{fill:#7c3aed;}',
      '.cal-face-shine{fill:#fff;opacity:.16;}',
      '.cal-eye-white{fill:#fff;}',
      '.cal-iris{fill:#1c1430;}',
      '.cal-glint{fill:#fff;opacity:.9;}',
      '.cal-pupil-group{transition:transform .1s ease-out;}',
      '.cal-pupil-group.cal-idle{transition:none;animation:cal-grid-scan 3.2s linear infinite;}',
      '@keyframes cal-grid-scan{',
      '  0%  { transform:translate(-6px,-3px); }',
      '  18% { transform:translate( 6px,-3px); }',
      '  20% { transform:translate(-6px, 0px); }',
      '  38% { transform:translate( 6px, 0px); }',
      '  40% { transform:translate(-6px, 3.2px); }',
      '  58% { transform:translate( 6px, 3.2px); }',
      '  62% { transform:translate(0,0); }',
      '  100%{ transform:translate(0,0); }',
      '}',
      '#cal-btn.cal-pulse:not(.cal-thinking) #cal-yaw{animation:cal-pulse-anim .28s ease-out;}',
      '@keyframes cal-pulse-anim{',
      '  0%{transform:rotateY(0) scale(1)} 50%{transform:rotateY(0) scale(1.12)} 100%{transform:rotateY(0) scale(1)}',
      '}',
      '.cal-mouth{fill:none;stroke:#2e1064;stroke-width:1.7;stroke-linecap:round;}',
      '.cal-mouth-ok,.cal-mouth-alert{display:none;}',
      '#cal-btn.cal-mood-ok .cal-mouth-ok{display:block;}',
      '#cal-btn.cal-mood-alert .cal-mouth-alert{display:block;}',
      '.cal-arm{',
      '  fill:#7c3aed;stroke:#5b21b6;stroke-width:1;',
      '  transform-origin:52px 50px;',
      '  opacity:0;',
      '}',
      '#cal-btn.cal-mood-ok:not(.cal-thinking) .cal-arm{',
      '  opacity:1;animation:cal-wave 3.6s ease-in-out infinite;',
      '}',
      '@keyframes cal-wave{',
      '  0%,70%,100%{transform:rotate(12deg)}',
      '  78%{transform:rotate(-28deg)}',
      '  86%{transform:rotate(18deg)}',
      '  94%{transform:rotate(-16deg)}',
      '}',
      '#cal-btn.cal-mood-alert:not(.cal-thinking) #cal-yaw{',
      '  animation:cal-worry 2.8s ease-in-out infinite;',
      '}',
      '@keyframes cal-worry{',
      '  0%,100%{transform:rotate(-4deg)}',
      '  50%{transform:rotate(4deg)}',
      '}',
      '#cal-bubble{',
      '  max-width:15.5rem;',
      '  background:var(--cal-mist,#f4f6fa);',
      '  border:1.5px solid rgba(109,40,217,.28);',
      '  border-radius:.9rem;',
      '  padding:.75rem .875rem;',
      '  box-shadow:0 4px 22px rgba(109,40,217,.13),0 1px 4px rgba(28,36,48,.07);',
      '  pointer-events:none;',
      '  font-size:.8125rem;line-height:1.5;',
      '  color:var(--cal-ink,#1c2430);',
      '  opacity:0;transform:translateY(6px);',
      '  transition:opacity .22s ease-out,transform .22s ease-out;',
      '}',
      '#cal-bubble.cal-visible{opacity:1;transform:translateY(0);pointer-events:all;}',
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
      buildCometSVG() +
      '<div id="cal-yaw">' + buildFaceSVG() + '</div>' +
      '</button>';
    return div;
  }

  function buildCometSVG() {
    // 2D comet lives outside the 3D spin so the trail stays readable.
    return (
      '<svg id="cal-comet-svg" viewBox="0 0 88 88" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
        '<g class="cal-comet">' +
          '<circle cx="44" cy="44" r="38" class="cal-comet-trail" transform="rotate(-90 44 44)"/>' +
          '<circle cx="44" cy="6" r="7" class="cal-comet-spark"/>' +
          '<circle cx="44" cy="6" r="3.8" class="cal-comet-head"/>' +
          '<circle cx="36.6" cy="7.2" r="2.2" class="cal-comet-dust" opacity=".55"/>' +
          '<circle cx="30.2" cy="10.8" r="1.6" class="cal-comet-dust" opacity=".35"/>' +
          '<circle cx="25.2" cy="16.2" r="1.15" class="cal-comet-dust" opacity=".2"/>' +
        '</g>' +
      '</svg>'
    );
  }

  function buildFaceSVG() {
    // Grok Bot tablet: portrait rounded-rect, solid violet, two eyes, no mouth.
    return (
      '<svg id="cal-svg" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
        '<rect x="14" y="6" width="36" height="52" rx="12" ry="12" class="cal-face"/>' +
        '<ellipse cx="26" cy="16" rx="10" ry="6" class="cal-face-shine"/>' +
        '<ellipse cx="24.5" cy="28" rx="7.2" ry="8.4" class="cal-eye-white"/>' +
        '<ellipse cx="39.5" cy="28" rx="7.2" ry="8.4" class="cal-eye-white"/>' +
        '<g id="cal-pupil-l" class="cal-pupil-group cal-idle">' +
          '<circle cx="24.5" cy="28" r="4.1" class="cal-iris"/>' +
          '<circle cx="26.2" cy="26.2" r="1.2" class="cal-glint"/>' +
        '</g>' +
        '<g id="cal-pupil-r" class="cal-pupil-group cal-idle">' +
          '<circle cx="39.5" cy="28" r="4.1" class="cal-iris"/>' +
          '<circle cx="41.2" cy="26.2" r="1.2" class="cal-glint"/>' +
        '</g>' +
        '<path class="cal-mouth cal-mouth-ok" d="M 24 41 Q 32 47 40 41"/>' +
        '<path class="cal-mouth cal-mouth-alert" d="M 25 43 Q 32 39 39 43"/>' +
        '<path class="cal-arm" d="M 48 46 Q 58 44 60 34 Q 61 30 58 31 Q 56 38 50 42 Z"/>' +
      '</svg>'
    );
  }

  // ─── Drag positioning ─────────────────────────────────────────────────────
  function loadDragPos() {
    try {
      var v = JSON.parse(localStorage.getItem(DRAG_KEY) || 'null');
      if (v && typeof v.left === 'number' && typeof v.top === 'number') return v;
    } catch (e) {}
    return null;
  }

  function saveDragPos(left, top) {
    try { localStorage.setItem(DRAG_KEY, JSON.stringify({ left: left, top: top })); } catch (e) {}
  }

  function clampPos(left, top) {
    // Clamp so the 88×88 button is always fully on-screen.
    var btnW = 88;
    var btnH = 88;
    var maxL = Math.max(0, window.innerWidth  - btnW);
    var maxT = Math.max(0, window.innerHeight - btnH);
    return {
      left: Math.max(0, Math.min(left, maxL)),
      top:  Math.max(0, Math.min(top,  maxT)),
    };
  }

  function applyPos(assist, left, top) {
    var c = clampPos(left, top);
    assist.style.left  = c.left + 'px';
    assist.style.top   = c.top  + 'px';
    assist.style.right = 'auto';  // must be auto, not '' — stylesheet still has right:1.1rem
  }

  function initPosition() {
    var assist = document.getElementById('cal-assist');
    if (!assist) return;
    var saved = loadDragPos();
    if (saved) {
      applyPos(assist, saved.left, saved.top);
    } else {
      // Default: upper-right, mirroring the CSS right:1.1rem / top:1.1rem.
      var margin = Math.round(1.1 * 16); // 1.1rem ≈ 18px
      applyPos(assist, window.innerWidth - 88 - margin, margin);
    }
  }

  // ─── Drag handlers ────────────────────────────────────────────────────────
  function onBtnPointerDown(e) {
    if (e.button !== 0 && e.pointerType !== 'touch') return;
    var assist = document.getElementById('cal-assist');
    var btn    = document.getElementById('cal-btn');
    if (!assist || !btn) return;

    var r = assist.getBoundingClientRect();
    dragState = {
      startX:    e.clientX,
      startY:    e.clientY,
      startLeft: r.left,
      startTop:  r.top,
      moved:     false,
    };

    btn.setPointerCapture(e.pointerId);
    btn.addEventListener('pointermove',   onBtnPointerMove);
    btn.addEventListener('pointerup',     onBtnPointerUp);
    btn.addEventListener('pointercancel', onBtnPointerUp);
    btn.classList.add('cal-dragging');
  }

  function onBtnPointerMove(e) {
    if (!dragState) return;
    var dx = e.clientX - dragState.startX;
    var dy = e.clientY - dragState.startY;

    if (!dragState.moved && Math.sqrt(dx * dx + dy * dy) > DRAG_THRESHOLD) {
      dragState.moved = true;
    }
    if (!dragState.moved) return;

    var assist = document.getElementById('cal-assist');
    if (assist) applyPos(assist, dragState.startLeft + dx, dragState.startTop + dy);
  }

  function onBtnPointerUp(e) {
    if (!dragState) return;
    var moved = dragState.moved;
    dragState = null;

    var btn = document.getElementById('cal-btn');
    if (btn) {
      btn.removeEventListener('pointermove',   onBtnPointerMove);
      btn.removeEventListener('pointerup',     onBtnPointerUp);
      btn.removeEventListener('pointercancel', onBtnPointerUp);
      btn.classList.remove('cal-dragging');
    }

    if (moved) {
      var assist = document.getElementById('cal-assist');
      if (assist) {
        var r = assist.getBoundingClientRect();
        saveDragPos(r.left, r.top);
      }
      // Suppress the click event that always fires after pointerup.
      suppressNextClick = true;
    }
  }

  // ─── Events ───────────────────────────────────────────────────────────────
  function bindEvents() {
    document.addEventListener('mousemove', onMouseMove, { passive: true });
    document.addEventListener('mousedown', onMouseDown, { passive: true });
    document.addEventListener('focusin',   onFocusIn,   { passive: true });

    var btn = document.getElementById('cal-btn');
    if (btn) {
      btn.addEventListener('pointerdown', onBtnPointerDown);
      btn.addEventListener('click', function () {
        if (suppressNextClick) { suppressNextClick = false; return; }
        fetchConflicts();
      });
    }

    // Notif card focus: first click focuses, second click on same card navigates.
    document.addEventListener('click', onNotifCardClick);
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

  // ─── Admin Notification card focus ────────────────────────────────────────
  function onNotifCardClick(e) {
    // Walk up to the nearest [data-cal-notif] ancestor (handles clicks on child elements).
    var card = e.target && e.target.closest ? e.target.closest('[data-cal-notif]') : null;
    if (!card) return;

    if (card === focusedNotif) {
      // Second click on the same focused card — follow the href.
      var href = card.getAttribute('data-cal-href') || '';
      if (href) {
        window.location.href = href;
      }
      return;
    }

    // First click (or click on a different card): focus it.
    e.preventDefault();
    focusedNotif = card;

    // Eyes look at the card.
    var r = card.getBoundingClientRect();
    setIdle(false);
    trackPoint(r.left + r.width / 2, r.top + r.height / 2);
    resetIdleTimer();

    // Brief thinking comet fires.
    setThinking(true);
    var thinkNotifTO = setTimeout(function () { setThinking(false); }, 850);
    void thinkNotifTO; // reference avoids linter warning

    // Render the bubble with notif content.
    showNotifBubble(card);
  }

  function showNotifBubble(card) {
    var bubble = document.getElementById('cal-bubble');
    if (!bubble) return;

    var title = card.getAttribute('data-cal-title') || 'Notification';
    var body  = card.getAttribute('data-cal-body')  || '';
    var href  = card.getAttribute('data-cal-href')  || '';

    setMood('alert');

    var goHtml = href
      ? '<div class="cal-actions">' +
          '<a href="' + esc(href) + '" class="cal-link">Go there \u2192</a>' +
        '</div>'
      : '';

    bubble.innerHTML =
      '<div class="cal-bubble-top">' +
        '<span class="cal-bot-name">Cal-BOT</span>' +
        '<button class="cal-x" aria-label="Dismiss" type="button">\u00d7</button>' +
      '</div>' +
      '<p class="cal-msg">' + esc(title) + '</p>' +
      (body ? '<p class="cal-more">' + esc(body) + '</p>' : '') +
      goHtml;

    bubble.classList.add('cal-visible');

    bubble.querySelector('.cal-x').addEventListener('click', function () {
      bubble.classList.remove('cal-visible');
      focusedNotif = null;
      setMood('ok');
    });
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
  var thinkTO = null;
  function setThinking(on) {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    if (on) btn.classList.add('cal-thinking');
    else btn.classList.remove('cal-thinking');
  }
  function setMood(mood) {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    btn.classList.remove('cal-mood-ok', 'cal-mood-alert');
    btn.classList.add('cal-mood-' + mood);
  }
  function fetchConflicts() {
    setThinking(true);
    var started = Date.now();
    var offset = getWeekOffset();
    var url = '/api/cal-assistant/conflicts?week_offset=' + encodeURIComponent(offset);
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data) renderConflicts(data);
        else setMood('ok');
      })
      .catch(function () { setMood('ok'); })
      .then(function () {
        var wait = Math.max(0, 1600 - (Date.now() - started));
        clearTimeout(thinkTO);
        thinkTO = setTimeout(function () { setThinking(false); }, wait);
      });
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
    if (!data.conflicts || !data.conflicts.length) {
      setMood('ok');
      return;
    }
    var unseen = data.conflicts.filter(function (c) { return !isSeen(conflictId(c)); });
    if (!unseen.length) {
      setMood('ok');
      return;
    }
    setMood('alert');
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
        '<button class="cal-x" aria-label="Dismiss" data-cid="' + esc(id) + '" type="button">\u00d7</button>' +
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
