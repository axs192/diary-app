'use strict';
// Runs app.js in a fake browser and prints what happened as JSON, for
// tests/test_app_js_behaviour.py to assert on. Times are UTC (TZ=UTC).
const { makeBrowser, ORIGIN } = require('./browser');

const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const at = (h, m, s) => Date.UTC(2030, 0, 15, h, m || 0, s || 0);
const out = {};

// --- links -----------------------------------------------------------------
{
  const b = makeBrowser({ now: at(10) });
  const a = b.link('/settings');
  const e = b.click(a);
  out.sameOriginLink = { prevented: e.defaultPrevented, to: b.state.navigations };
}
{
  const b = makeBrowser({ now: at(10) });
  const a = b.link('/meals');
  const span = new b.El('span');
  a.appendChild(span);
  const e = b.click(span);
  out.childOfLink = { prevented: e.defaultPrevented, to: b.state.navigations };
}
{
  const b = makeBrowser({ now: at(10) });
  const cases = {
    external: b.link('https://example.org/x'),
    lookalike: b.link(ORIGIN + '.evil.test/x'),
    newTab: b.link('/x', { target: '_blank' }),
    download: b.link('/x.csv', { download: '' }),
    notALink: new b.El('div'),
  };
  out.leftAlone = {};
  Object.keys(cases).forEach((k) => {
    const e = b.click(cases[k]);
    out.leftAlone[k] = e.defaultPrevented;
  });
  out.leftAloneNavigations = b.state.navigations;
}

// --- error banner ------------------------------------------------------------
{
  const b = makeBrowser({ now: at(10) });
  b.window.onerror('boom', ORIGIN + '/static/app.js', 12);
  const shown = b.body.find('js-error');
  const text = shown.length ? shown[0].textContent : '';
  b.window.onerror('second', ORIGIN + '/static/other.js', 7);
  const afterSecond = b.body.find('js-error');
  const dismiss = afterSecond[0].find('js-error-dismiss')[0];
  b.click(dismiss);
  out.banner = {
    count: shown.length, text,
    countAfterSecond: afterSecond.length,
    secondText: afterSecond[0].textContent,
    afterDismiss: b.body.find('js-error').length,
  };
  b.window.onerror('third', ORIGIN + '/static/app.js', 1);
  out.banner.reappears = b.body.find('js-error').length;
}
{
  const b = makeBrowser({ now: at(10), bannerFlag: 'off' });
  out.bannerOff = { handler: typeof b.window.onerror };
}
{
  const calls = [];
  const b = makeBrowser({ now: at(10), previousOnerror: (m) => { calls.push(m); } });
  b.window.onerror('kept', 'x.js', 1);
  out.bannerKeepsPrevious = { calls, shown: b.body.find('js-error').length };
}

// --- reconnecting overlay ----------------------------------------------------
{
  const b = makeBrowser({ now: at(10) });
  b.advance(3 * MIN);
  out.healthy = {
    overlay: b.body.find('reconnecting').length,
    reloads: b.state.reloads,
    pings: b.state.requests.length,
    allHealth: b.state.requests.every((u) => u.indexOf('/health') === 0),
    cacheBusted: new Set(b.state.requests).size === b.state.requests.length,
  };
}
{
  const b = makeBrowser({ now: at(10) });
  b.state.server = 'down';
  b.advance(30 * 1000);
  const first = b.body.find('reconnecting');
  const text = first.length ? first[0].textContent : '';
  b.advance(2 * MIN);
  const stillDown = { overlays: b.body.find('reconnecting').length, reloads: b.state.reloads };
  b.state.server = 'up';
  b.advance(30 * 1000);
  out.outage = { shown: first.length, text, stillDown, reloadsAfterRecovery: b.state.reloads };
}
['timeout', 500].forEach((mode) => {
  const b = makeBrowser({ now: at(10) });
  b.state.server = mode;
  b.advance(30 * 1000);
  out['outage_' + mode] = b.body.find('reconnecting').length;
});

// --- scheduled reloads ---------------------------------------------------------
function firstReload(startH, startM, startS) {
  const b = makeBrowser({ now: at(startH, startM, startS) });
  const start = b.clock.now;
  let elapsed = 0;
  while (b.state.reloads === 0 && elapsed < 30 * HOUR) {
    b.advance(30 * 1000);
    elapsed += 30 * 1000;
  }
  return { afterMs: elapsed, utcHour: new Date(start + elapsed).getUTCHours() };
}
out.reloadFrom10 = firstReload(10);    // 6 h rule -> 16:00
out.reloadFrom22 = firstReload(22);    // 03:00 comes first
out.reloadFrom01 = firstReload(1);     // 03:00 comes first
out.reloadFromJustAfter3 = firstReload(3, 0, 10); // next 03:00 is 24 h away -> 6 h rule
{
  const b = makeBrowser({ now: at(10) });
  b.fire('input', {});                       // someone types at 10:00
  b.advance(6 * HOUR - 4 * MIN);             // 15:56, the reload is due at 16:00
  b.fire('input', {});                       // types again at 15:56
  b.advance(4 * MIN);                        // 16:00: edited 4 min ago
  const deferred = b.state.reloads;
  b.advance(2 * MIN);                        // 16:02: idle for over 5 min
  out.typing = { deferred, after: b.state.reloads };
}
{
  const b = makeBrowser({ now: at(22) });
  b.state.server = 'down';
  b.advance(6 * HOUR);                       // past 03:00 with the server down
  const whileDown = b.state.reloads;
  b.state.server = 'up';
  b.advance(30 * 1000);
  out.reloadWaitsForServer = { whileDown, afterRecovery: b.state.reloads };
}

// --- Meals library tabs ----------------------------------------------------------
const WEEK = '2030-01-07';
const frag = (tab) => '/meals/library?week=' + WEEK + '&tab=' + tab;
const currentTab = (tabs) => Object.keys(tabs).filter(
  (k) => tabs[k].getAttribute('aria-current') === 'page');
{
  const b = makeBrowser({ now: at(10) });
  const { tabs, list } = b.tabsPage(WEEK);
  b.state.responses[frag('favourites')] = { body: '<ul>FAVOURITES</ul>' };
  const e = b.click(tabs.favourites);
  const during = { busy: list.className.indexOf('lib-busy') !== -1,
    html: list.innerHTML };
  b.advance(1);
  out.tabSwap = {
    prevented: e.defaultPrevented, navigations: b.state.navigations,
    requested: b.state.requests.filter((u) => u.indexOf('/meals/') === 0),
    during, html: list.innerHTML,
    busyAfter: list.className.indexOf('lib-busy') !== -1,
    current: currentTab(tabs),
  };
}
{
  const b = makeBrowser({ now: at(10) });
  const { tabs, list } = b.tabsPage(WEEK);
  const span = new b.El('span');
  tabs.mine.appendChild(span);
  b.state.responses[frag('mine')] = { body: '<ul>MINE</ul>' };
  b.click(span);                      // a tap on something inside the tab
  b.advance(1);
  out.tabChild = { html: list.innerHTML, current: currentTab(tabs) };
}
['down', 'timeout'].concat([500]).forEach((fail) => {
  const b = makeBrowser({ now: at(10) });
  const { tabs, list } = b.tabsPage(WEEK);
  b.state.responses[frag('mine')] = typeof fail === 'number'
    ? { status: fail, body: 'oops' } : { mode: fail };
  b.click(tabs.mine);
  b.advance(1);
  out['tabFails_' + fail] = {
    navigations: b.state.navigations, html: list.innerHTML,
    current: currentTab(tabs),
    busyAfter: list.className.indexOf('lib-busy') !== -1,
  };
});
{
  const b = makeBrowser({ now: at(10) });
  const { tabs, list } = b.tabsPage(WEEK);
  b.state.responses[frag('favourites')] = { body: '<ul>SLOW</ul>', delay: 2000 };
  b.state.responses[frag('mine')] = { body: '<ul>FAST</ul>', delay: 100 };
  b.click(tabs.favourites);
  b.click(tabs.mine);
  b.advance(3000);
  out.tabStale = { html: list.innerHTML, current: currentTab(tabs),
    busyAfter: list.className.indexOf('lib-busy') !== -1 };
}
{
  const b = makeBrowser({ now: at(10) });
  b.tabsPage(WEEK);
  const other = b.link('/settings');
  const e = b.click(other);
  out.tabsPageOtherLink = { prevented: e.defaultPrevented, to: b.state.navigations };
}

process.stdout.write(JSON.stringify(out));
