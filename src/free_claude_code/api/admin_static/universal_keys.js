(() => {
  "use strict";

  const state = {
    keys: [],
    loading: false,
    rawKeyGenerated: null,
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

  function showBanner(rawKey, keyName) {
    const banner = byId("ukBannerSecret");
    if (!banner) return;
    state.rawKeyGenerated = rawKey;
    byId("ukSecretKeyValue").textContent = rawKey;
    byId("ukSecretKeyName").textContent = keyName || "New Key";
    banner.hidden = false;
    banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function hideBanner() {
    const banner = byId("ukBannerSecret");
    if (banner) banner.hidden = true;
    state.rawKeyGenerated = null;
  }

  async function loadKeys() {
    state.loading = true;
    const tbody = byId("ukTableBody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:24px;">Loading keys...</td></tr>`;
    }
    try {
      const data = await api("/admin/api/universal-keys");
      state.keys = data.keys || [];
      renderKeys();
    } catch (err) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--error); padding:24px;">Failed to load keys: ${escapeHtml(err.message)}</td></tr>`;
      }
    } finally {
      state.loading = false;
    }
  }

  function renderKeys() {
    const tbody = byId("ukTableBody");
    if (!tbody) return;
    if (state.keys.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:32px;">No Universal API Keys found. Generate one above to connect Claude Code, Cline, or external clients.</td></tr>`;
      return;
    }

    tbody.innerHTML = state.keys.map((k) => {
      const isAct = k.is_active;
      const statusBadge = isAct
        ? `<span class="badge badge-active">● Active</span>`
        : `<span class="badge badge-revoked">○ Revoked</span>`;
      
      const lastUsed = k.last_used_at
        ? new Date(k.last_used_at).toLocaleString()
        : "Never";

      const defModel = k.default_model
        ? `<span class="badge badge-model">${escapeHtml(k.default_model)}</span>`
        : `<span style="color:var(--muted); font-size:0.8rem;">(Global default)</span>`;

      return `
        <tr data-key-id="${k.id}">
          <td><strong>${escapeHtml(k.name)}</strong></td>
          <td><code>${escapeHtml(k.key_prefix)}</code></td>
          <td>${defModel}</td>
          <td>${k.total_requests || 0}</td>
          <td style="color:var(--muted); font-size:0.8rem;">${lastUsed}</td>
          <td>${statusBadge}</td>
          <td>
            <div style="display:flex; gap:8px;">
              <button class="secondary-button uk-toggle-btn" style="padding:4px 10px; font-size:0.8rem;" data-id="${k.id}">
                ${isAct ? "Revoke" : "Activate"}
              </button>
              <button class="btn-icon-danger uk-delete-btn" title="Delete key" data-id="${k.id}" data-name="${escapeHtml(k.name)}">
                Delete
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join("");

    tbody.querySelectorAll(".uk-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleKey(btn.dataset.id));
    });

    tbody.querySelectorAll(".uk-delete-btn").forEach((btn) => {
      btn.addEventListener("click", () => deleteKey(btn.dataset.id, btn.dataset.name));
    });
  }

  async function handleCreateKey(e) {
    e.preventDefault();
    const btn = byId("ukCreateBtn");
    const nameInput = byId("ukInputName");
    const modelInput = byId("ukInputModel");
    const rpmInput = byId("ukInputRpm");
    const expiryInput = byId("ukInputExpiry");

    const name = nameInput.value.trim();
    if (!name) {
      alert("Please enter a name for the Universal Key.");
      return;
    }

    const payload = {
      name: name,
      default_model: modelInput.value.trim() || null,
      rate_limit_rpm: parseInt(rpmInput.value, 10) || 60,
      expires_in_days: expiryInput.value ? parseInt(expiryInput.value, 10) : null,
    };

    btn.disabled = true;
    btn.textContent = "Generating...";
    try {
      const res = await api("/admin/api/universal-keys", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      nameInput.value = "";
      modelInput.value = "";
      showBanner(res.raw_key, res.key.name);
      await loadKeys();
    } catch (err) {
      alert("Error generating Universal Key: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Generate Universal Key";
    }
  }

  async function toggleKey(id) {
    try {
      await api(`/admin/api/universal-keys/${id}/toggle`, { method: "POST" });
      await loadKeys();
    } catch (err) {
      alert("Error toggling key: " + err.message);
    }
  }

  async function deleteKey(id, name) {
    if (!confirm(`Are you sure you want to permanently delete the Universal Key "${name}"? Any clients using this key will immediately lose access.`)) {
      return;
    }
    try {
      await api(`/admin/api/universal-keys/${id}`, { method: "DELETE" });
      await loadKeys();
    } catch (err) {
      alert("Error deleting key: " + err.message);
    }
  }

  function copySecretKey() {
    if (!state.rawKeyGenerated) return;
    navigator.clipboard.writeText(state.rawKeyGenerated).then(() => {
      const copyBtn = byId("ukCopyBtn");
      if (copyBtn) {
        const orig = copyBtn.textContent;
        copyBtn.textContent = "Copied!";
        setTimeout(() => { copyBtn.textContent = orig; }, 2000);
      }
    }).catch(() => {
      alert("Failed to copy to clipboard. Please copy manually.");
    });
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
    const createForm = byId("ukCreateForm");
    if (createForm) {
      createForm.addEventListener("submit", handleCreateKey);
    }
    const copyBtn = byId("ukCopyBtn");
    if (copyBtn) {
      copyBtn.addEventListener("click", copySecretKey);
    }
    const dismissBannerBtn = byId("ukDismissBannerBtn");
    if (dismissBannerBtn) {
      dismissBannerBtn.addEventListener("click", hideBanner);
    }
  }

  window.UniversalKeysUI = {
    init,
    activate: () => {
      loadKeys();
    },
    refresh: loadKeys,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
