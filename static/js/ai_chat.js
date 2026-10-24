(function () {
  const tabs = document.querySelectorAll("#ai-tab, [data-ai-open]");
  const drawer = document.getElementById("ai-drawer");
  if (!tabs.length || !drawer) return;

  const closeBtn = document.getElementById("ai-close");
  const messagesEl = document.getElementById("ai-messages");
  const form = document.getElementById("ai-form");
  const input = document.getElementById("ai-input");
  const sendBtn = document.getElementById("ai-send");
  const dock = document.getElementById("ai-dock");
  const dockToggle = document.getElementById("ai-dock-toggle");

  const subjectEl = drawer.querySelector(".ai-subject");
  const subjectId = subjectEl ? subjectEl.dataset.subjectId : null;
  const history = [];
  let pending = false;

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  }

  function mdToHtml(md) {
    let out = esc(md);
    out = out.replace(/```([\s\S]*?)```/g, (_, code) => `<pre class="ai-code">${code.trim()}</pre>`);
    out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|\n)\s*[-*]\s+/g, "$1• ");
    out = out.replace(/\n/g, "<br>");
    return out;
  }

  function addMsg(role, html) {
    const el = document.createElement("div");
    el.className = `ai-msg ai-msg-${role === "model" ? "bot" : "user"}`;
    el.innerHTML = html;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function setPending(on) {
    pending = on;
    sendBtn.disabled = on;
    input.disabled = on;
  }

  function showTyping() {
    const el = addMsg("model", '<span class="ai-typing"><i></i><i></i><i></i></span>');
    el.classList.add("ai-msg-typing");
    return el;
  }

  function csrfToken() {
    if (window.CSRF_TOKEN) return window.CSRF_TOKEN;
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function ask(question) {
    history.push({ role: "user", text: question });
    if (history.length > 10) history.splice(0, history.length - 10);

    addMsg("user", esc(question));
    const typing = showTyping();
    setPending(true);
    try {
      const res = await fetch("/ai/ask/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({
          question,
          subject_id: Number(subjectId),
          history: history.slice(0, -1),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || "Something went wrong. Try again.");
      }
      history.push({ role: "model", text: data.answer });
      if (history.length > 10) history.splice(0, history.length - 10);
      typing.remove();
      addMsg("model", mdToHtml(data.answer));
    } catch (err) {
      typing.remove();
      history.pop();
      addMsg("model", `<span class="ai-error">${esc(err.message)}</span>`);
    } finally {
      setPending(false);
      input.focus();
    }
  }

  function setExpanded(open) {
    tabs.forEach((tab) => tab.setAttribute("aria-expanded", String(open)));
  }

  function setDockOpen(open) {
    if (!dock) return;
    dock.classList.toggle("is-open", open);
    if (dockToggle) dockToggle.setAttribute("aria-expanded", String(open));
  }

  if (dockToggle) {
    dockToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      setDockOpen(true);
    });
    document.addEventListener("click", (event) => {
      if (
        dock &&
        dock.classList.contains("is-open") &&
        !dock.contains(event.target) &&
        !drawer.contains(event.target)
      ) {
        setDockOpen(false);
      }
    });
    document.addEventListener("keydown", (event) => {
      if (
        event.key === "Escape" &&
        dock &&
        dock.classList.contains("is-open") &&
        !drawer.classList.contains("open")
      ) {
        setDockOpen(false);
      }
    });
  }

  function openDrawer() {
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    setExpanded(true);
    setDockOpen(false);
    input.focus();
  }

  tabs.forEach((tab) => tab.addEventListener("click", openDrawer));

  closeBtn.addEventListener("click", () => {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    setExpanded(false);
    setDockOpen(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer.classList.contains("open")) {
      drawer.classList.remove("open");
      drawer.setAttribute("aria-hidden", "true");
      setExpanded(false);
      setDockOpen(false);
    }
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = input.value.trim();
    if (!question || pending) return;
    input.value = "";
    ask(question);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
})();
