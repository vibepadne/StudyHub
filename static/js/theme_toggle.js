/* Site-wide color theme: light / dark / system.
   The active option is highlighted in the navbar pill; "system" follows
   the OS preference live. The chosen option persists in localStorage
   ("studyhub:theme"); base.html resolves it before first paint. */
(function () {
  var KEY = "studyhub:theme";
  var ORDER = ["light", "dark", "system"];
  var group = document.getElementById("theme-switch");
  if (!group) return;
  var opts = Array.prototype.slice.call(
    group.querySelectorAll(".theme-opt[data-theme-opt]")
  );
  var mq = window.matchMedia("(prefers-color-scheme: dark)");

  function choice() {
    try {
      var t = localStorage.getItem(KEY);
      return ORDER.indexOf(t) >= 0 ? t : "system";
    } catch (e) {
      return "system";
    }
  }

  function sync(persist) {
    var t = choice();
    var dark = t === "dark" || (t === "system" && mq.matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.dataset.themeChoice = t;
    opts.forEach(function (b) {
      var on = b.dataset.themeOpt === t;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", String(on));
    });
    if (persist) {
      try { localStorage.setItem(KEY, t); } catch (e) {}
    }
  }

  group.addEventListener("click", function (event) {
    var btn = event.target.closest ? event.target.closest(".theme-opt") : null;
    if (!btn || !btn.dataset.themeOpt) return;
    try { localStorage.setItem(KEY, btn.dataset.themeOpt); } catch (e) {}
    sync(false);
  });

  // Follow OS changes live while "system" is selected.
  var onChange = function () {
    if (choice() === "system") sync(false);
  };
  if (typeof mq.addEventListener === "function") {
    mq.addEventListener("change", onChange);
  } else if (typeof mq.addListener === "function") {
    mq.addListener(onChange);
  }

  // Another tab changed the preference — mirror it here too.
  window.addEventListener("storage", function (event) {
    if (event.key === KEY) sync(false);
  });

  sync(false);
})();
