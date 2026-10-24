document.querySelectorAll("[data-fullscreen]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const embed = btn.closest(".material-block").querySelector("embed");
    if (!embed) return;
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (embed.requestFullscreen) {
      embed.requestFullscreen();
    } else if (embed.webkitRequestFullscreen) {
      embed.webkitRequestFullscreen();
    }
  });
});

document.querySelectorAll(".txt-viewer").forEach(async (el) => {
  try {
    const res = await fetch(el.dataset.src);
    el.textContent = await res.text();
  } catch (e) {
    el.textContent = "Could not load file.";
  }
});

document.querySelectorAll(".docx-viewer").forEach(async (el) => {
  if (typeof mammoth === "undefined") {
    el.innerHTML =
      '<p class="muted center">Preview unavailable offline. Use the download button above.</p>';
    return;
  }
  try {
    const res = await fetch(el.dataset.src);
    const arrayBuffer = await res.arrayBuffer();
    const result = await mammoth.convertToHtml({ arrayBuffer });
    el.innerHTML = result.value || "<p class='muted'>Empty document.</p>";
  } catch (e) {
    el.innerHTML = "<p class='muted center'>Could not render this document.</p>";
  }
});

// Back-to-top — combined viewer, dark-glass theme, window + viewer-main scroll
(function() {
  const btn = document.getElementById("back-to-top");
  if (!btn) return;
  const main = document.getElementById("viewer-main");
  const SHOW_AFTER = 8;
  const HIDE_AFTER_DESKTOP = 3000;
  const isMobileViewport = () => window.matchMedia("(max-width: 768px)").matches;
  const hideDelay = () => (isMobileViewport() ? 1000 : HIDE_AFTER_DESKTOP);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Hidden until the user actually scrolls. This also covers restored
  // scroll positions: a programmatic restore must not reveal the button.
  let userScrolled = false;
  let hideTimer = null;

  function currentY() {
    const winY = window.scrollY || document.documentElement.scrollTop || 0;
    const mainY = main ? main.scrollTop || 0 : 0;
    return Math.max(winY, mainY);
  }
  function setVisible(show) {
    btn.classList.toggle("is-visible", show);
    btn.tabIndex = show ? 0 : -1;
    btn.setAttribute("aria-hidden", String(!show));
  }
  function clearHideTimer() {
    if (hideTimer) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  }
  function toggle() {
    if (userScrolled && currentY() > SHOW_AFTER) {
      setVisible(true);
      // Keep it while the user is scrolling; on phones it hides after 1s
      // without movement, on desktop after 3s.
      clearHideTimer();
      hideTimer = setTimeout(() => {
        hideTimer = null;
        setVisible(false);
      }, hideDelay());
    } else {
      clearHideTimer();
      setVisible(false);
    }
  }
  function arm() {
    userScrolled = true;
  }
  function scrollIntent() {
    userScrolled = true;
    // Show immediately on the attempt, even at the bottom of a page where
    // no further scroll event can fire.
    toggle();
  }
  const armKeys = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);
  window.addEventListener("wheel", scrollIntent, { passive: true });
  window.addEventListener("touchmove", scrollIntent, { passive: true });
  window.addEventListener("pointerdown", arm, { passive: true });
  window.addEventListener("keydown", (event) => {
    if (armKeys.has(event.key)) scrollIntent();
  }, { passive: true });

  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      if (userScrolled) toggle();
      else {
        clearHideTimer();
        setVisible(false);
      }
      ticking = false;
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  if (main) main.addEventListener("scroll", onScroll, { passive: true });
  setVisible(false);

  // Returning to the viewer through bfcache should start hidden again,
  // even if the previous visit left the button visible.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    userScrolled = false;
    clearHideTimer();
    setVisible(false);
  });

  btn.addEventListener("click", () => {
    const behavior = reduceMotion ? "auto" : "smooth";
    try {
      window.scrollTo({ top: 0, behavior });
      document.documentElement.scrollTo({ top: 0, behavior });
      if (main) main.scrollTo({ top: 0, behavior });
    } catch (e) {
      window.scrollTo(0, 0);
      if (main) main.scrollTop = 0;
    }
  });
})();

// Viewer TOC collapsable – overlay drawer on small screens, sidebar on desktop
(function() {
  const toc = document.getElementById("viewer-toc");
  const toggle = document.getElementById("viewer-toc-toggle");
  const reopen = document.getElementById("viewer-toc-reopen");
  const backdrop = document.getElementById("viewer-toc-backdrop");
  if (!toc) return;
  const mobileMq = window.matchMedia("(max-width: 1100px)");
  function isMobile() { return mobileMq.matches; }
  function setCollapsed(collapsed, persist) {
    toc.classList.toggle("collapsed", collapsed);
    document.body.classList.toggle("viewer-toc-collapsed", collapsed);
    document.body.classList.toggle("viewer-toc-drawer-open", !collapsed);
    toc.setAttribute("aria-hidden", String(collapsed));
    if (toggle) toggle.setAttribute("aria-expanded", String(!collapsed));
    if (persist !== false) {
      try { localStorage.setItem("studyhub:viewer-toc-collapsed", String(collapsed)); } catch(e) {}
    }
  }
  if (toggle) toggle.addEventListener("click", () => setCollapsed(!toc.classList.contains("collapsed")));
  if (reopen) reopen.addEventListener("click", () => setCollapsed(false));
  if (backdrop) backdrop.addEventListener("click", () => setCollapsed(true));
  toc.querySelectorAll("a[href^='#']").forEach((link) => {
    link.addEventListener("click", () => {
      if (isMobile()) setCollapsed(true);
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !toc.classList.contains("collapsed")) setCollapsed(true);
  });
  try {
    if (isMobile()) {
      setCollapsed(true, false);
    } else if (localStorage.getItem("studyhub:viewer-toc-collapsed") === "true") {
      setCollapsed(true, false);
    }
  } catch(e) {
    if (isMobile()) setCollapsed(true, false);
  }
  const onBreakpoint = () => {
    if (isMobile()) setCollapsed(true, false);
  };
  if (mobileMq.addEventListener) mobileMq.addEventListener("change", onBreakpoint);
  else if (mobileMq.addListener) mobileMq.addListener(onBreakpoint);
})();
