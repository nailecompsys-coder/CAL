/**
 * Grok-BOT — in-app scheduling assistant for the CAL admin portal.
 *
 * Capsule avatar (Grok-style: lavender pill, white slit eyes).
 * Idle is not a loop: he sleeps, glances, bobs, blinks, and wiggles at random.
 * Thinking: 3D spin, eyes dart, debris flies around him.
 * Surfaces OFF-conflict insight bubbles with fix links. Quiet on a clean week.
 *
 * No React. No build step. Jinja2 + plain JS only.
 * Uses Clinical Trust CSS tokens from input.css :root.
 *
 * Lives in the admin sidebar footer (#grok-dock), on the v2.0 / Backup line.
 * Ask him is the field next to the capsule — not a floating off-screen bar.
 *
 * Notif focus: clicking any [data-cal-notif] card on the dashboard focuses
 *   that issue — eyes track it, debris fires briefly, bubble restates it.
 *   A second click on the same focused card follows the data-cal-href.
 */
(function () {
  'use strict';

  var SEEN_KEY       = 'cal-seen-v1';
  var MAX_SEEN       = 200;
  var IDLE_MS        = 2200;
  var MAX_OFFSET     = 5.4;
  var DRAG_KEY       = 'cal-bot-pos-v1';
  var DRAG_THRESHOLD = 5;

  var idleTimer = null;
  var isIdle    = true;
  var pulseTO   = null;
  var directorTO = null;
  var dartTO     = null;
  var sleeping   = false;
  var thinking   = false;

  var dragState         = null;
  var suppressNextClick = false;
  var focusedNotif      = null;

  function init() {
    var dock = document.getElementById('grok-dock');
    if (!dock) return;

    injectStyles();
    dock.appendChild(buildWidget());
    var assist = document.getElementById('cal-assist');
    if (assist) assist.classList.add('cal-docked');
    setMood('ok');
    bindEvents();
    startDirector();
    setTimeout(fetchConflicts, 900);
    setInterval(fetchConflicts, 5 * 60 * 1000);
  }

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
      '  perspective:280px;',
      '  filter:drop-shadow(0 6px 16px color-mix(in srgb, var(--cal-purple,#6d28d9) 38%, transparent));',
      '}',
      '#cal-btn.cal-dragging{cursor:grabbing;}',
      '#cal-orbit-svg{',
      '  position:absolute;inset:0;width:88px;height:88px;',
      '  overflow:visible;pointer-events:none;opacity:.12;',
      '  transition:opacity .22s ease-out;',
      '}',
      '#cal-btn.cal-thinking #cal-orbit-svg{opacity:1;}',
      '#cal-btn.cal-spark #cal-orbit-svg{opacity:.55;}',
      '.cal-orbit{transform-origin:44px 44px;animation-play-state:paused;}',
      '#cal-btn.cal-thinking .cal-orbit,',
      '#cal-btn.cal-spark .cal-orbit{animation-play-state:running;}',
      '.cal-orbit-a{animation:cal-orbit-spin 1.15s linear infinite;}',
      '.cal-orbit-b{animation:cal-orbit-spin 1.85s linear infinite reverse;}',
      '.cal-orbit-c{animation:cal-orbit-spin 2.55s linear infinite;}',
      '@keyframes cal-orbit-spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}',
      '.cal-fly-dot{fill:var(--cal-purple-soft,#ede9fe);filter:drop-shadow(0 0 4px var(--cal-purple-mid,#8b5cf6));}',
      '.cal-fly-chip{fill:var(--cal-purple-mid,#8b5cf6);opacity:.85;}',
      '.cal-fly-star{fill:#fff;opacity:.9;filter:drop-shadow(0 0 5px var(--cal-purple-mid,#8b5cf6));}',
      '.cal-fly-spark{fill:var(--cal-purple-soft,#ede9fe);opacity:.55;}',
      '#cal-yaw{',
      '  position:absolute;left:12px;top:26px;width:64px;height:36px;',
      '  transform-style:preserve-3d;',
      '}',
      '#cal-btn.cal-thinking #cal-yaw{animation:cal-spin 2.4s linear infinite;}',
      '@keyframes cal-spin{',
      '  0%{transform:rotateY(0deg) rotateZ(0deg)}',
      '  40%{transform:rotateY(180deg) rotateZ(-8deg)}',
      '  100%{transform:rotateY(360deg) rotateZ(0deg)}',
      '}',
      '#cal-svg{width:64px;height:36px;display:block;overflow:visible;}',
      '.cal-face{fill:var(--cal-purple-mid,#8b5cf6);}',
      '.cal-face-shine{fill:#fff;opacity:.22;}',
      '.cal-slit{fill:#fff;}',
      '.cal-eyes{transform-origin:44px 18px;transition:transform .16s ease-out;}',
      '#cal-btn.cal-sleep .cal-eyes{',
      '  transform:scaleY(.16) translateY(2px);',
      '  transition:transform .35s ease;',
      '}',
      '#cal-btn.cal-blink .cal-eyes{',
      '  transform:scaleY(.12);',
      '  transition:transform .08s ease;',
      '}',
      '#cal-btn.cal-thinking .cal-eyes{transition:transform .08s ease-out;}',
      '#cal-btn.cal-pulse:not(.cal-thinking) #cal-yaw{animation:cal-pulse-anim .28s ease-out;}',
      '@keyframes cal-pulse-anim{',
      '  0%{transform:rotateY(0) scale(1)} 50%{transform:rotateY(0) scale(1.12)} 100%{transform:rotateY(0) scale(1)}',
      '}',
      '#cal-btn.cal-bob:not(.cal-thinking):not(.cal-sleep) #cal-yaw{',
      '  animation:cal-bob 1.6s ease-in-out 1;',
      '}',
      '@keyframes cal-bob{',
      '  0%,100%{transform:translateY(0)}',
      '  40%{transform:translateY(-5px) rotateZ(-4deg)}',
      '  70%{transform:translateY(2px) rotateZ(3deg)}',
      '}',
      '#cal-btn.cal-wiggle:not(.cal-thinking):not(.cal-sleep) #cal-yaw{',
      '  animation:cal-wiggle .7s ease-in-out 1;',
      '}',
      '@keyframes cal-wiggle{',
      '  0%,100%{transform:rotateZ(0)}',
      '  25%{transform:rotateZ(-11deg) translateX(-2px)}',
      '  50%{transform:rotateZ(9deg) translateX(2px)}',
      '  75%{transform:rotateZ(-5deg)}',
      '}',
      '#cal-btn.cal-peek:not(.cal-thinking):not(.cal-sleep) #cal-yaw{',
      '  animation:cal-peek 1.4s ease-in-out 1;',
      '}',
      '@keyframes cal-peek{',
      '  0%,100%{transform:rotateZ(0) rotateY(0)}',
      '  35%{transform:rotateZ(-14deg) rotateY(-18deg)}',
      '  65%{transform:rotateZ(6deg) rotateY(10deg)}',
      '}',
      '#cal-btn.cal-sleep #cal-yaw{',
      '  animation:cal-sleep-bob 3.6s ease-in-out infinite;',
      '  filter:brightness(.93);',
      '}',
      '@keyframes cal-sleep-bob{',
      '  0%,100%{transform:translateY(3px) rotateZ(-8deg)}',
      '  50%{transform:translateY(6px) rotateZ(-4deg)}',
      '}',
      '#cal-btn.cal-zzz::after{',
      '  content:"zzz";position:absolute;top:6px;right:4px;',
      '  font-size:11px;font-weight:800;letter-spacing:.04em;',
      '  color:var(--cal-purple,#6d28d9);opacity:.55;',
      '  animation:cal-zzz 1.8s ease-in-out infinite;',
      '  pointer-events:none;',
      '}',
      '@keyframes cal-zzz{',
      '  0%{transform:translate(0,0) scale(.8);opacity:.15}',
      '  50%{transform:translate(4px,-8px) scale(1);opacity:.7}',
      '  100%{transform:translate(8px,-16px) scale(1.1);opacity:0}',
      '}',
      '#cal-btn.cal-mood-alert:not(.cal-thinking):not(.cal-sleep) #cal-yaw{',
      '  animation:cal-worry 2.8s ease-in-out infinite;',
      '}',
      '@keyframes cal-worry{',
      '  0%,100%{transform:rotate(-4deg)}',
      '  50%{transform:rotate(4deg)}',
      '}',
      '#cal-bubble{',
      '  max-width:15.5rem;',
      '  background:var(--cal-mist,#f4f6fa);',
      '  border:1.5px solid color-mix(in srgb, var(--cal-purple,#6d28d9) 28%, transparent);',
      '  border-radius:.9rem;',
      '  padding:.75rem .875rem;',
      '  box-shadow:0 4px 22px color-mix(in srgb, var(--cal-purple,#6d28d9) 13%, transparent),0 1px 4px rgba(28,36,48,.07);',
      '  pointer-events:none;',
      '  font-size:.8125rem;line-height:1.5;',
      '  color:var(--cal-ink,#1c2430);',
      '  opacity:0;transform:translateY(6px);',
      '  transition:opacity .22s ease-out,transform .22s ease-out;',
      '}',
      '#cal-bubble:empty{display:none;padding:0;border:0;box-shadow:none;}',
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
      '#cal-ask{',
      '  width:16.5rem;pointer-events:all;',
      '}',
      '#cal-ask-label{',
      '  display:block;margin:0 0 .22rem .15rem;',
      '  font-size:.62rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;',
      '  color:var(--cal-purple,#6d28d9);',
      '}',
      '#cal-ask-form{',
      '  display:flex;gap:.35rem;align-items:stretch;',
      '  background:var(--cal-mist,#f4f6fa);',
      '  border:1.5px solid color-mix(in srgb, var(--cal-purple,#6d28d9) 28%, transparent);',
      '  border-radius:.9rem;padding:.28rem .28rem .28rem .55rem;',
      '  box-shadow:0 4px 18px color-mix(in srgb, var(--cal-purple,#6d28d9) 12%, transparent);',
      '}',
      '#cal-ask-input{',
      '  flex:1;min-width:0;border:0;background:transparent;outline:none;',
      '  font-size:.75rem;color:var(--cal-ink,#1c2430);',
      '}',
      '#cal-ask-input::placeholder{color:var(--cal-muted,#6b7a8d);}',
      '#cal-ask-go{',
      '  border:0;border-radius:.7rem;cursor:pointer;',
      '  background:var(--cal-purple,#6d28d9);color:#fff;',
      '  font-size:.68rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;',
      '  padding:.4rem .65rem;',
      '}',
      '#cal-assist.cal-docked{',
      '  position:relative;top:auto;right:auto;left:auto;',
      '  width:100%;align-items:stretch;gap:.4rem;',
      '  pointer-events:all;z-index:2;',
      '}',
      '#cal-assist.cal-docked .cal-dock-row{',
      '  display:flex;align-items:center;gap:.4rem;width:100%;',
      '}',
      '#cal-assist.cal-docked #cal-btn{',
      '  width:52px;height:40px;flex-shrink:0;cursor:pointer;',
      '}',
      '#cal-assist.cal-docked #cal-orbit-svg{width:52px;height:40px;}',
      '#cal-assist.cal-docked #cal-yaw{left:2px;top:4px;width:48px;height:32px;}',
      '#cal-assist.cal-docked #cal-svg{width:48px;height:32px;}',
      '#cal-assist.cal-docked #cal-ask{width:auto;flex:1;min-width:0;}',
      '#cal-assist.cal-docked #cal-ask-label{display:none;}',
      '#cal-assist.cal-docked #cal-ask-form{box-shadow:none;}',
      '#cal-assist.cal-docked #cal-bubble{max-width:none;width:100%;}',
    ].join('\n');
    document.head.appendChild(s);
  }

  function buildWidget() {
    var div = document.createElement('div');
    div.id = 'cal-assist';
    div.innerHTML =
      '<div id="cal-bubble"></div>' +
      '<div class="cal-dock-row">' +
        '<button id="cal-btn" aria-label="Grok-BOT" type="button">' +
        buildOrbitSVG() +
        '<div id="cal-yaw">' + buildFaceSVG() + '</div>' +
        '</button>' +
        '<div id="cal-ask">' +
          '<span id="cal-ask-label">Ask him</span>' +
          '<form id="cal-ask-form" autocomplete="off">' +
            '<input id="cal-ask-input" type="text" maxlength="240" placeholder="Ask him\u2026" />' +
            '<button id="cal-ask-go" type="submit">Ask him</button>' +
          '</form>' +
        '</div>' +
      '</div>';
    return div;
  }

  function buildOrbitSVG() {
    return (
      '<svg id="cal-orbit-svg" viewBox="0 0 88 88" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
        '<g class="cal-orbit cal-orbit-a">' +
          '<circle class="cal-fly-dot" cx="44" cy="5" r="2.6"/>' +
          '<rect class="cal-fly-chip" x="78" y="40" width="5" height="5" rx="1.2"/>' +
        '</g>' +
        '<g class="cal-orbit cal-orbit-b">' +
          '<polygon class="cal-fly-star" points="12,44 13.4,47.2 16.8,47.4 14.2,49.6 15,53 12,51.2 9,53 9.8,49.6 7.2,47.4 10.6,47.2"/>' +
          '<circle class="cal-fly-spark" cx="62" cy="10" r="1.6"/>' +
          '<circle class="cal-fly-spark" cx="18" cy="70" r="1.3"/>' +
        '</g>' +
        '<g class="cal-orbit cal-orbit-c">' +
          '<circle class="cal-fly-dot" cx="44" cy="82" r="1.8"/>' +
          '<rect class="cal-fly-chip" x="6" y="22" width="3.2" height="3.2" rx="0.8" transform="rotate(22 7.6 23.6)"/>' +
          '<polygon class="cal-fly-star" points="74,68 75,70.4 77.6,70.6 75.6,72.2 76.2,74.6 74,73.2 71.8,74.6 72.4,72.2 70.4,70.6 73,70.4"/>' +
        '</g>' +
      '</svg>'
    );
  }

  function buildFaceSVG() {
    // Horizontal Grok capsule — white slit eyes, no mouth, no arm.
    return (
      '<svg id="cal-svg" viewBox="0 0 64 36" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
        '<rect x="2" y="6" width="60" height="24" rx="12" ry="12" class="cal-face"/>' +
        '<ellipse cx="16" cy="12" rx="10" ry="5" class="cal-face-shine"/>' +
        '<g id="cal-eyes" class="cal-eyes">' +
          '<rect class="cal-slit" x="34" y="15" width="11" height="4.2" rx="2.1"/>' +
          '<rect class="cal-slit" x="47" y="15" width="11" height="4.2" rx="2.1"/>' +
        '</g>' +
      '</svg>'
    );
  }

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
    assist.style.right = 'auto';
  }

  function initPosition() {
    if (isDocked()) return;
  }

  function isDocked() {
    var assist = document.getElementById('cal-assist');
    return !!(assist && assist.classList.contains('cal-docked'));
  }

  function keepWidgetOnScreen() {
    if (isDocked()) return;
  }

  function onBtnPointerDown(e) {
    if (isDocked()) return;
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
      suppressNextClick = true;
    }
  }

  function bindEvents() {
    document.addEventListener('mousemove', onMouseMove, { passive: true });
    document.addEventListener('mousedown', onMouseDown, { passive: true });
    document.addEventListener('focusin',   onFocusIn,   { passive: true });

    var btn = document.getElementById('cal-btn');
    if (btn) {
      btn.addEventListener('pointerdown', onBtnPointerDown);
      btn.addEventListener('click', function () {
        if (suppressNextClick) { suppressNextClick = false; return; }
        wakeFromSleep();
        checkRulesThenConflicts();
      });
    }

    var askForm = document.getElementById('cal-ask-form');
    if (askForm) {
      askForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var input = document.getElementById('cal-ask-input');
        var question = input ? String(input.value || '').trim() : '';
        if (!question) {
          showAskBubble('Ask me about time off, clinic patients, cases, call, meetings, or a location.');
          return;
        }
        askGrok(question);
      });
    }

    document.addEventListener('click', onNotifCardClick);
  }

  function onMouseMove(e) {
    if (sleeping) return;
    setIdle(false);
    if (!thinking) trackPoint(e.clientX, e.clientY);
    resetIdleTimer();
  }

  function onMouseDown() {
    if (sleeping) wakeFromSleep();
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
        if (sleeping) wakeFromSleep();
        setIdle(false);
        if (!thinking) trackPoint(r.left + r.width / 2, r.top + r.height / 2);
        resetIdleTimer();
      }
    }
  }

  function onNotifCardClick(e) {
    var card = e.target && e.target.closest ? e.target.closest('[data-cal-notif]') : null;
    if (!card) return;
    if (card.getAttribute('data-cal-informational') === '1') return;

    if (card === focusedNotif) {
      var href = card.getAttribute('data-cal-href') || '';
      if (href) {
        window.location.href = href;
      }
      return;
    }

    e.preventDefault();
    focusedNotif = card;

    var r = card.getBoundingClientRect();
    wakeFromSleep();
    setIdle(false);
    trackPoint(r.left + r.width / 2, r.top + r.height / 2);
    resetIdleTimer();

    setThinking(true);
    var thinkNotifTO = setTimeout(function () { setThinking(false); }, 850);
    void thinkNotifTO;

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
        '<span class="cal-bot-name">Grok-BOT</span>' +
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

  function showAskBubble(answer) {
    var bubble = document.getElementById('cal-bubble');
    if (!bubble) return;
    setMood('ok');
    bubble.innerHTML =
      '<div class="cal-bubble-top">' +
        '<span class="cal-bot-name">Grok-BOT</span>' +
        '<button class="cal-x" aria-label="Dismiss" type="button">\u00d7</button>' +
      '</div>' +
      '<p class="cal-msg">' + esc(answer) + '</p>' +
      '<div class="cal-actions">' +
        '<a href="/admin/settings/grok-bot-rules" class="cal-link">Rules he follows \u2192</a>' +
      '</div>';
    bubble.classList.add('cal-visible');
    keepWidgetOnScreen();
    bubble.querySelector('.cal-x').addEventListener('click', function () {
      bubble.classList.remove('cal-visible');
    });
  }

  function askGrok(question) {
    wakeFromSleep();
    setThinking(true);
    fetch('/api/admin/grok/ask', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ question: question }),
    })
      .then(function (r) { return r.ok ? r.json() : { answer: 'I could not reach the live board.' }; })
      .then(function (data) {
        showAskBubble((data && data.answer) || 'I could not tell who or what that was about.');
      })
      .catch(function () { showAskBubble('I could not reach the live board.'); })
      .then(function () { setThinking(false); });
  }

  function checkRulesThenConflicts() {
    setThinking(true);
    fetch('/api/admin/grok/check-rules', { method: 'POST', credentials: 'same-origin' })
      .catch(function () {})
      .then(function () { fetchConflicts(); });
  }

  function resetIdleTimer() {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () { setIdle(true); }, IDLE_MS);
  }

  function setIdle(idle) {
    isIdle = idle;
    if (!idle && sleeping) return;
    var eyes = document.getElementById('cal-eyes');
    if (!eyes) return;
    if (!idle) {
      eyes.style.transition = 'transform .16s ease-out';
    }
  }

  function trackPoint(screenX, screenY) {
    if (sleeping || thinking) return;
    var btn = document.getElementById('cal-btn');
    var eyes = document.getElementById('cal-eyes');
    if (!btn || !eyes) return;
    var r = btn.getBoundingClientRect();
    if (!r.width) return;

    var fcx = r.left + r.width  / 2;
    var fcy = r.top  + r.height / 2;
    var dx  = screenX - fcx;
    var dy  = screenY - fcy;
    var dist = Math.sqrt(dx * dx + dy * dy);

    var influence = Math.min(1, dist / 320);
    var angle = Math.atan2(dy, dx);
    var ox = +(Math.cos(angle) * MAX_OFFSET * influence).toFixed(3);
    var oy = +(Math.sin(angle) * MAX_OFFSET * influence * 0.7).toFixed(3);
    eyes.style.transform = 'translate(' + ox + 'px,' + oy + 'px)';
  }

  function setEyeOffset(ox, oy) {
    var eyes = document.getElementById('cal-eyes');
    if (!eyes) return;
    eyes.style.transform = 'translate(' + ox + 'px,' + oy + 'px)';
  }

  function triggerPulse() {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    btn.classList.remove('cal-pulse');
    void btn.offsetWidth;
    btn.classList.add('cal-pulse');
    clearTimeout(pulseTO);
    pulseTO = setTimeout(function () { btn.classList.remove('cal-pulse'); }, 320);
  }

  function rand(min, max) {
    return min + Math.random() * (max - min);
  }

  function startDirector() {
    scheduleDirector(rand(1600, 3200));
  }

  function scheduleDirector(ms) {
    clearTimeout(directorTO);
    directorTO = setTimeout(runDirector, ms);
  }

  function clearMotionClasses() {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    btn.classList.remove('cal-bob', 'cal-wiggle', 'cal-peek', 'cal-blink', 'cal-spark');
  }

  function bumpClass(name, ms) {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    btn.classList.remove(name);
    void btn.offsetWidth;
    btn.classList.add(name);
    setTimeout(function () { btn.classList.remove(name); }, ms);
  }

  function goSleep() {
    var btn = document.getElementById('cal-btn');
    if (!btn || thinking) return;
    sleeping = true;
    clearMotionClasses();
    var eyes = document.getElementById('cal-eyes');
    if (eyes) eyes.style.transform = '';
    btn.classList.add('cal-sleep', 'cal-zzz');
  }

  function wakeFromSleep() {
    if (!sleeping) return;
    sleeping = false;
    var btn = document.getElementById('cal-btn');
    if (btn) btn.classList.remove('cal-sleep', 'cal-zzz');
    blinkOnce();
  }

  function twitchInSleep() {
    bumpClass('cal-wiggle', 700);
  }

  function blinkOnce() {
    bumpClass('cal-blink', 140);
  }

  function glanceAway() {
    if (sleeping || thinking) return;
    var ox = rand(-5, 6);
    var oy = rand(-3, 3);
    setEyeOffset(ox, oy);
    setTimeout(function () {
      if (!thinking && !sleeping) setEyeOffset(rand(-2, 2), rand(-1.5, 1.5));
    }, 700);
  }

  function dartEyesTick() {
    if (!thinking) return;
    setEyeOffset(rand(-6, 6), rand(-4, 4));
    dartTO = setTimeout(dartEyesTick, rand(90, 260));
  }

  function runDirector() {
    if (dragState) {
      scheduleDirector(2400);
      return;
    }
    if (thinking) {
      scheduleDirector(rand(1800, 2800));
      return;
    }
    if (sleeping) {
      if (Math.random() < 0.58) wakeFromSleep();
      else twitchInSleep();
      scheduleDirector(rand(3500, 8000));
      return;
    }
    if (!isIdle && Math.random() < 0.55) {
      blinkOnce();
      scheduleDirector(rand(1800, 4200));
      return;
    }
    var roll = Math.random();
    if (roll < 0.18) goSleep();
    else if (roll < 0.36) glanceAway();
    else if (roll < 0.5) bumpClass('cal-bob', 1600);
    else if (roll < 0.64) bumpClass('cal-wiggle', 700);
    else if (roll < 0.78) blinkOnce();
    else if (roll < 0.9) bumpClass('cal-peek', 1400);
    else bumpClass('cal-spark', 1400);
    scheduleDirector(rand(2200, 6200));
  }

  var thinkTO = null;
  function setThinking(on) {
    var btn = document.getElementById('cal-btn');
    if (!btn) return;
    thinking = !!on;
    if (on) {
      wakeFromSleep();
      clearMotionClasses();
      btn.classList.add('cal-thinking');
      clearTimeout(dartTO);
      dartEyesTick();
    } else {
      btn.classList.remove('cal-thinking');
      clearTimeout(dartTO);
      var eyes = document.getElementById('cal-eyes');
      if (eyes) eyes.style.transform = '';
    }
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

  function loadSeen() {
    try { return JSON.parse(localStorage.getItem(SEEN_KEY) || '[]'); } catch (e) { return []; }
  }
  function markSeen(id) {
    var s = loadSeen();
    if (s.indexOf(id) !== -1) return;
    s.push(id);
    if (s.length > MAX_SEEN) s.splice(0, s.length - MAX_SEEN);
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function isSeen(id) { return loadSeen().indexOf(id) !== -1; }
  function conflictId(c) { return c.surgeonId + '-' + c.date + '-' + c.dayOffId; }

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
        '<span class="cal-bot-name">Grok-BOT</span>' +
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
      setTimeout(fetchConflicts, 260);
    });
  }

  function formatMessage(c) {
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

  var ESC_MAP = { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' };
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) { return ESC_MAP[ch]; });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
