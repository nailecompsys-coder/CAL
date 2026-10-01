const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/admin_calendar.js'), 'utf8');

function fixture() {
  const requests = [], callbacks = [], pending = [], nodes = {};
  const timers = [], mutations = [], store = new Map(), listeners = {}, pageListeners = {};
  let now = 0;
  class Clock extends Date { static now() {return now;} }
  const main = {scrollTop:320};
  for (const id of ['master-calendar', 'calendar-surgeon', 'calendar-status', 'calendar-scope',
                    'calendar-retry', 'calendar-detail', 'calendar-detail-close']) {
    nodes[id] = {textContent:'', classList:{toggle(){}}, setAttribute(){},
      addEventListener(name, fn) {this[name] = fn;}, close(){}, querySelector(){return null;}, contains(){return false;}};
  }
  const select = nodes['calendar-surgeon'];
  select.value = '';
  select.options = [{value:'',textContent:'All clinicians'},{value:'1',textContent:'Dr. Florin'}];
  Object.defineProperty(select, 'selectedOptions', {get:() => select.options.filter(o => o.value === select.value)});
  let calendar;
  class Calendar {
    constructor(host, options) {
      calendar = this; this.options = options; this.view = {type:'dayGridMonth'};
      // FullCalendar may start fetching in its constructor, before the outer
      // `calendar` binding receives the instance. This broke direct page reloads.
      this.refetchEvents();
    }
    refetchEvents() {
      const result = {success:null, failure:null}; callbacks.push(result);
      pending.push(this.options.events({startStr:'2026-10-01',endStr:'2026-11-01'},
        value => {result.success=value; value.forEach(row => store.set(String(row.id),row));}, error => {result.failure=error;}));
    }
    removeAllEvents() {mutations.push('clear'); store.clear();}
    getEventSources() {return [{id:'feed'}];}
    getEventById(id) {return store.has(id) ? {remove:() => {mutations.push(`remove:${id}`);store.delete(id);}} : null;}
    addEvent(row) {mutations.push(`add:${row.id}`);store.set(String(row.id),row);}
    batchRendering(fn) {mutations.push('batch');fn();}
    getDate() {return new Date(2026,9,1);}
    render() {}
  }
  const document = {hidden:false,querySelector:selector => selector === 'main' ? main : ({dataset:{today:'2026-10-01'}}),
    getElementById:id => nodes[id],addEventListener:(name,fn) => {listeners[name]=fn;}};
  vm.runInNewContext(source, {
    document,
    window:{FullCalendar:{Calendar},addEventListener:(name,fn) => {pageListeners[name]=fn;}}, FullCalendar:{Calendar},
    location:{href:'http://localhost/admin/calendar',search:''}, history:{replaceState(){}},
    URL, URLSearchParams, AbortController, Date:Clock, matchMedia:() => ({matches:false}),
    setInterval:fn => {timers.push(fn);return timers.length;}, clearInterval(){},
    fetch:(url, options) => new Promise(resolve => requests.push({url,options,resolve})),
  });
  const respond = (index, entries) => requests[index].resolve({ok:true,
    headers:{get:() => 'application/json'},json:async () => entries});
  const tick = () => {now+=60000;return timers.at(-1)();};
  return {nodes, requests, callbacks, pending, respond, calendar, mutations,store,tick,document,main,listeners,pageListeners};
}

test('direct page load fetches and finishes before a user changes filters', async () => {
  const f=fixture(); assert.equal(f.requests.length,1);
  f.respond(0,[{id:'one'}]); await f.pending[0];
  assert.equal(f.callbacks[0].success.length,1);
  assert.match(f.nodes['calendar-status'].textContent,/1 schedule entries/);
});

test('rapid doctor selection aborts the old request and an empty result stays empty', async () => {
  const f=fixture();
  f.nodes['calendar-surgeon'].value='1'; f.nodes['calendar-surgeon'].change();
  assert.equal(f.requests[0].options.signal.aborted,true);
  assert.match(f.requests[1].url,/surgeon_id=1/);
  f.respond(1,[]); await f.pending[1];
  f.respond(0,[{id:'other-doctor'}]); await f.pending[0];
  assert.equal(f.callbacks[0].success.length,0);
  assert.equal(f.callbacks[1].success.length,0);
  assert.equal(f.nodes['calendar-status'].textContent,'No scheduled events in this date range.');
});

test('a failed feed shows retry instead of claiming the calendar is empty', async () => {
  const f=fixture();
  f.requests[0].resolve({ok:false,headers:{get:()=>'text/html'}});
  await f.pending[0];
  assert.ok(f.callbacks[0].failure);
  assert.equal(f.nodes['calendar-retry'].hidden,false);
  assert.match(f.nodes['calendar-status'].textContent,/could not load/);
});

test('unchanged background response performs no calendar mutations', async () => {
  const f=fixture(); const row={id:'one',title:'Clinic'};
  f.respond(0,[row]); await f.pending[0]; f.mutations.length=0;
  const before=f.store.get('one');
  const update=f.tick(); f.respond(1,[{...row}]); await update;
  assert.deepEqual(f.mutations,[]);
  assert.equal(f.store.get('one'),before);
  assert.equal(f.main.scrollTop,320);
});

test('changed, added, and removed records are patched without clearing unchanged entries', async () => {
  const f=fixture(); f.respond(0,[{id:'steady'},{id:'edit',title:'Old'},{id:'remove'}]); await f.pending[0];
  f.mutations.length=0;const before=f.store.get('steady');
  const update=f.tick(); f.respond(1,[{id:'steady'},{id:'edit',title:'New'},{id:'new'}]); await update;
  assert.deepEqual(f.mutations,['batch','remove:remove','remove:edit','add:edit','add:new']);
  assert.equal(f.store.get('steady'),before);
  assert.equal(f.store.get('edit').title,'New');assert.equal(f.main.scrollTop,320);
});

test('background failure keeps the last good schedule and retry recovers', async () => {
  const f=fixture();f.respond(0,[{id:'one'}]);await f.pending[0];f.mutations.length=0;
  const update=f.tick();f.requests[1].resolve({ok:false});await update;
  assert.equal(f.store.has('one'),true);assert.deepEqual(f.mutations,[]);
  assert.match(f.nodes['calendar-status'].textContent,/last loaded schedule/);
  const retry=f.nodes['calendar-retry'].onclick();f.respond(2,[{id:'one'}]);await retry;
  assert.equal(f.nodes['calendar-retry'].hidden,true);
});

test('hidden tabs and open details pause polling; details opened in flight defer updates', async () => {
  const f=fixture();f.respond(0,[{id:'one'}]);await f.pending[0];f.mutations.length=0;
  f.document.hidden=true;await f.tick();assert.equal(f.requests.length,1);
  f.document.hidden=false;f.nodes['calendar-detail'].open=true;await f.tick();assert.equal(f.requests.length,1);
  f.nodes['calendar-detail'].open=false;const update=f.tick();
  f.nodes['calendar-detail'].open=true;f.respond(1,[{id:'changed'}]);await update;
  assert.deepEqual(f.mutations,[]);assert.equal(f.store.has('one'),true);
  f.nodes['calendar-detail'].open=false;const resume=f.tick();f.respond(2,[{id:'changed'}]);await resume;
  assert.equal(f.store.has('changed'),true);
});

test('old background results cannot overwrite a newly selected doctor', async () => {
  const f=fixture();f.respond(0,[{id:'old'}]);await f.pending[0];
  const update=f.tick();
  f.nodes['calendar-surgeon'].value='1';f.nodes['calendar-surgeon'].change();
  assert.equal(f.requests[1].options.signal.aborted,true);
  f.respond(2,[{id:'new-doctor'}]);await f.pending[1];f.mutations.length=0;
  f.respond(1,[{id:'stale'}]);await update;
  assert.deepEqual(f.mutations,[]);assert.equal(f.store.has('stale'),false);
  assert.equal(f.store.has('new-doctor'),true);
});

test('failed date navigation cannot background-load the previous scope', async () => {
  const f=fixture();f.respond(0,[{id:'old'}]);await f.pending[0];
  const navigation=f.calendar.options.events({startStr:'2026-11-01',endStr:'2026-12-01'},()=>{},()=>{});
  f.requests[1].resolve({ok:false});await navigation;
  await f.tick();assert.equal(f.requests.length,2);assert.equal(f.store.size,0);
});

test('background checks do not overlap and stop on navigation away', async () => {
  const f=fixture();f.respond(0,[{id:'one'}]);await f.pending[0];
  const update=f.tick();await f.tick();assert.equal(f.requests.length,2);
  f.pageListeners.pagehide();assert.equal(f.requests[1].options.signal.aborted,true);
  f.respond(1,[{id:'stale'}]);await update;
  await f.tick();assert.equal(f.requests.length,2);assert.equal(f.store.has('stale'),false);
  f.pageListeners.pageshow({persisted:true});assert.equal(f.requests.length,3);
  f.respond(2,[{id:'one'}]);
});

test('replacing a keyboard-focused event restores focus without scrolling', async () => {
  const f=fixture();f.respond(0,[{id:'one',title:'Old'}]);await f.pending[0];
  const focused={dataset:{calendarEventId:'one'},isConnected:false};
  f.document.activeElement={closest:() => focused};
  f.nodes['master-calendar'].contains=() => true;
  let focusOptions;
  f.nodes['master-calendar'].querySelectorAll=() => [{dataset:{calendarEventId:'one'},focus:options => {focusOptions=options;}}];
  const update=f.tick();f.respond(1,[{id:'one',title:'New'}]);await update;
  assert.equal(focusOptions.preventScroll,true);assert.equal(f.main.scrollTop,320);
});

test('calendar opt-out prevents the shared whole-page refresh timer', () => {
  const base=fs.readFileSync(path.join(__dirname,'../app/templates/base_admin.html'),'utf8');
  const script=base.slice(base.indexOf('(function adminQuietRefresh()'),base.indexOf('</script>',base.indexOf('(function adminQuietRefresh()')));
  vm.runInNewContext(script,{document:{querySelector:selector => selector === '[data-calendar-live]' ? {} : null},
    setInterval(){throw new Error('Whole-page timer must not run for the calendar');}});
});
