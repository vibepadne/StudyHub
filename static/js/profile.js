function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(";").shift();
  return window.CSRF_TOKEN;
}

const avatarBtn = document.getElementById("avatar-btn");
const avatarMenu = document.getElementById("avatar-menu");
const viewOption = document.getElementById("view-avatar-option");
const changeOption = document.getElementById("change-avatar-option");
const fileInput = document.getElementById("avatar-file-input");
const statusEl = document.getElementById("avatar-status");
const modal = document.getElementById("avatar-modal");
const modalImg = document.getElementById("modal-img");
const modalCloseBtn = document.getElementById("modal-close-btn");
const modalChangeBtn = document.getElementById("modal-change-btn");

let hasPhoto = !!(viewOption && !viewOption.disabled);

// Ensure profile opens at very top (below navbar), not scrolled to password section
if ("scrollRestoration" in history) history.scrollRestoration = "manual";
window.addEventListener("DOMContentLoaded", () => {
  // Remove any hash that would jump to password form
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  window.scrollTo({ top: 0, left: 0, behavior: "auto" });
});
window.addEventListener("load", () => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));

function showStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.style.color = isError ? "var(--danger-text)" : "var(--success-text)";
  statusEl.classList.remove("hidden");
  setTimeout(() => statusEl.classList.add("hidden"), 4000);
}

/* Popover menu */
function closeMenu() {
  if (!avatarMenu || !avatarBtn) return;
  avatarMenu.classList.add("hidden");
  avatarBtn.setAttribute("aria-expanded", "false");
}
if (avatarBtn && avatarMenu) {
  avatarBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = !avatarMenu.classList.contains("hidden");
    avatarMenu.classList.toggle("hidden", open);
    avatarBtn.setAttribute("aria-expanded", String(!open));
  });
}

document.addEventListener("click", (e) => {
  if (avatarMenu && avatarBtn &&
      !avatarMenu.classList.contains("hidden") &&
      !avatarMenu.contains(e.target)) {
    closeMenu();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeMenu();
    closeModal();
  }
});

/* View modal */
function openModal() {
  if (!modal || !modalImg) return;
  const img = document.getElementById("avatar-preview-img");
  if (!img) return;
  modalImg.src = img.src;
  modal.classList.remove("hidden");
}
function closeModal() {
  if (modal) modal.classList.add("hidden");
}

if (viewOption) {
  viewOption.addEventListener("click", () => {
    closeMenu();
    openModal();
  });
}
if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeModal);
if (modal) {
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
}

/* Change photo */
function triggerPicker() {
  closeMenu();
  closeModal();
  if (fileInput) fileInput.click();
}
if (changeOption) changeOption.addEventListener("click", triggerPicker);
if (modalChangeBtn) modalChangeBtn.addEventListener("click", triggerPicker);

if (fileInput) fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;
  statusEl.textContent = "Uploading…";
  statusEl.classList.remove("hidden");
  try {
    const fd = new FormData();
    fd.append("avatar", file);
    const res = await fetch("/profile/avatar/", {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin",
      body: fd,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed.");
    applyPhoto(data.url);
    showStatus("Profile photo updated.");
  } catch (err) {
    showStatus(err.message, true);
  } finally {
    fileInput.value = "";
  }
});

function applyPhoto(url) {
  let img = document.getElementById("avatar-preview-img");
  const initials = document.getElementById("avatar-initials");
  if (!img && initials) {
    img = document.createElement("img");
    img.id = "avatar-preview-img";
    img.alt = "Profile picture";
    initials.replaceWith(img);
  }
  if (img) img.src = url;

  const navAvatar = document.querySelector(".nav-avatar");
  if (navAvatar) {
    let navImg = navAvatar.querySelector("img");
    const navInitials = navAvatar.querySelector(".avatar-initials");
    if (!navImg && navInitials) {
      navImg = document.createElement("img");
      navInitials.replaceWith(navImg);
    }
    if (navImg) navImg.src = url;
  }

  if (!hasPhoto) {
    hasPhoto = true;
    if (viewOption) viewOption.disabled = false;
  }
}
