// Scroll memory — restores your place when you come back to a page:
// closing a viewer (its "Back to …" link), the browser Back/Forward
// button, a same-page reload, a POST-redirect to the same list, or
// returning from a share composer. Fresh visits (homepage links,
// grid -> subject, first open of a viewer) always start at the top.
(function () {
  var PREFIX = "studyhub:scroll:";
  var ALLOW = "studyhub:scroll-allow:";
  // Viewer pages use the same logic as every other page; the only
  // difference is that .viewer-main can be a second scroll container,
  // so its position is saved alongside the window position.
  function mainScroller() {
    return document.getElementById("viewer-main");
  }

  function keyFor(path) {
    return PREFIX + path;
  }
  function allowFor(path) {
    return ALLOW + path;
  }
  function currentKey() {
    return keyFor(location.pathname);
  }
  function readSaved(raw) {
    // Current format: JSON {"y": <windowY>, "main": <viewerMainY>} —
    // older tabs stored a bare int (window Y only).
    try {
      var obj = JSON.parse(raw);
      if (obj && typeof obj === "object" && typeof obj.y === "number" && isFinite(obj.y)) {
        return {
          y: obj.y,
          main: typeof obj.main === "number" && isFinite(obj.main) ? obj.main : 0,
        };
      }
    } catch (e) {}
    var n = parseInt(raw, 10);
    return isFinite(n) ? { y: n, main: 0 } : null;
  }
  function getSaved(path) {
    try {
      var v = sessionStorage.getItem(keyFor(path));
      if (v == null) return null;
      var s = readSaved(v);
      return s && s.y > 0 ? s : null;
    } catch (e) {
      return null;
    }
  }
  function hasAllow(path) {
    try {
      return sessionStorage.getItem(allowFor(path)) === "1";
    } catch (e) {
      return false;
    }
  }
  function setAllow(path) {
    try {
      sessionStorage.setItem(allowFor(path), "1");
    } catch (e) {}
  }
  function consumeAllow(path) {
    try {
      sessionStorage.removeItem(allowFor(path));
    } catch (e) {}
  }
  function clearPath(path) {
    try {
      sessionStorage.removeItem(keyFor(path));
      sessionStorage.removeItem(allowFor(path));
    } catch (e) {}
  }

  // Destinations that imply "I will come back": any viewer / share composer.
  function isViewerDest(path) {
    return (
      path.indexOf("/viewer/") === 0 ||
      path.indexOf("/shared/combined") === 0 ||
      path.indexOf("/share/") === 0 ||
      /^\/shared\/\d+\//.test(path)
    );
  }

  function navType() {
    try {
      var entries = performance.getEntriesByType("navigation");
      return entries && entries[0] ? entries[0].type : null;
    } catch (e) {
      return null;
    }
  }
  function referrerPath() {
    try {
      if (!document.referrer) return null;
      var u = new URL(document.referrer, location.origin);
      if (u.origin !== location.origin) return null;
      return u.pathname;
    } catch (e) {
      return null;
    }
  }

  // Helper for programmatic navigations (window.location.href) to a viewer:
  // call before leaving so the return trip restores this page's position.
  // Pass the destination URL to arm only for viewer/share destinations;
  // call with no argument to arm unconditionally.
  try {
    window.__studyhubArmReturn = function (destUrl) {
      if (destUrl && typeof destUrl === "string") {
        try {
          var u = new URL(destUrl, location.origin);
          if (u.origin !== location.origin || !isViewerDest(u.pathname)) return;
        } catch (e) {
          return;
        }
      }
      save();
      setAllow(location.pathname);
    };
  } catch (e) {}

  try {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  } catch (e) {}

  // Restore ONLY when: returning from a viewer (explicit allow flag),
  // using the browser Back/Forward buttons, reloading the same page
  // (F5 / add-delete POST reload), or arriving from the exact same URL
  // (form POST-redirect back to the list).
  // Fresh visits from homepage / grid / other pages start at the top.
  function shouldRestore() {
    if (location.hash) return false;
    if (hasAllow(location.pathname)) return true;
    if (navType() === "back_forward") return true;
    if (navType() === "reload") return true;
    var ref = referrerPath();
    if (ref && ref === location.pathname) return true;
    return false;
  }

  function instantScrollTo(y) {
    var root = document.documentElement;
    var prev = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    try {
      window.scrollTo({ top: y, behavior: "auto" });
    } catch (e) {
      window.scrollTo(0, y);
    }
    root.style.scrollBehavior = prev;
  }

  // Restores must never fight the user: any manual scroll gesture cancels
  // the remaining retries immediately.
  var restoreTimer = null;
  var restoreCancelled = false;
  function cancelRestore() {
    if (!restoreTimer) return;
    restoreCancelled = true;
    clearInterval(restoreTimer);
    restoreTimer = null;
  }
  ["wheel", "touchstart", "pointerdown", "keydown"].forEach(function (type) {
    window.addEventListener(type, cancelRestore, { passive: true });
  });

  function applyTo(y, mainY) {
    instantScrollTo(y);
    var main = mainScroller();
    if (main) {
      try {
        var capped = typeof mainY === "number" ? mainY : 0;
        capped = Math.min(capped, Math.max(0, main.scrollHeight - main.clientHeight));
        if (Math.abs((main.scrollTop || 0) - capped) > 1) main.scrollTop = capped;
      } catch (e) {}
    }
  }

  function restore() {
    restoreCancelled = false;
    if (restoreTimer) {
      clearInterval(restoreTimer);
      restoreTimer = null;
    }
    if (!shouldRestore()) {
      // Fresh visit — drop any stale position so a later reload starts top.
      clearPath(location.pathname);
      return;
    }
    var s = getSaved(location.pathname);
    if (s == null) {
      consumeAllow(location.pathname);
      return;
    }
    consumeAllow(location.pathname);
    applyTo(s.y, s.main);
    // Retry briefly — dashboard topics/shared rows render async, so the
    // page height grows after DOMContentLoaded and clamps the first jump.
    // Stops at once if the user starts scrolling on their own.
    var attempts = 0;
    var maxAttempts = 14;
    restoreTimer = setInterval(function () {
      attempts += 1;
      try {
        var max = document.documentElement.scrollHeight - window.innerHeight;
        var target = Math.min(s.y, Math.max(0, max));
        if (
          !restoreCancelled &&
          target > 0 &&
          Math.abs((window.scrollY || 0) - target) > 2
        ) {
          applyTo(target, s.main);
        }
      } catch (e) {}
      if (restoreCancelled || attempts >= maxAttempts) {
        clearInterval(restoreTimer);
        restoreTimer = null;
        // Re-save the settled position so a follow-up reload keeps it.
        if (!restoreCancelled) {
          save();
        }
      }
    }, 200);
  }

  function save() {
    try {
      var main = mainScroller();
      sessionStorage.setItem(
        currentKey(),
        JSON.stringify({
          y: window.scrollY || window.pageYOffset || 0,
          main: main ? main.scrollTop || 0 : 0,
        })
      );
    } catch (e) {}
  }

  var ticking = false;
  function saveThrottled() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      save();
      ticking = false;
    });
  }

  window.addEventListener("scroll", saveThrottled, { passive: true });
  // The viewer can also scroll its .viewer-main container — remember it too.
  var mainScrollerEl = mainScroller();
  if (mainScrollerEl) {
    mainScrollerEl.addEventListener("scroll", saveThrottled, { passive: true });
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") save();
  });
  window.addEventListener("pagehide", save);

  // Going TO a viewer: remember this page and allow one restore on return.
  // Links to anything else (homepage, grid, fresh subject) set no flag,
  // so those arrivals correctly start at the top.
  document.addEventListener(
    "click",
    function (e) {
      var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (!a) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#") return;
      try {
        var url = new URL(href, location.origin);
        if (url.origin !== location.origin) return;
        if (url.pathname === location.pathname) return;
        if (isViewerDest(url.pathname)) {
          save();
          setAllow(location.pathname);
        }
      } catch (err) {}
    },
    true
  );

  // Dashboard is a mini-SPA (openSubject/backToSubjects use pushState):
  // leaving a view arms its restore flag; entering a view restores only
  // when armed (back), otherwise starts at the top (fresh open).
  try {
    var origPush = history.pushState;
    history.pushState = function () {
      try {
        save();
        setAllow(location.pathname);
      } catch (e) {}
      var ret = origPush.apply(this, arguments);
      try {
        if (hasAllow(location.pathname)) {
          restore();
        } else {
          instantScrollTo(0);
          clearPath(location.pathname);
        }
      } catch (e) {}
      return ret;
    };
  } catch (e) {}

  window.addEventListener("popstate", function () {
    // Let dashboard.js swap views first, then restore if armed.
    setTimeout(restore, 60);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", restore);
  } else {
    restore();
  }
  window.addEventListener("load", function () {
    if (restoreCancelled || !shouldRestore()) return;
    var s = getSaved(location.pathname);
    if (s != null) {
      try {
        applyTo(s.y, s.main);
      } catch (e) {}
    }
  });
})();
