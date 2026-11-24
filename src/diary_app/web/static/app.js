/* The one script the app ships. Hand-written ES5: the kitchen iPad runs iOS 9
 * Safari, so no arrow functions, let/const, template literals, fetch, or
 * Element.closest. There is no build step to transpile for us.
 *
 * Why it exists: in an iOS 9 Home Screen (standalone) app, tapping a plain
 * same-origin <a href> opens Safari instead of navigating in place. Guided
 * Access blocks leaving the app, so the tap looks dead. Setting location.href
 * from a click handler keeps the navigation inside the app. Forms are
 * unaffected (plain POST then 303 stays in the app), so they are left alone.
 */
(function () {
  var origin = location.protocol + '//' + location.host;

  function isSameOrigin(href) {
    return href === origin || href.indexOf(origin + '/') === 0;
  }

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
}());
