'use strict';
// A tiny fake browser for running static/app.js under Node in tests. Only the
// browser boundary is faked (DOM, timers, clock, XMLHttpRequest, location);
// app.js itself is the real file. This file is test tooling and is never
// served, so it may use modern JavaScript.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ORIGIN = 'http://diary.test:8000';
const APP_JS = path.join(
  __dirname, '..', '..', 'src', 'diary_app', 'web', 'static', 'app.js');

class El {
  constructor(tag) {
    this.nodeName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.parentNode = null;
    this.className = '';
    this.ownText = '';
  }
  get textContent() {
    return this.ownText + this.children.map((c) => c.textContent).join('');
  }
  set textContent(v) { this.ownText = String(v); this.children = []; }
  get href() {
    const h = this.attrs.href;
    if (h === undefined) return '';
    return h.charAt(0) === '/' ? ORIGIN + h : h;
  }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) {
    this.children = this.children.filter((x) => x !== c);
    c.parentNode = null;
    return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  hasAttribute(k) { return k in this.attrs; }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  find(className) {
    const out = [];
    const walk = (n) => {
      if (n.className.split(' ').indexOf(className) !== -1) out.push(n);
      n.children.forEach(walk);
    };
    walk(this);
    return out;
  }
}

function makeBrowser(opts) {
  const clock = { now: opts.now };
  const timers = [];
  let nextId = 1;
  const state = {
    server: 'up', // 'up' | 'down' | 'timeout' | a status number
    requests: [],
    reloads: 0,
    navigations: [],
  };

  class FakeDate extends Date {
    constructor(...args) {
      if (args.length) super(...args); else super(clock.now);
    }
    static now() { return clock.now; }
  }

  function addTimer(fn, ms, repeat) {
    const t = { id: nextId++, fn, due: clock.now + ms, ms, repeat };
    timers.push(t);
    return t.id;
  }
  function clearTimer(id) {
    const i = timers.findIndex((t) => t.id === id);
    if (i !== -1) timers.splice(i, 1);
  }

  class FakeXHR {
    open(method, url) { this.method = method; this.url = url; }
    send() {
      state.requests.push(this.url);
      const s = state.server;
      addTimer(() => {
        if (s === 'down') { if (this.onerror) this.onerror(); }
        else if (s === 'timeout') { if (this.ontimeout) this.ontimeout(); }
        else {
          this.status = s === 'up' ? 200 : s;
          if (this.onload) this.onload();
        }
      }, 0, false);
    }
  }

  const body = new El('body');
  if (opts.bannerFlag !== undefined) {
    body.setAttribute('data-error-banner', opts.bannerFlag);
  }
  const document = {
    body,
    listeners: {},
    addEventListener(type, fn) {
      (this.listeners[type] = this.listeners[type] || []).push(fn);
    },
    createElement: (tag) => new El(tag),
  };
  const location = {
    protocol: 'http:',
    host: 'diary.test:8000',
    reload() { state.reloads += 1; },
    set href(v) { state.navigations.push(v); },
    get href() { return ORIGIN + '/home'; },
  };
  const sandbox = {
    document, location, Date: FakeDate, XMLHttpRequest: FakeXHR,
    setTimeout: (fn, ms) => addTimer(fn, ms, false),
    setInterval: (fn, ms) => addTimer(fn, ms, true),
    clearTimeout: clearTimer, clearInterval: clearTimer,
  };
  sandbox.window = sandbox;
  if (opts.previousOnerror) sandbox.onerror = opts.previousOnerror;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(APP_JS, 'utf8'), sandbox, { filename: 'app.js' });

  function advance(ms) {
    const end = clock.now + ms;
    for (;;) {
      timers.sort((a, b) => a.due - b.due || a.id - b.id);
      const t = timers[0];
      if (!t || t.due > end) break;
      clock.now = t.due;
      if (t.repeat) t.due += t.ms; else timers.shift();
      t.fn();
    }
    clock.now = end;
  }

  function fire(type, event) {
    (document.listeners[type] || []).forEach((fn) => fn(event));
  }
  function click(target) {
    const event = {
      target, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
    };
    // Bubble like a browser: the element, its ancestors, then the document.
    for (let n = target; n; n = n.parentNode) {
      (n.listeners.click || []).forEach((fn) => fn(event));
    }
    fire('click', event);
    return event;
  }
  function link(href, attrs) {
    const a = new El('a');
    a.setAttribute('href', href);
    Object.keys(attrs || {}).forEach((k) => a.setAttribute(k, attrs[k]));
    body.appendChild(a);
    return a;
  }

  return { state, body, window: sandbox, advance, fire, click, link, El, clock };
}

module.exports = { makeBrowser, ORIGIN };
