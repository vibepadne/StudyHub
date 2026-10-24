(function () {
  const backdrop = document.getElementById("cmdk-backdrop");
  const input = document.getElementById("cmdk-input");
  const resultsEl = document.getElementById("cmdk-results");
  const modeBadge = document.getElementById("cmdk-mode-badge");
  if (!backdrop || !input || !resultsEl) return;

  const MODES = {
    local: { badge: "\ud83d\udd0d Search", placeholder: "Search subjects, topics, documents\u2026" },
    google: { badge: "\ud83c\uddec\ud83c\udde7 Google", placeholder: "Search Google \u2014 Enter opens a new tab" },
    youtube: { badge: "\u25b6 YouTube", placeholder: "Search YouTube \u2014 Enter opens a new tab" },
    ai: { badge: "\u2728 Ask AI", placeholder: "Ask the StudyHub assistant (no notes attached)\u2026" },
  };

  let mode = "local";
  let isOpen = false;
  let items = [];
  let activeIndex = -1;
  let debounceTimer = null;
  let currentFetch = null;
  const aiHistory = [];

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function mdToHtml(md) {
    let out = esc(md);
    out = out.replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="cmdk-ai-code">${code.trim()}</pre>`);
    out = out.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|\n)\s*[-*]\s+/g, "$1\u2022 ");
    out = out.replace(/\n/g, "<br>");
    return out;
  }

  function csrfToken() {
    if (window.CSRF_TOKEN) return window.CSRF_TOKEN;
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setMode(next) {
    mode = next;
    const conf = MODES[mode];
    if (modeBadge) modeBadge.innerHTML = conf.badge;
    input.placeholder = conf.placeholder;
    clearResults();
    renderIdleHint();
  }

  function openPalette(startMode) {
    backdrop.classList.remove("hidden");
    backdrop.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    isOpen = true;
    setMode(startMode || "local");
    setTimeout(() => input.focus(), 10);
  }

  function closePalette() {
    if (!isOpen) return;
    if (currentFetch) {
      currentFetch.abort();
      currentFetch = null;
    }
    clearTimeout(debounceTimer);
    backdrop.classList.add("hidden");
    backdrop.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    isOpen = false;
    items = [];
    activeIndex = -1;
  }

  function clearResults() {
    resultsEl.innerHTML = "";
    items = [];
    activeIndex = -1;
  }

  function renderIdleHint() {
    if (mode === "local") {
      resultsEl.innerHTML =
        '<p class="cmdk-idle">Type to search your subjects, topics, documents \u2014 and inside documents.</p>';
    } else if (mode === "google") {
      resultsEl.innerHTML =
        '<p class="cmdk-idle">Press <kbd>enter</kbd> to open Google results in a new tab. <kbd>esc</kbd> closes.</p>';
    } else if (mode === "youtube") {
      resultsEl.innerHTML =
        '<p class="cmdk-idle">Press <kbd>enter</kbd> to search YouTube in a new tab. Paste a video link to jump straight to it.</p>';
    } else {
      resultsEl.innerHTML =
        '<p class="cmdk-idle">Ask anything \u2014 the assistant answers directly, without attaching your notes.</p>';
    }
  }

  function flattenGroups(groups) {
    const flat = [];
    groups.forEach((group) => {
      group.items.forEach((item) => {
        flat.push({ ...item, group: group.label });
      });
    });
    return flat;
  }

  function renderResults(groups, q) {
    items = flattenGroups(groups);
    activeIndex = items.length ? 0 : -1;
    if (!items.length) {
      resultsEl.innerHTML = `<p class="cmdk-idle">No matches for \u201c${esc(q)}\u201d.</p>`;
      return;
    }
    const html = [];
    let lastGroup = null;
    items.forEach((item, index) => {
      if (item.group !== lastGroup) {
        html.push(`<div class="cmdk-group-label">${esc(item.group)}</div>`);
        lastGroup = item.group;
      }
      const snippet = item.snippet
        ? `<span class="cmdk-snippet">${esc(item.snippet)}</span>`
        : "";
      html.push(
        `<button type="button" class="cmdk-item${index === activeIndex ? " active" : ""}" data-index="${index}">
          <span class="cmdk-icon">${item.icon || "\ud83d\udcc4"}</span>
          <span class="cmdk-texts">
            <span class="cmdk-title">${esc(item.title)}</span>
            ${snippet}
            <span class="cmdk-sub">${esc(item.subtitle || "")}</span>
          </span>
        </button>`
      );
    });
    resultsEl.innerHTML = html.join("");
    resultsEl.querySelectorAll(".cmdk-item").forEach((el) => {
      el.addEventListener("click", () => activateItem(Number(el.dataset.index)));
      el.addEventListener("mousemove", () => selectItem(Number(el.dataset.index)));
    });
    scrollActiveIntoView();
  }

  function selectItem(index) {
    if (index < 0 || index >= items.length) return;
    activeIndex = index;
    resultsEl.querySelectorAll(".cmdk-item").forEach((el) => {
      el.classList.toggle("active", Number(el.dataset.index) === index);
    });
    scrollActiveIntoView();
  }

  function scrollActiveIntoView() {
    const active = resultsEl.querySelector(".cmdk-item.active");
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function activateItem(index) {
    const item = items[index];
    if (item && item.url) {
      try {
        var dest = new URL(item.url, location.origin);
        var isViewer = dest.pathname.indexOf("/viewer/") === 0 ||
          dest.pathname.indexOf("/shared/combined") === 0 ||
          dest.pathname.indexOf("/share/") === 0 ||
          /^\/shared\/\d+\//.test(dest.pathname);
        if (isViewer && window.__studyhubArmReturn) window.__studyhubArmReturn();
      } catch (e) {}
      window.location.href = item.url;
    }
  }

  async function runLocalSearch(q) {
    if (currentFetch) currentFetch.abort();
    const controller = new AbortController();
    currentFetch = controller;
    try {
      const res = await fetch(`/search/?q=${encodeURIComponent(q)}`, {
        credentials: "same-origin",
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({ groups: [] }));
      if (isOpen && mode === "local") renderResults(data.groups || [], q);
    } catch (err) {
      if (err.name !== "AbortError") {
        resultsEl.innerHTML = '<p class="cmdk-idle cmdk-error">Search failed. Try again.</p>';
      }
    } finally {
      if (currentFetch === controller) currentFetch = null;
    }
  }

  function scheduleLocalSearch(q) {
    clearTimeout(debounceTimer);
    if (q.trim().length < 2) {
      clearResults();
      renderIdleHint();
      return;
    }
    debounceTimer = setTimeout(() => runLocalSearch(q.trim()), 220);
  }

  function youtubeTargetUrl(q) {
    const trimmed = q.trim();
    const watchMatch = trimmed.match(
      /(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([\w-]{11})/i
    );
    if (watchMatch) return `https://www.youtube.com/watch?v=${watchMatch[1]}`;
    if (/^[\w-]{11}$/.test(trimmed)) return `https://www.youtube.com/watch?v=${trimmed}`;
    return `https://www.youtube.com/results?search_query=${encodeURIComponent(trimmed)}`;
  }

  function showAiMessage(html, cls) {
    const el = document.createElement("div");
    el.className = `cmdk-ai-msg${cls ? " " + cls : ""}`;
    el.innerHTML = html;
    resultsEl.appendChild(el);
    resultsEl.scrollTop = resultsEl.scrollHeight;
    return el;
  }

  async function submitQuickAsk(q) {
    const typing = showAiMessage(
      '<span class="ai-typing"><i></i><i></i><i></i></span>',
      "typing"
    );
    try {
      const res = await fetch("/ai/quick-ask/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({
          question: q,
          history: aiHistory.slice(-10),
        }),
      });
      const data = await res.json().catch(() => ({}));
      typing.remove();
      if (!res.ok) throw new Error(data.error || "Something went wrong. Try again.");
      aiHistory.push({ role: "user", text: q });
      aiHistory.push({ role: "model", text: data.answer });
      if (aiHistory.length > 20) aiHistory.splice(0, aiHistory.length - 20);
      showAiMessage(mdToHtml(data.answer));
    } catch (err) {
      typing.remove();
      showAiMessage(
        `<span class="ai-error">${esc(err.message)}</span>`,
        "error"
      );
    }
  }

  function execute() {
    const q = input.value.trim();
    if (mode === "local") {
      if (activeIndex >= 0 && q.length >= 2) activateItem(activeIndex);
      return;
    }
    if (!q) return;
    if (mode === "google") {
      window.open(`https://www.google.com/search?q=${encodeURIComponent(q)}`, "_blank");
      closePalette();
    } else if (mode === "youtube") {
      window.open(youtubeTargetUrl(q), "_blank");
      closePalette();
    } else if (mode === "ai") {
      input.value = "";
      showAiMessage(`<strong>You:</strong> ${esc(q)}`);
      submitQuickAsk(q);
    }
  }

  function openAiDrawerIfPresent() {
    const aiTab = document.getElementById("ai-tab");
    const drawer = document.getElementById("ai-drawer");
    if (aiTab && drawer) {
      if (isOpen) closePalette();
      aiTab.click();
      return true;
    }
    return false;
  }

  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape" && isOpen) {
        e.preventDefault();
        closePalette();
        return;
      }
      if (!(e.ctrlKey && !e.altKey && !e.metaKey)) return;
      const key = (e.key || "").toLowerCase();
      if (key === "s") {
        e.preventDefault();
        if (isOpen && mode === "local") closePalette();
        else openPalette("local");
      } else if (key === "g") {
        e.preventDefault();
        openPalette(isOpen && mode === "google" ? "local" : "google");
      } else if (key === "y") {
        e.preventDefault();
        openPalette(isOpen && mode === "youtube" ? "local" : "youtube");
      } else if (key === "i") {
        e.preventDefault();
        // Inside the combined/shared viewer: use the on-page AI chat,
        // which answers from that subject's documents.
        if (!openAiDrawerIfPresent()) {
          openPalette(isOpen && mode === "ai" ? "local" : "ai");
        }
      }
    },
    true
  );

  const navTrigger = document.getElementById("nav-search-trigger");
  if (navTrigger) {
    navTrigger.addEventListener("click", () => {
      if (isOpen) {
        closePalette();
      } else {
        openPalette("local");
      }
    });
  }

  const aiHint = document.getElementById("cmdk-hint-ai");
  if (aiHint && document.getElementById("ai-drawer")) {
    aiHint.textContent = "ask about these docs";
  }

  input.addEventListener("input", () => {
    if (mode === "local") scheduleLocalSearch(input.value);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      execute();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (items.length) selectItem(Math.min(items.length - 1, activeIndex + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (items.length) selectItem(Math.max(0, activeIndex - 1));
    }
  });

  backdrop.addEventListener("mousedown", (e) => {
    if (e.target === backdrop) closePalette();
  });
})();
