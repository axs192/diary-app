/* The one script the app ships. Hand-written ES5: the kitchen iPad runs iOS 9
 * Safari, so no arrow functions, let/const, template literals, fetch, or
 * Element.closest. There is no build step to transpile for us.
 *
 * It does three jobs, each small and independent:
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

  // --- 1. Links -----------------------------------------------------------

  document.addEventListener('click', function (e) {
    var a = e.target;
    while (a && a.nodeName !== 'A') {
      a = a.parentNode;
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
