const MIN_CHARS = 2;
const DEBOUNCE_MS = 220;

const input = document.getElementById("user-search-input");
const box = document.getElementById("chip-box");
const dropdown = document.getElementById("search-dropdown");
const chipsEl = document.getElementById("chips");
const hidden = document.getElementById("recipient-ids");

const selected = new Map();
let results = [];
let activeIndex = -1;
let debounceTimer = null;
let requestSeq = 0;

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function initials(name) {
  return (name || "?").trim().charAt(0).toUpperCase();
}

function avatarHtml(result) {
  if (result.avatar) {
    return `<img class="user-avatar" src="${esc(result.avatar)}" alt="">`;
  }
  return `<span class="user-avatar user-avatar-fallback">${esc(initials(result.full_name || result.username))}</span>`;
}

function syncHidden() {
  hidden.value = Array.from(selected.keys()).join(",");
}

function renderChips() {
  chipsEl.innerHTML = "";
  selected.forEach((result, id) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `
      ${avatarHtml(result)}
      <span class="chip-name">${esc(result.full_name || result.username)}</span>
      <span class="chip-handle">@${esc(result.username)}</span>
      <button type="button" class="chip-x" aria-label="Remove">&times;</button>`;
    chip.querySelector(".chip-x").addEventListener("click", () => {
      selected.delete(id);
      syncHidden();
      renderChips();
    });
    chipsEl.appendChild(chip);
  });
  syncHidden();
}

function addResult(result) {
  selected.set(String(result.id), result);
  renderChips();
  input.value = "";
  hideDropdown();
  input.focus();
}

function hideDropdown() {
  dropdown.classList.add("hidden");
  dropdown.innerHTML = "";
  results = [];
  activeIndex = -1;
}

function highlight(listHtml, q) {
  const idx = listHtml.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return listHtml;
  return (
    esc(listHtml.slice(0, idx)) +
    "<mark>" +
    esc(listHtml.slice(idx, idx + q.length)) +
    "</mark>" +
    esc(listHtml.slice(idx + q.length))
  );
}

function renderDropdown(q) {
  if (!results.length) {
    dropdown.innerHTML = `<div class="dropdown-empty">No people found for “${esc(q)}”.</div>`;
    dropdown.classList.remove("hidden");
    return;
  }
  dropdown.innerHTML = results
    .map(
      (r, i) => `
      <button type="button" class="dropdown-item${i === activeIndex ? " active" : ""}" data-id="${r.id}">
        ${avatarHtml(r)}
        <span class="dropdown-names">
          <span class="dropdown-name">${highlight(r.full_name || r.username, q)}</span>
          <span class="dropdown-handle">@${highlight(r.username, q)}</span>
        </span>
        ${selected.has(String(r.id)) ? '<span class="badge badge-sm">added</span>' : ""}
      </button>`
    )
    .join("");
  dropdown.classList.remove("hidden");
  dropdown.querySelectorAll(".dropdown-item").forEach((el) => {
    el.addEventListener("mousedown", (e) => {
      e.preventDefault();
      pick(el.dataset.id);
    });
  });
}

function pick(id) {
  const result = results.find((r) => String(r.id) === String(id));
  if (!result) return;
  addResult(result);
}

async function search(q) {
  const seq = ++requestSeq;
  try {
    const res = await fetch(`${window.SEARCH_URL}?q=${encodeURIComponent(q)}`, {
      credentials: "same-origin",
    });
    if (!res.ok) return;
    const data = await res.json();
    if (seq !== requestSeq) return;
    results = data.results || [];
    activeIndex = results.length ? 0 : -1;
    renderDropdown(q);
  } catch (e) {}
}

input.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  const q = input.value.trim().replace(/^@/, "");
  if (q.length < MIN_CHARS) {
    hideDropdown();
    return;
  }
  debounceTimer = setTimeout(() => search(q), DEBOUNCE_MS);
});

input.addEventListener("keydown", (e) => {
  if (dropdown.classList.contains("hidden")) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    activeIndex = Math.min(activeIndex + 1, results.length - 1);
    renderDropdown(input.value.trim());
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    activeIndex = Math.max(activeIndex - 1, 0);
    renderDropdown(input.value.trim());
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (activeIndex >= 0 && results[activeIndex]) pick(results[activeIndex].id);
  } else if (e.key === "Escape") {
    hideDropdown();
  }
});

document.addEventListener("click", (e) => {
  if (!box.contains(e.target)) hideDropdown();
});

function showInstantToastShare(msg, tone = "success") {
  let host = document.getElementById("instant-toast-host");
  if (!host) { host = document.createElement("div"); host.id = "instant-toast-host"; host.setAttribute("aria-live","polite"); document.body.appendChild(host); }
  const el = document.createElement("div"); el.className = `instant-toast instant-toast--${tone}`; el.textContent = msg; host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("is-visible"));
  setTimeout(() => { el.classList.remove("is-visible"); setTimeout(() => el.remove(), 280); }, 4500);
}
document.getElementById("share-form").addEventListener("submit", (e) => {
  if (!selected.size) {
    e.preventDefault();
    document.getElementById("pick-hint").textContent =
      "Add at least one person before sharing.";
    document.getElementById("pick-hint").classList.add("hint-error");
    input.focus();
    return;
  }
  // Instant redirect: complete sharing in background, return to previous page immediately
  e.preventDefault();
  const form = e.target;
  // The documents are being shared — drop the dashboard's remembered
  // selection so the page we return to is not still ticked.
  if (form.dataset.clearBubbleSelection) {
    try { localStorage.removeItem("studyhub:bubble-selection"); } catch (_) {}
  }
  const btn = form.querySelector('button[type="submit"]');
  if (btn) { btn.disabled = true; btn.textContent = "Shared ✓"; btn.style.opacity = "0.85"; }
  showInstantToastShare(`Sharing with ${selected.size} ${selected.size===1?"person":"people"} — queued, finishing in background…`);

  const formData = new FormData(form);
  const action = form.action;
  // Previous page where user was (dashboard, shared-lists, etc.) – fallback to dashboard
  let prev = "/dashboard/";
  try {
    if (document.referrer && new URL(document.referrer).origin === location.origin) {
      prev = document.referrer;
    } else if (window.history.length > 1) {
      // Use dashboard as sensible previous for direct share links
      const isSharePage = location.pathname.startsWith("/share/");
      if (isSharePage) prev = "/dashboard/";
    }
  } catch (_) {}

  // Background POST – keepalive so it survives the instant navigation
  try {
    fetch(action, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      keepalive: true,
      headers: { "X-Requested-With": "fetch" }
    }).catch(() => {});
    // Also try sendBeacon as fallback for very quick unload
    if (navigator.sendBeacon) {
      // sendBeacon will be second attempt; server is idempotent via get_or_create
      try { navigator.sendBeacon(action, formData); } catch(_) {}
    }
  } catch (_) {}

  // Instant redirect – user doesn't stare at share page
  setTimeout(() => { window.location.href = prev; }, 140);
});
