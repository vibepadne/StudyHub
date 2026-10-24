(function () {
  "use strict";

  // ── DOM refs ───────────────────────────────────────────────────────
  const selectionBar   = document.getElementById("shared-selection-bar");
  const selectionCount = document.getElementById("shared-selection-count");
  const openSelected   = document.getElementById("shared-open-selected");
  const deleteForm     = document.getElementById("shared-delete-form");
  const revokeForm     = document.getElementById("shared-revoke-form");
  const deleteIds      = document.getElementById("shared-delete-ids");
  const revokeIds      = document.getElementById("shared-revoke-ids");
  const clearBtn       = document.getElementById("shared-clear-selection");

  const combineForm        = document.getElementById("combine-form");
  const combineCount       = document.getElementById("combine-count");
  const combineIds         = document.getElementById("combine-material-ids");
  const combineSubmit      = document.getElementById("combine-submit");
  const combineNewFields   = document.getElementById("combine-new-fields");
  const combineExistFields = document.getElementById("combine-existing-fields");

  // ── Helpers ────────────────────────────────────────────────────────
  function isShown(el) { return !el.closest(".hidden"); }

  function allCheckboxes(cls) {
    return Array.from(document.querySelectorAll(cls)).filter(isShown);
  }

  function getDocsForGroup(groupKey) {
    return Array.from(
      document.querySelectorAll(`.share-child-check[data-group-key="${groupKey}"]`)
    ).filter(isShown);
  }

  function getTopicsForGroup(groupKey) {
    return Array.from(
      document.querySelectorAll(`.share-topic-check[data-group-key="${groupKey}"]`)
    ).filter(isShown);
  }

  function getGroupCheck(groupKey) {
    return document.querySelector(`.share-group-check[data-group-key="${groupKey}"]`);
  }

  // ── Checkbox sync: group ↔ topic ↔ doc ────────────────────────────
  function syncFromGroup(el) {
    const key = el.dataset.groupKey;
    getTopicsForGroup(key).forEach(function (t) { t.checked = el.checked; t.indeterminate = false; });
    getDocsForGroup(key).forEach(function (d) { d.checked = el.checked; });
    el.indeterminate = false;
  }

  function syncFromTopic(el) {
    var key = el.dataset.groupKey;
    var tid = el.dataset.topicId;
    var docs = Array.from(
      document.querySelectorAll(`.share-child-check[data-group-key="${key}"][data-topic-id="${tid}"]`)
    ).filter(isShown);
    docs.forEach(function (d) { d.checked = el.checked; });
    el.indeterminate = false;
    syncGroupUp(key);
  }

  function syncFromDoc(el) {
    var key = el.dataset.groupKey;
    var tid = el.dataset.topicId;
    if (tid) {
      var topicEl = document.querySelector(`.share-topic-check[data-group-key="${key}"][data-topic-id="${tid}"]`);
      if (topicEl) {
        var siblings = Array.from(
          document.querySelectorAll(`.share-child-check[data-group-key="${key}"][data-topic-id="${tid}"]`)
        ).filter(isShown);
        var all = siblings.every(function (c) { return c.checked; });
        var some = siblings.some(function (c) { return c.checked; });
        topicEl.checked = all;
        topicEl.indeterminate = !all && some;
      }
    }
    syncGroupUp(key);
  }

  function syncGroupUp(groupKey) {
    var groupEl = getGroupCheck(groupKey);
    if (!groupEl) return;
    var docs = getDocsForGroup(groupKey);
    var topics = getTopicsForGroup(groupKey);
    if (docs.length) {
      var all = docs.every(function (c) { return c.checked; });
      var some = docs.some(function (c) { return c.checked; });
      groupEl.checked = all;
      groupEl.indeterminate = !all && some;
    } else if (topics.length) {
      var allT = topics.every(function (t) { return t.checked && !t.indeterminate; });
      var someT = topics.some(function (t) { return t.checked || t.indeterminate; });
      groupEl.checked = allT;
      groupEl.indeterminate = !allT && someT;
    }
  }

  function syncAllGroups() {
    document.querySelectorAll(".share-group-check").forEach(function (g) {
      syncGroupUp(g.dataset.groupKey);
    });
  }

  // ── Selection bar logic ────────────────────────────────────────────
  function updateSelection() {
    var received = allCheckboxes(".shared-received-check").filter(function (b) { return b.checked; });
    var given    = allCheckboxes(".shared-given-check").filter(function (b) { return b.checked; });
    var scope    = received.length ? "received" : given.length ? "given" : null;

    // Disable the other scope's checkboxes
    allCheckboxes(".shared-received-check").forEach(function (b) { b.disabled = scope === "given"; });
    allCheckboxes(".shared-given-check").forEach(function (b) { b.disabled = scope === "received"; });

    if (selectionBar) selectionBar.classList.toggle("hidden", !scope);
    if (selectionCount) selectionCount.textContent = String(received.length || given.length);

    // Open Combined Viewer button
    if (openSelected) {
      var docBoxes = scope === "received" ? received : given;
      var canOpen = docBoxes.some(function (b) { return !!b.dataset.materialId; });
      openSelected.classList.toggle("hidden", !scope || !canOpen);
      openSelected.disabled = !canOpen;
    }

    // Delete / Revoke — support comma-separated share lists (multi-recipient docs)
    function collectShareIds(boxes) {
      var out = [];
      boxes.forEach(function (b) {
        var raw = b.dataset.shareId || b.dataset.shareIds || "";
        raw.split(",").forEach(function (v) {
          v = (v || "").trim();
          if (v && out.indexOf(v) === -1) out.push(v);
        });
      });
      return out.join(",");
    }
    if (deleteForm) deleteForm.classList.toggle("hidden", scope !== "received");
    if (revokeForm) revokeForm.classList.toggle("hidden", scope !== "given");
    if (deleteIds) deleteIds.value = collectShareIds(received);
    if (revokeIds) revokeIds.value = collectShareIds(given);

    // Highlight checked items
    document.querySelectorAll(".doc-option").forEach(function (opt) {
      var cb = opt.querySelector(".shared-selection-checkbox");
      opt.classList.toggle("checked", cb && cb.checked);
    });
    document.querySelectorAll(".topic-option").forEach(function (opt) {
      var cb = opt.querySelector(".shared-selection-checkbox");
      opt.classList.toggle("checked", cb && cb.checked);
    });

    // Combine form visibility
    var hasUnlockedDocs = allCheckboxes(".share-child-check[data-material-id]").length > 0;
    if (combineForm) combineForm.classList.toggle("hidden", !(scope === "received" && hasUnlockedDocs));

    var checkedMats = allCheckboxes(".share-child-check[data-material-id]").filter(function (b) { return b.checked; });
    var uniqueIds = checkedMats.map(function (b) { return b.dataset.materialId; }).filter(function (v, i, a) { return a.indexOf(v) === i; });
    if (combineCount) combineCount.textContent = String(uniqueIds.length);
    if (combineIds) combineIds.value = uniqueIds.join(",");
    if (combineSubmit) combineSubmit.disabled = uniqueIds.length === 0;
    updateCombineDestination();
  }

  // ── Combine form destination toggle ────────────────────────────────
  function updateCombineDestination() {
    var checked = document.querySelector('input[name="destination"]:checked');
    var val = checked ? checked.value : "new";
    if (combineNewFields) combineNewFields.classList.toggle("hidden", val !== "new");
    if (combineExistFields) combineExistFields.classList.toggle("hidden", val !== "existing");
  }

  document.querySelectorAll('input[name="destination"]').forEach(function (r) {
    r.addEventListener("change", updateCombineDestination);
  });

  // ── Event delegation for checkbox changes ──────────────────────────
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t.classList) return;
    if (t.classList.contains("share-group-check")) { syncFromGroup(t); updateSelection(); }
    else if (t.classList.contains("share-topic-check")) { syncFromTopic(t); updateSelection(); }
    else if (t.classList.contains("share-child-check")) { syncFromDoc(t); updateSelection(); }
    else if (t.classList.contains("shared-selection-checkbox")) { updateSelection(); }
  });

  // ── Open Combined Viewer ───────────────────────────────────────────
  if (openSelected) {
    openSelected.addEventListener("click", function () {
      var checked = allCheckboxes(".share-child-check[data-material-id]").filter(function (b) { return b.checked; });
      var ids = checked.map(function (b) { return b.dataset.materialId; }).filter(function (v, i, a) { return a.indexOf(v) === i; });
      if (ids.length) {
        var dest = "/shared/combined/?materials=" + ids.join(",") + "&from=shared";
        // Opening the combined viewer clears the selection so it is not
        // still ticked when the user returns to this page.
        clearSelection();
        // Arm the scroll memory so closing the combined viewer (back-link
        // or Back button) returns to this very part of the shared page.
        if (window.__studyhubArmReturn) window.__studyhubArmReturn(dest);
        window.location.href = dest;
      }
    });
  }

  // ── Clear selection ────────────────────────────────────────────────
  function clearSelection() {
    document.querySelectorAll(".shared-selection-checkbox").forEach(function (b) {
      b.checked = false;
      b.indeterminate = false;
    });
    syncAllGroups();
    updateSelection();
  }

  if (clearBtn) clearBtn.addEventListener("click", clearSelection);

  // ── Sidebar collapse ───────────────────────────────────────────────
  var sidebar       = document.getElementById("shared-sidebar");
  var sidebarToggle = document.getElementById("sidebar-toggle");
  var sidebarReopen = document.getElementById("shared-sidebar-reopen");
  var tabRecv = document.getElementById("tab-received");
  var tabGiven = document.getElementById("tab-given");
  var sectionRecv = document.getElementById("section-received");
  var sectionGiven = document.getElementById("section-given");
  var ACTIVE_TAB_KEY = "studyhub:shared-active-tab";

  function applySidebar(collapsed, persist) {
    if (sidebar) sidebar.classList.toggle("collapsed", collapsed);
    document.body.classList.toggle("shared-sidebar-collapsed", collapsed);
    document.body.classList.toggle(
      "shared-sidebar-drawer-open",
      !collapsed && window.innerWidth <= 1100
    );
    if (sidebarToggle) sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    if (sidebarReopen) sidebarReopen.classList.toggle("hidden", !collapsed);
    // Only the desktop preference is remembered; the mobile drawer always
    // starts closed so it cannot cover the page on the next visit.
    if (persist !== false && window.innerWidth > 1100) {
      try { localStorage.setItem("studyhub:shared-sidebar-collapsed", String(collapsed)); } catch (e) {}
    }
  }

  window.addEventListener("resize", function () {
    if (window.innerWidth > 1100) {
      document.body.classList.remove("shared-sidebar-drawer-open");
    }
  });

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", function () {
      applySidebar(!sidebar.classList.contains("collapsed"));
    });
    if (sidebarReopen) {
      sidebarReopen.addEventListener("click", function () { applySidebar(false); });
    }
    var sidebarBackdrop = document.getElementById("shared-sidebar-backdrop");
    if (sidebarBackdrop) {
      sidebarBackdrop.addEventListener("click", function () { applySidebar(true); });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !sidebar.classList.contains("collapsed")) {
        applySidebar(true);
      }
    });
    try {
      var was = localStorage.getItem("studyhub:shared-sidebar-collapsed");
      // On phones/tablets the filters drawer always starts closed; a stored
      // "open" state from another visit must not cover the page on load.
      applySidebar(window.innerWidth <= 1100 ? true : was === "true", false);
    } catch (e) {
      applySidebar(window.innerWidth <= 1100, false);
    }
  }

  // The remembered state is applied — allow transitions again after first paint.
  window.requestAnimationFrame(function () {
    document.documentElement.classList.remove("sidebar-preload");
  });

  // ── Section tabs (mutually exclusive) ──────────────────────────────
  function clearAllSelection() {
    document.querySelectorAll(".shared-selection-checkbox").forEach(function (b) {
      b.checked = false;
      b.indeterminate = false;
    });
    syncAllGroups();
    updateSelection();
  }

  function applyTab(tab, persist) {
    var showReceived = tab !== "given";
    var currentReceived = tabRecv ? tabRecv.getAttribute("aria-pressed") === "true" : true;
    var changed = currentReceived !== showReceived;
    if (tabRecv) tabRecv.setAttribute("aria-pressed", String(showReceived));
    if (tabGiven) tabGiven.setAttribute("aria-pressed", String(!showReceived));
    if (sectionRecv) sectionRecv.classList.toggle("hidden", !showReceived);
    if (sectionGiven) sectionGiven.classList.toggle("hidden", showReceived);
    // Drop any selection from the section that is being hidden.
    if (changed) clearAllSelection();
    if (persist) {
      try { localStorage.setItem(ACTIVE_TAB_KEY, showReceived ? "received" : "given"); } catch (e) {}
    }
  }

  function initialTab() {
    var t = null;
    try { t = localStorage.getItem(ACTIVE_TAB_KEY); } catch (e) {}
    if (t === "received" || t === "given") return t;
    // One-time migration from the old independent-toggle switches.
    try {
      if (
        localStorage.getItem("studyhub:shared-show-given") === "true" &&
        localStorage.getItem("studyhub:shared-show-received") === "false"
      ) {
        return "given";
      }
    } catch (e) {}
    return "received";
  }

  if (tabRecv && tabGiven && sectionRecv && sectionGiven) {
    tabRecv.addEventListener("click", function () { applyTab("received", true); });
    tabGiven.addEventListener("click", function () { applyTab("given", true); });
    applyTab(initialTab(), false);
  }

  // ── See more: five collections ("bubbles") at a time ───────────────
  var SEE_MORE_STEP = 5;

  function hiddenGroups(section) {
    return Array.from(section.querySelectorAll(".share-group.share-extra.hidden"));
  }

  function updateSeeMore(section) {
    var groups = hiddenGroups(section);
    var remaining = groups.length;
    var btn = section.querySelector(".see-more-btn");
    if (btn) {
      if (!remaining) {
        var wrap = btn.closest(".see-more-wrap") || btn;
        wrap.classList.add("hidden");
      } else {
        btn.textContent = "See more (" + remaining + " more collection" + (remaining === 1 ? "" : "s") + ")";
      }
    }
    var counter = section.querySelector("[data-visible-count]");
    if (counter) {
      var total = parseInt(counter.dataset.total || "0", 10);
      counter.textContent = String(Math.max(0, total - remaining));
    }
  }

  function revealNextGroups(section) {
    // Reveal the next five collections, keeping the recency order.
    var groups = hiddenGroups(section);
    for (var i = 0; i < groups.length && i < SEE_MORE_STEP; i++) {
      groups[i].classList.remove("hidden");
    }
  }

  Array.from(document.querySelectorAll(".share-section")).forEach(function (section) {
    var btn = section.querySelector(".see-more-btn");
    if (btn) {
      btn.addEventListener("click", function () {
        revealNextGroups(section);
        updateSeeMore(section);
      });
    }
    updateSeeMore(section);
  });

  // ── Auto-scroll to the collection that was just unlocked ───────────
  function focusUnlockedCollection() {
    var hash = window.location.hash || "";
    if (hash.indexOf("#collection-") !== 0) return;
    var el = document.getElementById(hash.slice(1));
    if (!el) return;
    // Unlock anchors always live in "shared with me"; if the other tab is
    // shown, switch to the tab that contains this collection.
    if (el.closest("#section-received") && sectionRecv && sectionRecv.classList.contains("hidden")) {
      applyTab("received", true);
    } else if (el.closest("#section-given") && sectionGiven && sectionGiven.classList.contains("hidden")) {
      applyTab("given", true);
    }
    // The collection may still be behind "See more" — reveal until it's out.
    var owner = el.closest(".share-section");
    if (owner && el.classList.contains("hidden")) {
      while (el.classList.contains("hidden") && hiddenGroups(owner).length) {
        revealNextGroups(owner);
      }
      updateSeeMore(owner);
    }
    try { el.scrollIntoView({ behavior: "smooth", block: "start" }); }
    catch (e) { el.scrollIntoView(); }
    el.classList.add("group-flash");
    window.setTimeout(function () { el.classList.remove("group-flash"); }, 2600);
  }

  if ((window.location.hash || "").indexOf("#collection-") === 0) {
    window.addEventListener("load", function () {
      window.setTimeout(focusUnlockedCollection, 60);
    });
  }

  // ── Init ───────────────────────────────────────────────────────────
  syncAllGroups();
  updateSelection();
})();
