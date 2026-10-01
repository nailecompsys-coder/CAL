const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/admin_calendar.js'), 'utf8');

function fixture() {
  const requests = [], callbacks = [], pending = [], nodes = {};
  for (const id of ['master-calendar', 'calendar-surgeon', 'calendar-status', 'calendar-scope',
                    'calendar-retry', 'calendar-detail', 'calendar-detail-close']) {
    nodes[id] = {textContent:'', classList:{toggle(){}}, setAttribute(){},
      addEventListener(name, fn) {this[name] = fn;}, close(){}};
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
        value => {result.success=value;}, error => {result.failure=error;}));
    }
    removeAllEvents() {}
    getDate() {return new Date(2026,9,1);}
    render() {}
  }
  vm.runInNewContext(source, {
    document:{querySelector:() => ({dataset:{today:'2026-10-01'}}), getElementById:id => nodes[id]},
    window:{FullCalendar:{Calendar}}, FullCalendar:{Calendar},
    location:{href:'http://localhost/admin/calendar',search:''}, history:{replaceState(){}},
    URL, URLSearchParams, AbortController, Date, matchMedia:() => ({matches:false}),
    fetch:(url, options) => new Promise(resolve => requests.push({url,options,resolve})),
  });
  const respond = (index, entries) => requests[index].resolve({ok:true,
    headers:{get:() => 'application/json'},json:async () => entries});
  return {nodes, requests, callbacks, pending, respond, calendar};
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
