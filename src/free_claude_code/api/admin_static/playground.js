(() => {
  "use strict";

  const state = {
    sessions: [],
    currentSessionId: null,
    messages: [],
    sending: false,
  };

  const byId = (id) => document.getElementById(id);

  async function api(path, options = {}) {
    if (window.FCCAdminApi) {
      return window.FCCAdminApi(path, options);
    }
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = body.detail || "";
      } catch {}
      throw new Error(detail || `${res.status} ${res.statusText}`);
    }
    return res.json();
  }

  async function loadSessions() {
    try {
      const data = await api("/admin/api/playground/sessions");
      state.sessions = data.sessions || [];
      renderSessions();
      if (!state.currentSessionId && state.sessions.length > 0) {
        await selectSession(state.sessions[0].id);
      } else if (state.sessions.length === 0) {
        await createSession("New Playground Session", "auto");
      }
    } catch (err) {
      console.error("Failed to load playground sessions:", err);
    }
  }

  function renderSessions() {
    const list = byId("pgSessionList");
    if (!list) return;

    if (state.sessions.length === 0) {
      list.innerHTML = `<div style="padding:16px; font-size:0.8rem; color:var(--muted); text-align:center;">No sessions yet.</div>`;
      return;
    }

    list.innerHTML = state.sessions.map((s) => {
      const isActive = s.id === state.currentSessionId;
      const modelLabel = s.selected_model || "auto";
      const updatedStr = s.updated_at ? new Date(s.updated_at).toLocaleDateString() : "";

      return `
        <div class="pg-session-item ${isActive ? "active" : ""}" data-session-id="${s.id}">
          <div class="pg-session-info">
            <span class="pg-session-title">${escapeHtml(s.title || "Untitled Session")}</span>
            <span class="pg-session-meta">${escapeHtml(modelLabel)} · ${updatedStr}</span>
          </div>
          <button class="btn-icon-danger pg-delete-session-btn" title="Delete session" data-id="${s.id}">✕</button>
        </div>
      `;
    }).join("");

    list.querySelectorAll(".pg-session-item").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.closest(".pg-delete-session-btn")) return;
        selectSession(el.dataset.sessionId);
      });
    });

    list.querySelectorAll(".pg-delete-session-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSession(btn.dataset.id);
      });
    });
  }

  async function createSession(title = "New Playground Session", model = "auto") {
    try {
      const res = await api("/admin/api/playground/sessions", {
        method: "POST",
        body: JSON.stringify({
          title: title,
          selected_model: model,
        }),
      });
      state.currentSessionId = res.id;
      await loadSessions();
      await selectSession(res.id);
    } catch (err) {
      alert("Failed to create session: " + err.message);
    }
  }

  async function selectSession(sessionId) {
    state.currentSessionId = sessionId;
    renderSessions();
    const msgsContainer = byId("pgMessagesContainer");
    if (msgsContainer) {
      msgsContainer.innerHTML = `<div class="pg-empty-state">Loading messages...</div>`;
    }

    try {
      const data = await api(`/admin/api/playground/sessions/${sessionId}`);
      state.messages = data.messages || [];
      const session = data.session || {};
      
      const modelSelect = byId("pgModelSelect");
      if (modelSelect && session.selected_model) {
        modelSelect.value = session.selected_model;
      }
      
      const titleEl = byId("pgActiveSessionTitle");
      if (titleEl) {
        titleEl.textContent = session.title || "Playground Session";
      }

      renderMessages();
    } catch (err) {
      if (msgsContainer) {
        msgsContainer.innerHTML = `<div class="pg-empty-state" style="color:var(--error);">Failed to load messages: ${escapeHtml(err.message)}</div>`;
      }
    }
  }

  async function deleteSession(sessionId) {
    if (!confirm("Are you sure you want to delete this test session?")) return;
    try {
      await api(`/admin/api/playground/sessions/${sessionId}`, { method: "DELETE" });
      if (state.currentSessionId === sessionId) {
        state.currentSessionId = null;
        state.messages = [];
      }
      await loadSessions();
    } catch (err) {
      alert("Failed to delete session: " + err.message);
    }
  }

  function renderMessages() {
    const container = byId("pgMessagesContainer");
    if (!container) return;

    if (state.messages.length === 0) {
      container.innerHTML = `
        <div class="pg-empty-state">
          <p>This session has no messages yet.</p>
          <span style="font-size:0.82rem; color:var(--muted);">Select a model above, type a test prompt below, and hit Send to test routing, latency, and provider failover.</span>
        </div>
      `;
      return;
    }

    container.innerHTML = state.messages.map((m) => {
      const isUser = m.role === "user";
      if (isUser) {
        return `
          <div class="pg-msg user">
            <div class="pg-msg-bubble">${escapeHtml(m.content)}</div>
            <div class="pg-msg-meta" style="justify-content: flex-end;">
              <span>You · ${m.created_at ? new Date(m.created_at).toLocaleTimeString() : ""}</span>
            </div>
          </div>
        `;
      }

      // Assistant message
      const speedBadge = m.latency_ms != null
        ? `<span class="pg-badge-stat speed">⚡ ${m.latency_ms}ms</span>`
        : "";
      const modelBadge = m.resolved_model
        ? `<span class="pg-badge-stat">🤖 ${escapeHtml(m.resolved_model)}</span>`
        : "";
      const providerBadge = m.resolved_provider
        ? `<span class="pg-badge-stat">🏢 ${escapeHtml(m.resolved_provider)}</span>`
        : "";
      const tokensBadge = m.tokens_used
        ? `<span class="pg-badge-stat">🔢 ${m.tokens_used} tok</span>`
        : "";

      const errorAlert = m.error_detail
        ? `<div style="background:var(--error-bg); border:1px solid var(--error-border); color:var(--error); padding:8px 12px; border-radius:var(--radius-sm); margin-top:8px; font-size:0.85rem;">Error: ${escapeHtml(m.error_detail)}</div>`
        : "";

      return `
        <div class="pg-msg assistant">
          <div class="pg-msg-bubble">${escapeHtml(m.content || "")}</div>
          ${errorAlert}
          <div class="pg-msg-meta">
            ${speedBadge}
            ${modelBadge}
            ${providerBadge}
            ${tokensBadge}
            <span>${m.created_at ? new Date(m.created_at).toLocaleTimeString() : ""}</span>
          </div>
        </div>
      `;
    }).join("");

    container.scrollTop = container.scrollHeight;
  }

  async function handleSendMessage() {
    if (state.sending) return;
    const textarea = byId("pgPromptInput");
    const prompt = textarea.value.trim();
    if (!prompt) return;

    if (!state.currentSessionId) {
      await createSession("New Playground Session", "auto");
    }

    const modelSelect = byId("pgModelSelect");
    const selectedModel = modelSelect ? modelSelect.value : "auto";

    // Optimistically add user message
    const userMsg = {
      role: "user",
      content: prompt,
      created_at: new Date().toISOString(),
    };
    state.messages.push(userMsg);
    renderMessages();

    textarea.value = "";
    state.sending = true;
    updateInputState();

    try {
      const res = await api(`/admin/api/playground/sessions/${state.currentSessionId}/chat`, {
        method: "POST",
        body: JSON.stringify({
          prompt: prompt,
          model: selectedModel,
        }),
      });

      const assistantMsg = {
        role: "assistant",
        content: res.content || "",
        resolved_provider: res.resolved_provider,
        resolved_model: res.resolved_model,
        latency_ms: res.latency_ms,
        tokens_used: res.tokens_used,
        error_detail: res.error,
        created_at: new Date().toISOString(),
      };
      state.messages.push(assistantMsg);
      renderMessages();

      // Refresh session list so timestamps/titles update
      loadSessions();
    } catch (err) {
      const errorMsg = {
        role: "assistant",
        content: "Error executing chat prompt.",
        error_detail: err.message,
        created_at: new Date().toISOString(),
      };
      state.messages.push(errorMsg);
      renderMessages();
    } finally {
      state.sending = false;
      updateInputState();
      textarea.focus();
    }
  }

  function updateInputState() {
    const btn = byId("pgSendBtn");
    const textarea = byId("pgPromptInput");
    const statusText = byId("pgSendStatus");

    if (btn) {
      btn.disabled = state.sending;
      btn.textContent = state.sending ? "Running..." : "Send Prompt";
    }
    if (textarea) {
      textarea.disabled = state.sending;
    }
    if (statusText) {
      statusText.textContent = state.sending ? "Querying provider & routing..." : "";
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function init() {
    const newSessionBtn = byId("pgNewSessionBtn");
    if (newSessionBtn) {
      newSessionBtn.addEventListener("click", () => {
        createSession("Test Session " + (state.sessions.length + 1), "auto");
      });
    }

    const sendBtn = byId("pgSendBtn");
    if (sendBtn) {
      sendBtn.addEventListener("click", handleSendMessage);
    }

    const textarea = byId("pgPromptInput");
    if (textarea) {
      textarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          handleSendMessage();
        }
      });
    }
  }

  window.PlaygroundUI = {
    init,
    activate: () => {
      loadSessions();
    },
    refresh: loadSessions,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
