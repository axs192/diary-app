/* The one script the app ships. Hand-written ES5: the kitchen iPad runs iOS 9
 * Safari, so no arrow functions, let/const, template literals, fetch, or
 * Element.closest. There is no build step to transpile for us.
 *
 * It does six jobs, each small and independent:
 *
 * 1. Links. In an iOS 9 Home Screen (standalone) app, tapping a plain
 *    same-origin <a href> opens Safari instead of navigating in place. Guided
 *    Access blocks leaving the app, so the tap looks dead. Setting
 *    location.href from a click handler keeps the navigation in the app.
 *    Forms are unaffected (plain POST then 303 stays in the app).
 *
 * 2. Self-healing, for a screen that is left on 24/7. Every 30 seconds it asks
 *    the server /health. If that fails it covers the page with "Reconnecting"
 *    and keeps asking, then reloads once the server answers (Safari's own
 *    error page would otherwise sit there until someone touched the iPad).
 *    It also reloads the page 6 hours after loading, or at 3 am if that comes
 *    first, to shed any memory built up. A reload waits while someone is
 *    typing.
 *
 * 3. Errors. The iPad has no Web Inspector, so a script error shows in a small
 *    dismissible banner (message, file, line). <body data-error-banner="off">
 *    turns this off (the ERROR_BANNER setting on the server).
 *
 * 4. Meals tabs. Ideas / Favourites / My meals are real links, but a full
 *    page load of the long Meals page flashes black on the iPad while it
 *    paints. A tab with data-fragment fetches just the list and swaps it into
 *    #library-list instead, falling back to the normal link if that fails.
 *
 * 5. In-place forms. A tap on a submit button in a form with
 *    data-swap="<id>" posts the form in the background with _fragment=1; the
 *    server answers with just that part of the page, which replaces the
 *    element <id>. The page keeps its scroll position and does not flash.
 *    Without this script the same form is a normal post and 303 redirect.
 *    <details id=".."> sections that were open stay open across the swap,
 *    so ticking an item does not close the aisle being worked through.
 *
 * 6. Select-all text boxes, for copying a list on iOS 9 (see below).
 */
(function () {
  var POLL_MS = 30000;
  var PING_TIMEOUT_MS = 8000;
  var RELOAD_AFTER_MS = 6 * 60 * 60 * 1000;
  var NIGHT_HOUR = 3;
  var TYPING_GRACE_MS = 5 * 60 * 1000;

  var origin = location.protocol + '//' + location.host;

  function isSameOrigin(href) {
    return href === origin || href.indexOf(origin + '/') === 0;
  }

  function make(tag, className, text) {
    var el = document.createElement(tag);
    el.className = className;
    if (text) {
      el.textContent = text;
    }
    return el;
  }

  function hasClass(el, name) {
    return (' ' + el.className + ' ').indexOf(' ' + name + ' ') !== -1;
  }

  function addClass(el, name) {
    if (!hasClass(el, name)) {
      el.className = el.className ? el.className + ' ' + name : name;
    }
  }

  function removeClass(el, name) {
    el.className = (' ' + el.className + ' ').replace(' ' + name + ' ', ' ')
      .replace(/^\s+|\s+$/g, '');
  }

  // --- 4 and 5. Swapping part of the page --------------------------------

  var swapCount = 0; // which tap is current, so a late answer can be ignored

  // Which <details id=".."> sections inside `target` are open right now, as
  // { id: true|false }. Sections without an id cannot be told apart, so they
  // are skipped.
  function openSections(target) {
    var found = {};
    var all = target.getElementsByTagName('details');
    for (var i = 0; i < all.length; i++) {
      var id = all[i].getAttribute('id');
      if (id) {
        found[id] = !!all[i].open;
      }
    }
    return found;
  }

  // Puts sections back as the user left them. Ones the server just added are
  // left as the server drew them. Without this, every swap would snap an
  // aisle the user is working through shut again.
  function restoreSections(target, sections) {
    var all = target.getElementsByTagName('details');
    for (var i = 0; i < all.length; i++) {
      var id = all[i].getAttribute('id');
      if (id && sections.hasOwnProperty(id)) {
        all[i].open = sections[id];
      }
    }
  }

  // Sends a request and puts the answer into `target`, dimming it (busyClass)
  // meanwhile. On an error status, a timeout or no connection it calls
  // failed() instead; done() runs after a successful swap. An answer to an
  // earlier tap that arrives after a later one is dropped.
  function swapInto(target, busyClass, method, url, body, failed, done) {
    var mine = ++swapCount;
    addClass(target, busyClass);

    function fail() {
      if (mine === swapCount) {
        removeClass(target, busyClass);
        failed();
      }
    }

    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    xhr.timeout = 15000;
    xhr.onload = function () {
      if (mine !== swapCount) {
        return; // a later tap has taken over
      }
      if (xhr.status !== 200) {
        fail();
        return;
      }
      var sections = openSections(target);
      target.innerHTML = xhr.responseText;
      restoreSections(target, sections);
      removeClass(target, busyClass);
      if (done) {
        done();
      }
    };
    xhr.onerror = fail;
    xhr.ontimeout = fail;
    xhr.send(body);
  }

  // --- 4. Meals tabs ------------------------------------------------------

  function markCurrent(tab) {
    var tabs = tab.parentNode.children;
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].getAttribute('data-fragment')) {
        tabs[i].removeAttribute('aria-current');
      }
    }
    tab.setAttribute('aria-current', 'page');
  }

  // Swaps the library list for the one at `url`. If that cannot be done, the
  // tab does what it always did: load the whole page.
  function swapLibrary(tab, url) {
    var list = document.getElementById('library-list');
    if (!list) {
      location.href = tab.href;
      return;
    }
    swapInto(list, 'lib-busy', 'GET', url, null, function () {
      location.href = tab.href;
    }, function () {
      markCurrent(tab);
    });
  }

  // --- 5. In-place forms --------------------------------------------------

  // The submit button a tap landed on (or inside), or null.
  function submitButton(el) {
    while (el && el.nodeName !== 'BUTTON') {
      el = el.parentNode;
    }
    if (!el || (el.getAttribute('type') || 'submit') !== 'submit') {
      return null;
    }
    return el;
  }

  // Posts the button's form in the background and swaps the server's
  // fragment into the element named by the form's data-swap. Returns false,
  // and does nothing, when the form is not one of those.
  function submitInPlace(button) {
    var form = button.form;
    var targetId = form && form.getAttribute('data-swap');
    var target = targetId && document.getElementById(targetId);
    if (!target) {
      return false;
    }
    var data = new FormData(form);
    if (button.getAttribute('name')) {
      // Safari 9 has no SubmitEvent.submitter, so add the tapped button.
      data.append(button.getAttribute('name'), button.getAttribute('value') || '');
    }
    data.append('_fragment', '1');
    var url = button.getAttribute('formaction') || form.getAttribute('action');
    // On failure reload rather than resubmit: the post may already have
    // reached the server, and sending a toggle twice would undo it.
    swapInto(target, 'swap-busy', 'POST', url, data, function () {
      location.reload();
    });
    return true;
  }

  // --- 1. Links -----------------------------------------------------------

  document.addEventListener('click', function (e) {
    var button = submitButton(e.target);
    if (button && submitInPlace(button)) {
      e.preventDefault();
      return;
    }
    var a = e.target;
    while (a && a.nodeName !== 'A') {
      a = a.parentNode;
    }
    if (a && a.getAttribute('data-fragment')) {
      e.preventDefault();
      swapLibrary(a, a.getAttribute('data-fragment'));
      return;
    }
    if (!a || !a.href || !isSameOrigin(a.href)) {
      return; // not a link, or an external one: leave it alone
    }
    if (a.hasAttribute('download') || a.getAttribute('target') === '_blank') {
      return;
    }
    e.preventDefault();
    location.href = a.href;
  }, false);

  // --- 6. Select-all text boxes -------------------------------------------

  // iOS 9 cannot copy from script (no execCommand('copy')), so a box marked
  // data-select-all selects its text when tapped, ready for a long-press Copy.
  // Focus does not bubble, hence the capture listener.
  document.addEventListener('focus', function (e) {
    var box = e.target;
    if (box && box.getAttribute && box.getAttribute('data-select-all') !== null) {
      box.setSelectionRange(0, box.value.length);
    }
  }, true);

  // --- 3. Errors ----------------------------------------------------------

  var banner = null;

  function showError(message, file, line) {
    var where = String(file || '').replace(origin, '') + ':' + line;
    var text = message + ' (' + where + ')';
    if (!banner) {
      banner = make('div', 'js-error');
      banner.appendChild(make('span', 'js-error-text'));
      var dismiss = make('button', 'js-error-dismiss', 'Dismiss');
      dismiss.setAttribute('type', 'button');
      dismiss.addEventListener('click', function () {
        document.body.removeChild(banner);
        banner = null;
      }, false);
      banner.appendChild(dismiss);
      document.body.appendChild(banner);
    }
    banner.children[0].textContent = text;
  }

  if (document.body.getAttribute('data-error-banner') !== 'off') {
    var previousOnError = window.onerror;
    window.onerror = function (message, file, line) {
      showError(message, file, line);
      if (typeof previousOnError === 'function') {
        return previousOnError.apply(this, arguments);
      }
      return false;
    };
  }

  // --- 2. Self-healing ----------------------------------------------------

  var overlay = null;
  var lastEdit = 0;

  function showReconnecting() {
    if (overlay) {
      return;
    }
    overlay = make('div', 'reconnecting');
    overlay.setAttribute('role', 'alert');
    overlay.appendChild(make('p', 'reconnecting-title', 'Reconnecting…'));
    overlay.appendChild(make('p', 'reconnecting-note',
      'Waiting for the diary to come back.'));
    document.body.appendChild(overlay);
  }

  // Calls done(true) if the server answers 200, done(false) for anything
  // else (no connection, timeout, error status). XHR, not fetch: iOS 9.
  function pingServer(done) {
    var finished = false;
    function finish(ok) {
      if (!finished) {
        finished = true;
        done(ok);
      }
    }
    var xhr = new XMLHttpRequest();
    // A changing query string stops iOS 9 serving a cached answer.
    xhr.open('GET', '/health?t=' + new Date().getTime(), true);
    xhr.timeout = PING_TIMEOUT_MS;
    xhr.onload = function () {
      finish(xhr.status === 200);
    };
    xhr.onerror = function () {
      finish(false);
    };
    xhr.ontimeout = function () {
      finish(false);
    };
    xhr.send();
  }

  // The next time to refresh: 6 hours from `now`, or the next 3 am if sooner.
  function nextReloadAt(now) {
    var night = new Date(now);
    night.setHours(NIGHT_HOUR, 0, 0, 0);
    if (night.getTime() <= now) {
      night.setDate(night.getDate() + 1);
    }
    return Math.min(now + RELOAD_AFTER_MS, night.getTime());
  }

  var reloadAt = nextReloadAt(new Date().getTime());

  function noteEdit() {
    lastEdit = new Date().getTime();
  }
  document.addEventListener('input', noteEdit, false);
  document.addEventListener('change', noteEdit, false);

  function someoneIsTyping(now) {
    return now - lastEdit < TYPING_GRACE_MS;
  }

  function poll() {
    pingServer(function (up) {
      var now = new Date().getTime();
      if (!up) {
        showReconnecting();
      } else if (overlay) {
        location.reload(); // it was down and is back
      } else if (now >= reloadAt && !someoneIsTyping(now)) {
        location.reload();
      }
    });
  }

  setInterval(poll, POLL_MS);
}());
