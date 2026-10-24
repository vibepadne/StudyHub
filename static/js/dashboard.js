const API = "/api";
const CSRF = window.CSRF_TOKEN;

const state = {
  subjects: [],
  currentSubject: null,
};

function getBubbleSelection() {
  try {
    const saved = JSON.parse(localStorage.getItem("studyhub:bubble-selection") || "null");
    if (saved && Array.isArray(saved.topics)) return {topics: saved.topics.map(Number), materials: (saved.materials || []).map(Number)};
    return {topics: (saved || []).map(Number), materials: []};
  } catch (err) { return {topics: [], materials: []}; }
}
function setBubbleSelection(selection) {
  try { localStorage.setItem("studyhub:bubble-selection", JSON.stringify({topics: [...new Set(selection.topics)], materials: [...new Set(selection.materials)]})); } catch (err) {}
  updateBubbleShare();
  syncDashboardCheckboxes();
  updateDashboardSelectionBar();
}
async function openDashboardCombined() {
  const sel = getBubbleSelection();
  let materialIds = [...sel.materials];
  // Expand topics to their materials
  if (sel.topics.length) {
    try {
      const allTopics = await api(`${API}/topics/`);
      const selectedTopics = allTopics.filter((t) => sel.topics.includes(t.id));
      const matsByTopic = await Promise.all(selectedTopics.map((t) => api(`${API}/materials/?topic=${t.id}`)));
      const topicMats = matsByTopic.flat().map((m) => m.id);
      materialIds = [...new Set([...materialIds, ...topicMats])];
    } catch (e) {}
  }
  if (!materialIds.length) {
    alert("Select at least one document or topic to view.");
    return;
  }
  // Tell the combined viewer where it was opened from so its back link
  // returns to this subject's topics page (not the shared list).
  const params = new URLSearchParams({
    materials: materialIds.join(","),
    from: "topics",
  });
  if (state.currentSubject) params.set("subject", String(state.currentSubject.id));
  const dest = `/shared/combined/?${params.toString()}`;
  // Opening the combined viewer consumes the selection: clear it first so
  // the dashboard is not still ticked when the user comes back.
  setBubbleSelection({ topics: [], materials: [] });
  try { window.__studyhubArmReturn && window.__studyhubArmReturn(dest); } catch (e) {}
  window.location.href = dest;
}
function updateBubbleShare() {
  // Legacy bubble at bottom right removed – keep for backward compat but hide if exists
  const bubble = document.getElementById("bubble-share");
  if (bubble) bubble.classList.add("hidden");
}
function updateDashboardSelectionBar() {
  const bar = document.getElementById("dashboard-selection-bar");
  const countEl = document.getElementById("dashboard-selection-count");
  const openBtn = document.getElementById("dashboard-open-combined");
  const shareBtn = document.getElementById("dashboard-share-action");
  const deleteBtn = document.getElementById("dashboard-delete-action");
  if (!bar || !countEl) return;
  const sel = getBubbleSelection();
  const count = sel.topics.length + sel.materials.length;
  const hasSelection = count > 0;
  const hasDocs = sel.materials.length > 0 || sel.topics.length > 0;
  bar.classList.toggle("hidden", !hasSelection);
  countEl.textContent = String(count);
  if (openBtn) {
    openBtn.classList.toggle("hidden", !hasDocs);
    openBtn.disabled = !hasDocs;
  }
  if (shareBtn) shareBtn.classList.toggle("hidden", !hasSelection);
  if (deleteBtn) deleteBtn.classList.toggle("hidden", !hasSelection);
  // Update share href
  if (shareBtn) {
    if (hasSelection) shareBtn.href = `/share/bubble/?topics=${sel.topics.join(",")}&materials=${sel.materials.join(",")}`;
    else shareBtn.removeAttribute("href");
  }
}

function syncDashboardCheckboxes() {
  const sel = getBubbleSelection();
  const topicSet = new Set(sel.topics);
  const matSet = new Set(sel.materials);
  document.querySelectorAll(".bubble-topic-select").forEach((cb) => {
    const tid = Number(cb.dataset.topicId);
    cb.checked = topicSet.has(tid);
    // topic indeterminate if some of its docs checked
    const topicId = cb.dataset.topicId;
    const childMats = Array.from(document.querySelectorAll(`.bubble-material-select[data-topic-id="${topicId}"]`));
    if (childMats.length) {
      const all = childMats.every((c) => matSet.has(Number(c.dataset.materialId)));
      const some = childMats.some((c) => matSet.has(Number(c.dataset.materialId)));
      cb.indeterminate = !cb.checked && some;
      if (all && !cb.checked) {
        // if all docs checked but topic not checked, reflect as checked? 
        // Keep topic checked only if explicitly in selection; otherwise indeterminate is enough
      }
    }
  });
  document.querySelectorAll(".bubble-material-select").forEach((cb) => {
    const mid = Number(cb.dataset.materialId);
    cb.checked = matSet.has(mid);
  });
  document.querySelectorAll(".subject-select-input").forEach((cb) => {
    const sid = Number(cb.dataset.subjectId);
    if (!sid) return;
    const topicsInSubject = Array.from(document.querySelectorAll(`.bubble-topic-select[data-subject-id="${sid}"]`)).map((c) => Number(c.dataset.topicId));
    const matsInSubject = Array.from(document.querySelectorAll(`.bubble-material-select[data-subject-id="${sid}"]`)).map((c) => Number(c.dataset.materialId));
    if (!topicsInSubject.length && !matsInSubject.length) return;
    const allTopics = topicsInSubject.every((id) => topicSet.has(id));
    const allMats = matsInSubject.every((id) => matSet.has(id));
    const someTopics = topicsInSubject.some((id) => topicSet.has(id));
    const someMats = matsInSubject.some((id) => matSet.has(id));
    const all = allTopics && allMats;
    const some = someTopics || someMats;
    cb.checked = all;
    cb.indeterminate = !all && some;
  });
}

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return CSRF;
}

async function api(url, options = {}) {
  const opts = {
    headers: { "X-CSRFToken": getCookie("csrftoken") },
    credentials: "same-origin",
    ...options,
  };
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data === "object" ? JSON.stringify(data) : String(data);
    } catch (e) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function showInstantToast(message, tone = "success") {
  let host = document.getElementById("instant-toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "instant-toast-host";
    host.setAttribute("aria-live", "polite");
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.className = `instant-toast instant-toast--${tone}`;
  el.textContent = message;
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("is-visible"));
  setTimeout(() => {
    el.classList.remove("is-visible");
    setTimeout(() => el.remove(), 280);
  }, 2600);
}

/* ---------- Subjects ---------- */

async function loadSubjects() {
  state.subjects = await api(`${API}/subjects/`);
  renderSubjects();
}

function renderSubjects() {
  const grid = document.getElementById("subjects-grid");
  grid.innerHTML = "";
  if (!state.subjects.length) {
    grid.innerHTML =
      '<div class="empty-state">No subjects yet. Click <strong>+ New Subject</strong> to create your first one and start organizing.</div>';
    return;
  }
  state.subjects.forEach((s) => {
    const card = document.createElement("div");
    card.className = "subject-card";
    card.innerHTML = `
      <label class="subject-select" title="Select all items in this subject">
        <input type="checkbox" class="subject-select-input" data-subject-id="${s.id}" aria-label="Select all items in this subject">
      </label>
      <h3>${esc(s.name)}</h3>
      <p class="subject-meta">${esc(s.class_level)}</p>
      <p class="subject-meta">${s.topic_count} topics · ${s.material_count} files</p>`;
    const subjectSelect = card.querySelector(".subject-select-input");
    subjectSelect.addEventListener("click", (e) => e.stopPropagation());
    subjectSelect.addEventListener("change", async () => {
      subjectSelect.disabled = true;
      try {
        const topics = (await api(`${API}/topics/`)).filter((topic) => topic.subject === s.id);
        const materials = (await Promise.all(topics.map((topic) => api(`${API}/materials/?topic=${topic.id}`)))).flat();
        const selection = getBubbleSelection();
        if (subjectSelect.checked) {
          setBubbleSelection({topics: [...selection.topics, ...topics.map((topic) => topic.id)], materials: [...selection.materials, ...materials.map((material) => material.id)]});
        } else {
          const topicIds = new Set(topics.map((topic) => topic.id));
          const materialIds = new Set(materials.map((material) => material.id));
          setBubbleSelection({topics: selection.topics.filter((id) => !topicIds.has(id)), materials: selection.materials.filter((id) => !materialIds.has(id))});
        }
        // also update UI checkboxes in current panel if open
        if (state.currentSubject && state.currentSubject.id === s.id) {
          document.querySelectorAll(".bubble-topic-select").forEach((cb) => { cb.checked = subjectSelect.checked; });
          document.querySelectorAll(".bubble-material-select").forEach((cb) => { cb.checked = subjectSelect.checked; });
          // also need to ensure topic indeterminate cleared
          document.querySelectorAll(".bubble-topic-select, .bubble-material-select, .subject-select-input").forEach((cb) => cb.indeterminate = false);
          // re-sync via bubble
          const sel = getBubbleSelection();
          // ensure all topic/material checkboxes reflect
          syncDashboardCheckboxes();
        }
      } finally { subjectSelect.disabled = false; }
    });
    card.addEventListener("click", () => openSubject(s));
    grid.appendChild(card);
  });
  syncDashboardCheckboxes();
  const initialId = Number(window.INITIAL_SUBJECT_ID || 0);
  const initialSubject = state.subjects.find((subject) => subject.id === initialId);
  if (initialSubject) openSubject(initialSubject, false);
}

async function createSubject(e) {
  e.preventDefault();
  const form = e.target;
  const data = Object.fromEntries(new FormData(form));
  const btn = form.querySelector('button[type="submit"]');
  const origText = btn ? btn.textContent : "";
  // ── Instant ──────────────────────────────────────────────────────────
  const grid = document.getElementById("subjects-grid");
  let placeholder = null;
  if (grid && data.name) {
    if (grid.querySelector(".empty-state")) grid.innerHTML = "";
    placeholder = document.createElement("div");
    placeholder.className = "subject-card optimistic-item";
    placeholder.innerHTML = `<h3>${esc(data.name)}</h3><p class="subject-meta">${esc(data.class_level || "")}</p><p class="subject-meta"><span class="badge badge-optimistic">Creating ✓</span></p>`;
    placeholder.style.opacity = "0.72";
    grid.prepend(placeholder);
  }
  form.reset();
  form.classList.add("hidden");
  if (btn) { btn.disabled = true; btn.textContent = "Created ✓"; }
  showInstantToast(data.name ? `Subject “${data.name}” created — syncing…` : "Subject created — syncing…");
  setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = origText; } }, 650);
  try {
    await api(`${API}/subjects/`, {
      method: "POST",
      headers: { ...opts_headers(), "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (placeholder) placeholder.remove();
    await loadSubjects();
  } catch (err) {
    if (placeholder) { const b = placeholder.querySelector(".badge-optimistic"); if (b) b.textContent = "Failed"; placeholder.classList.add("optimistic-failed"); }
    showInstantToast(`Could not create subject: ${err.message}`, "error");
  }
}

function opts_headers() {
  return { "X-CSRFToken": getCookie("csrftoken") };
}

/* ---------- Subject panel ---------- */

async function openSubject(subject, updateUrl = true) {
  state.currentSubject = subject;
  document.getElementById("dashboard-header").classList.add("hidden");
  if (updateUrl && location.pathname !== `/dashboard/subject/${subject.id}/`) {
    history.pushState({ subjectId: subject.id }, "", `/dashboard/subject/${subject.id}/`);
  }
  document.getElementById("subjects-grid").classList.add("hidden");
  document.getElementById("btn-new-subject").classList.add("hidden");
  document.getElementById("subject-form").classList.add("hidden");
  document.getElementById("subject-panel").classList.remove("hidden");
  document.getElementById("access-panel").classList.add("hidden");

  document.getElementById("panel-title").textContent = subject.name;
  document.getElementById("panel-meta").textContent = `Class: ${subject.class_level}`;
  document.getElementById("open-viewer").href = `/viewer/subject/${subject.id}/`;
  document.getElementById("share-subject").href = `/share/subject/${subject.id}/`;

  await loadTopics(subject.id);
}

async function renameSubject() {
  const subject = state.currentSubject;
  if (!subject) return;
  const form = document.getElementById("rename-form");
  const input = document.getElementById("rename-input");
  document.getElementById("rename-class-input").value = subject.class_level || "";
  document.getElementById("panel-title").classList.add("hidden");
  form.classList.remove("hidden");
  input.value = subject.name;
  input.focus();
  input.select();
}

function closeRenameForm() {
  document.getElementById("rename-form").classList.add("hidden");
  document.getElementById("panel-title").classList.remove("hidden");
}

async function submitRename(e) {
  e.preventDefault();
  const subject = state.currentSubject;
  if (!subject) return;
  const newName = document.getElementById("rename-input").value.trim();
  const newClass = document.getElementById("rename-class-input").value.trim();
  const changed =
    (newName && newName !== subject.name) ||
    (newClass && newClass !== (subject.class_level || ""));
  if (!newName) {
    closeRenameForm();
    return;
  }
  if (!changed) {
    closeRenameForm();
    return;
  }
  const body = {};
  if (newName !== subject.name) body.name = newName;
  if (newClass !== (subject.class_level || "")) body.class_level = newClass;
  try {
    const updated = await api(`${API}/subjects/${subject.id}/`, {
      method: "PATCH",
      headers: { ...opts_headers(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    updated.color = updated.color || subject.color;
    updated.topic_count = updated.topic_count ?? subject.topic_count;
    updated.material_count = updated.material_count ?? subject.material_count;
    state.currentSubject = updated;
    const idx = state.subjects.findIndex((s) => s.id === subject.id);
    if (idx !== -1) state.subjects[idx] = updated;
    renderSubjects();
    document.getElementById("panel-title").textContent = updated.name;
    document.getElementById("panel-meta").textContent = `Class: ${updated.class_level}`;
    closeRenameForm();
  } catch (err) {
    alert("Edit failed: " + err.message);
  }
}

async function loadAccess(subjectId) {
  const list = document.getElementById("access-list");
  const search = document.getElementById("access-search");
  search.value = "";
  list.innerHTML = '<p class="muted">Loading…</p>';
  let people;
  try {
    people = await api(`${API}/subjects/${subjectId}/access/`);
  } catch (err) {
    list.innerHTML = '<p class="muted">Could not load the access list.</p>';
    return;
  }
  state.accessPeople = people;
  state.accessSubjectId = subjectId;
  renderAccessList();
}

function renderAccessList() {
  const list = document.getElementById("access-list");
  const q = document.getElementById("access-search").value.trim().toLowerCase();
  const all = state.accessPeople || [];
  list.innerHTML = "";
  if (!all.length) {
    list.innerHTML =
      '<p class="muted">Nobody has access yet. Click Share to invite someone.</p>';
    return;
  }
  const filtered = q
    ? all.filter((p) =>
        `${p.full_name} ${p.username}`.toLowerCase().includes(q)
      )
    : all;
  if (!filtered.length) {
    list.innerHTML = `<p class="muted">No one matches that search.</p>`;
    return;
  }
  filtered.forEach((p) => {
    const displayName = p.full_name || p.username;
    const avatar = p.avatar
      ? `<img class="user-avatar" src="${esc(p.avatar)}" alt="">`
      : `<span class="user-avatar user-avatar-fallback">${esc(displayName.charAt(0).toUpperCase())}</span>`;
    const row = document.createElement("div");
    row.className = "share-row card";
    row.innerHTML = `
      <div class="share-main">
        ${avatar}
        <strong>${esc(displayName)}</strong>
        <span class="muted">@${esc(p.username)}</span>
        <span class="badge">${p.kind === "subject" ? "whole subject" : `topic: ${esc(p.topic_name)}`}</span>
        ${p.has_password ? '<span class="badge badge-lock">&#128274;</span>' : ""}
        <span class="muted">${esc(p.shared_at)}</span>
      </div>
      <div class="share-actions">
        <button class="btn btn-danger btn-sm" type="button">Revoke</button>
      </div>`;
    row.querySelector(".btn-danger").addEventListener("click", async () => {
      if (!confirm(`Revoke ${displayName}'s (@${p.username}) access?`)) return;
      try {
        const res = await fetch(`/shared/${p.share_id}/revoke/`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": getCookie("csrftoken"),
            "X-Requested-With": "fetch",
          },
        });
        if (!res.ok) throw new Error(res.statusText);
        await loadAccess(state.accessSubjectId);
      } catch (err) {
        alert("Revoke failed: " + err.message);
      }
    });
    list.appendChild(row);
  });
}

function toggleAccess() {
  const panel = document.getElementById("access-panel");
  if (!state.currentSubject) return;
  if (panel.classList.contains("hidden")) {
    panel.classList.remove("hidden");
    loadAccess(state.currentSubject.id);
  } else {
    panel.classList.add("hidden");
  }
}

function backToSubjects(updateUrl = true) {
  if (updateUrl && location.pathname !== "/dashboard/") {
    history.pushState({}, "", "/dashboard/");
  }
  document.getElementById("subject-panel").classList.add("hidden");
  document.getElementById("subjects-grid").classList.remove("hidden");
  document.getElementById("btn-new-subject").classList.remove("hidden");
  document.getElementById("dashboard-header").classList.remove("hidden");
  state.currentSubject = null;
}

/* ---------- Topics & materials ---------- */

function rememberTopic(subjectId, topicId) {
  try { sessionStorage.setItem(`studyhub:last-topic:${subjectId}`, String(topicId)); } catch (err) {}
}

function restoreTopicPosition(subjectId) {
  let topicId = null;
  try { topicId = sessionStorage.getItem(`studyhub:last-topic:${subjectId}`); } catch (err) {}
  if (!topicId) return;
  const card = document.querySelector(`.topic-card[data-topic-id="${topicId}"]`);
  if (!card) return;
  requestAnimationFrame(() => {
    const top = card.getBoundingClientRect().top + window.scrollY - 88;
    window.scrollTo({ top: Math.max(0, top), behavior: "auto" });
  });
}

async function loadTopics(subjectId) {
  const allTopics = await api(`${API}/topics/`);
  const topics = allTopics.filter((t) => t.subject === subjectId);
  const list = document.getElementById("topics-list");
  list.innerHTML = "";

  if (!topics.length) {
    list.innerHTML =
      '<div class="card empty-state">No topics yet. Add one above, then upload your files into it.</div>';
    return;
  }

  for (const topic of topics) {
    const node = document.getElementById("tpl-topic").content.cloneNode(true);
    const topicCard = node.querySelector(".topic-card");
    topicCard.dataset.topicId = topic.id;
    const topicSelect = node.querySelector(".bubble-topic-select");
    topicSelect.dataset.topicId = topic.id;
    topicSelect.dataset.subjectId = topic.subject;
    topicSelect.checked = getBubbleSelection().topics.includes(topic.id);
    topicSelect.addEventListener("click", (event) => event.stopPropagation());
    topicSelect.addEventListener("change", async () => {
      const materials = await api(`${API}/materials/?topic=${topic.id}`);
      const selection = getBubbleSelection();
      if (topicSelect.checked) {
        const newMats = materials.map((m) => m.id).filter((id) => !selection.materials.includes(id));
        setBubbleSelection({topics: [...selection.topics, topic.id], materials: [...selection.materials, ...newMats]});
        // visually check all its docs
        topicCard.querySelectorAll(".bubble-material-select").forEach((cb) => { cb.checked = true; });
      } else {
        const matIds = new Set(materials.map((m) => m.id));
        setBubbleSelection({topics: selection.topics.filter((id) => id !== topic.id), materials: selection.materials.filter((id) => !matIds.has(id))});
        topicCard.querySelectorAll(".bubble-material-select").forEach((cb) => { cb.checked = false; });
      }
      syncDashboardCheckboxes();
    });
    const topicNameLink = node.querySelector(".topic-name");
    if (topicNameLink) {
      topicNameLink.textContent = topic.name;
      topicNameLink.href = `/viewer/topic/${topic.id}/`;
    }
    node.querySelector(".topic-count").textContent = `${topic.material_count} file${topic.material_count === 1 ? "" : "s"}`;
    const topicViewer = node.querySelector(".topic-viewer");
    if (topicViewer) topicViewer.href = `/viewer/topic/${topic.id}/`;
    const ul = node.querySelector(".material-list");
    const materials = await api(`${API}/materials/?topic=${topic.id}`);
    if (!materials.length) {
      ul.innerHTML = '<li class="muted">No files uploaded yet.</li>';
    }
    materials.forEach((m) => {
      const li = document.createElement("li");
      li.innerHTML = `
        <label class="bubble-material-check" title="Select document for Bubble Share"><input type="checkbox" class="bubble-material-select" aria-label="Select document"></label>
        <a href="/viewer/topic/${topic.id}/?material=${m.id}"><span class="file-chip">${esc(m.file_type)}</span> ${esc(m.title)}</a>`;
      const materialSelect = li.querySelector(".bubble-material-select");
      materialSelect.dataset.materialId = m.id;
      materialSelect.dataset.topicId = topic.id;
      materialSelect.dataset.subjectId = topic.subject;
      materialSelect.checked = getBubbleSelection().materials.includes(m.id);
      materialSelect.addEventListener("click", (event) => event.stopPropagation());
      materialSelect.addEventListener("change", () => {
        const selection = getBubbleSelection();
        if (materialSelect.checked) {
          setBubbleSelection({topics: selection.topics, materials: [...selection.materials, m.id]});
        } else {
          setBubbleSelection({topics: selection.topics, materials: selection.materials.filter((id) => id !== m.id)});
        }
        // update parent topic indeterminate/checked
        const topicMats = Array.from(topicCard.querySelectorAll(".bubble-material-select"));
        const allChecked = topicMats.every((cb) => cb.checked);
        const someChecked = topicMats.some((cb) => cb.checked);
        topicSelect.checked = allChecked;
        topicSelect.indeterminate = !allChecked && someChecked;
        syncDashboardCheckboxes();
      });
      ul.appendChild(li);
    });
    // after materials loaded, set topic indeterminate
    const topicMatsInit = Array.from(node.querySelectorAll(".bubble-material-select"));
    if (topicMatsInit.length) {
      const selMats = getBubbleSelection().materials;
      const all = topicMatsInit.every((cb) => selMats.includes(Number(cb.dataset.materialId)));
      const some = topicMatsInit.some((cb) => selMats.includes(Number(cb.dataset.materialId)));
      if (!topicSelect.checked && some) topicSelect.indeterminate = true;
      if (all && !topicSelect.checked) {
        // if all docs checked but topic not, keep indeterminate
      }
    }

    const uploadForm = node.querySelector(".upload-form");
    uploadForm.addEventListener("submit", (e) => uploadMaterial(e, topic.id));

    list.appendChild(node);
  }
  syncDashboardCheckboxes();
  restoreTopicPosition(subjectId);
}

async function addTopic(e) {
  e.preventDefault();
  const form = e.target;
  const name = new FormData(form).get("name").trim();
  if (!state.currentSubject || !name) return;
  const btn = form.querySelector('button[type="submit"]');
  const origText = btn ? btn.textContent : "";
  // ── Instant optimistic ───────────────────────────────────────────────
  const list = document.getElementById("topics-list");
  let placeholder = null;
  if (list) {
    if (list.querySelector(".empty-state")) list.innerHTML = "";
    placeholder = document.createElement("div");
    placeholder.className = "topic-card card optimistic-item";
    placeholder.innerHTML = `<div class="topic-head"><h3>${esc(name)} <span class="badge badge-optimistic">Creating ✓</span></h3><span class="badge topic-count">0 files</span></div>`;
    placeholder.style.opacity = "0.72";
    list.prepend(placeholder);
  }
  form.reset();
  if (btn) { btn.disabled = true; btn.textContent = "Created ✓"; }
  showInstantToast(`Topic “${name}” created — syncing in background`);
  setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = origText; } }, 650);
  // background
  try {
    await api(`${API}/topics/`, {
      method: "POST",
      headers: { ...opts_headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ name, subject: state.currentSubject.id }),
    });
    if (placeholder) placeholder.remove();
    await loadTopics(state.currentSubject.id);
  } catch (err) {
    if (placeholder) { placeholder.querySelector(".badge-optimistic").textContent = "Failed"; placeholder.classList.add("optimistic-failed"); }
    showInstantToast(`Could not create topic: ${err.message}`, "error");
  }
}

async function uploadMaterial(e, topicId) {
  e.preventDefault();
  const form = e.target;
  const fileInput = form.querySelector('input[type="file"]');
  const files = Array.from(fileInput?.files || []);
  if (!files.length) return;
  rememberTopic(state.currentSubject.id, topicId);
  const title = form.querySelector('input[name="title"]')?.value.trim() || "";
  const btn = form.querySelector('button[type="submit"]');
  const origText = btn.textContent;
  // ── Instant optimistic UI: show queued state on Enter instantly ──────
  const ul = form.closest(".topic-card")?.querySelector(".material-list") || document.querySelector(`.topic-card[data-topic-id="${topicId}"] .material-list`);
  const placeholders = [];
  if (ul) {
    // Remove empty placeholder if present
    const empty = ul.querySelector(".muted");
    if (empty && empty.textContent.includes("No files")) empty.remove();
    files.forEach((file) => {
      const li = document.createElement("li");
      li.className = "optimistic-item";
      li.innerHTML = `<label class="bubble-material-check"><input type="checkbox" disabled></label><a href="#"><span class="file-chip">…</span> ${esc(file.name)} <span class="badge badge-optimistic">Queued ✓</span></a>`;
      ul.appendChild(li);
      placeholders.push(li);
    });
  }
  form.reset();
  btn.disabled = true;
  btn.textContent = files.length === 1 ? "Queued ✓" : `Queued ${files.length} ✓`;
  showInstantToast(files.length === 1 ? `“${files[0].name}” queued — uploading in background` : `${files.length} files queued — uploading in background`);
  // Re-enable quickly so user can queue more; background continues
  setTimeout(() => { btn.disabled = false; btn.textContent = origText; }, 700);

  // ── Background upload (non-blocking) ─────────────────────────────────
  let uploaded = 0;
  const bg = async () => {
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const li = placeholders[i];
      if (li) li.querySelector(".badge-optimistic").textContent = "Uploading…";
      try {
        const fd = new FormData();
        fd.append("file", file, file.name);
        fd.append("topic", topicId);
        if (title && files.length === 1) fd.append("title", title);
        await api(`${API}/materials/`, { method: "POST", body: fd });
        uploaded += 1;
        if (li) {
          li.querySelector(".badge-optimistic").textContent = "Done ✓";
          li.classList.add("optimistic-done");
        }
      } catch (err) {
        if (li) {
          li.querySelector(".badge-optimistic").textContent = "Failed";
          li.classList.add("optimistic-failed");
          li.title = err.message;
        }
        // Keep placeholder but mark failed; don't alert blocking
        showInstantToast(`Upload failed for “${file.name}”: ${err.message}`, "error");
      }
    }
    if (uploaded) {
      try { await loadTopics(state.currentSubject.id); } catch (e) {}
      if (uploaded === files.length) showInstantToast(uploaded === 1 ? "File uploaded ✓" : `${uploaded} files uploaded ✓`);
    }
  };
  bg();
}

/* ---------- Wire up ---------- */

document.getElementById("rename-subject").addEventListener("click", renameSubject);
document.getElementById("rename-form").addEventListener("submit", submitRename);
document.getElementById("rename-cancel").addEventListener("click", closeRenameForm);
document.getElementById("rename-input").addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeRenameForm();
});
document.getElementById("access-search").addEventListener("input", renderAccessList);
document.getElementById("access-subject").addEventListener("click", toggleAccess);
const settingsTrigger = document.getElementById("subject-settings");
const settingsMenu = document.getElementById("subject-settings-menu");
function closeSettingsMenu() {
  settingsMenu.classList.add("hidden");
  settingsTrigger.setAttribute("aria-expanded", "false");
}
settingsTrigger.addEventListener("click", (e) => {
  e.stopPropagation();
  const isOpen = !settingsMenu.classList.contains("hidden");
  if (isOpen) closeSettingsMenu();
  else {
    settingsMenu.classList.remove("hidden");
    settingsTrigger.setAttribute("aria-expanded", "true");
  }
});
settingsMenu.addEventListener("click", () => closeSettingsMenu());
document.addEventListener("click", (e) => {
  if (!e.target.closest(".subject-settings")) closeSettingsMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeSettingsMenu();
});
document.addEventListener("click", () => {
  document.querySelectorAll(".topic-settings-menu:not(.hidden)").forEach((menu) => {
    menu.classList.add("hidden");
    menu.closest(".topic-settings")?.querySelector(".topic-settings-trigger")?.setAttribute("aria-expanded", "false");
  });
});
document.getElementById("btn-new-subject").addEventListener("click", () => {
  document.getElementById("subject-form").classList.toggle("hidden");
});
document.getElementById("cancel-subject").addEventListener("click", () => {
  document.getElementById("subject-form").classList.add("hidden");
});
document.getElementById("subject-form").addEventListener("submit", createSubject);
document.getElementById("topic-form").addEventListener("submit", addTopic);
document.getElementById("bubble-share-action")?.addEventListener("click", (event) => {
  event.preventDefault();
  const selection = getBubbleSelection();
  if (selection.topics.length || selection.materials.length) {
    try { window.__studyhubArmReturn && window.__studyhubArmReturn(); } catch (e) {}
    location.href = `/share/bubble/?topics=${selection.topics.join(",")}&materials=${selection.materials.join(",")}`;
  }
});
document.getElementById("bubble-delete-action")?.addEventListener("click", async () => {
  const selection = getBubbleSelection();
  const count = selection.topics.length + selection.materials.length;
  if (!count || !confirm(`Delete ${count} selected item${count === 1 ? "" : "s"}?`)) return;
  try {
    for (const id of selection.materials) await api(`${API}/materials/${id}/`, { method: "DELETE" });
    for (const id of selection.topics) await api(`${API}/topics/${id}/`, { method: "DELETE" });
    setBubbleSelection({topics: [], materials: []});
    if (state.currentSubject) await loadTopics(state.currentSubject.id);
  } catch (err) { alert("Delete failed: " + err.message); }
});
document.getElementById("bubble-clear-action")?.addEventListener("click", () => {
  setBubbleSelection({topics: [], materials: []});
  document.querySelectorAll(".bubble-topic-select, .bubble-material-select, .subject-select-input").forEach((input) => { input.checked = false; input.indeterminate = false; });
});
document.getElementById("bubble-open-combined")?.addEventListener("click", (e) => {
  e.preventDefault();
  openDashboardCombined();
});
document.getElementById("dashboard-open-combined")?.addEventListener("click", openDashboardCombined);
document.getElementById("dashboard-share-action")?.addEventListener("click", (e) => {
  e.preventDefault();
  const sel = getBubbleSelection();
  if (sel.topics.length || sel.materials.length) {
    try { window.__studyhubArmReturn && window.__studyhubArmReturn(); } catch (e) {}
    location.href = `/share/bubble/?topics=${sel.topics.join(",")}&materials=${sel.materials.join(",")}`;
  }
});
document.getElementById("dashboard-delete-action")?.addEventListener("click", async () => {
  const sel = getBubbleSelection();
  const count = sel.topics.length + sel.materials.length;
  if (!count || !confirm(`Delete ${count} selected item${count === 1 ? "" : "s"}?`)) return;
  try {
    for (const id of sel.materials) await api(`${API}/materials/${id}/`, { method: "DELETE" });
    for (const id of sel.topics) await api(`${API}/topics/${id}/`, { method: "DELETE" });
    setBubbleSelection({topics: [], materials: []});
    if (state.currentSubject) await loadTopics(state.currentSubject.id);
    await loadSubjects();
  } catch (err) { alert("Delete failed: " + err.message); }
});
document.getElementById("dashboard-clear-selection")?.addEventListener("click", () => {
  setBubbleSelection({topics: [], materials: []});
  document.querySelectorAll(".bubble-topic-select, .bubble-material-select, .subject-select-input").forEach((input) => { input.checked = false; input.indeterminate = false; });
});
document.getElementById("back-to-subjects").addEventListener("click", (e) => {
  e.preventDefault();
  backToSubjects();
});

window.addEventListener("popstate", () => {
  const match = location.pathname.match(/^\/dashboard\/subject\/(\d+)\/$/);
  const subject = match && state.subjects.find((item) => item.id === Number(match[1]));
  if (subject) openSubject(subject, false);
  else backToSubjects(false);
});

window.addEventListener("pageshow", (event) => {
  // Returning from the share page may restore this page from the bfcache;
  // re-sync the ticked documents with what is actually remembered.
  if (event.persisted) {
    syncDashboardCheckboxes();
    updateDashboardSelectionBar();
  }
});

loadSubjects();
updateBubbleShare();
syncDashboardCheckboxes();
updateDashboardSelectionBar();
