(() => {
  "use strict";

  const state = {
    keys: [],
    loading: false,
    rawKeyGenerated: null,
    universalModel: {
      alias: "free-claude-universal",
      target_model: null,
      available_models: [],
    },
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

  function copyToClipboard(text, btnElement, successText = "Copied!") {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      if (btnElement) {
        const originalText = btnElement.textContent;
        btnElement.textContent = successText;
        btnElement.classList.add("btn-copied");
        setTimeout(() => {
          btnElement.textContent = originalText;
          btnElement.classList.remove("btn-copied");
        }, 2000);
      }
    }).catch(() => {
      // Fallback for browsers that restrict clipboard in non-secure contexts
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        if (btnElement) {
          const originalText = btnElement.textContent;
          btnElement.textContent = successText;
          setTimeout(() => { btnElement.textContent = originalText; }, 2000);
        }
      } catch (e) {
        alert("Please copy manually:\n" + text);
      }
      document.body.removeChild(ta);
    });
  }

  function getApiBaseUrl() {
    return window.location.origin + "/v1";
  }

  function updateConnectionDetails() {
    const baseUrl = getApiBaseUrl();
    const baseCode = byId("ukApiBaseUrl");
    if (baseCode) {
      baseCode.textContent = baseUrl;
    }

    const curlElem = byId("ukCurlSnippet");
    if (curlElem) {
      const alias = state.universalModel.alias || "free-claude-universal";
      curlElem.textContent = `curl -X POST ${baseUrl}/chat/completions \\
  -H "Authorization: Bearer YOUR_UNIVERSAL_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"model": "${alias}", "messages": [{"role": "user", "content": "Hello!"}]}'`;
    }
  }

  async function loadUniversalModel() {
    try {
      const data = await api("/admin/api/universal-model");
      state.universalModel = {
        alias: data.alias || "free-claude-universal",
        target_model: data.target_model,
        available_models: data.available_models || [],
      };
      renderUniversalModelUI();
    } catch (err) {
      console.warn("Failed to load universal model config:", err);
    }
  }

  function renderUniversalModelUI() {
    const aliasInput = byId("ukModelAliasInput");
    if (aliasInput && document.activeElement !== aliasInput) {
      aliasInput.value = state.universalModel.alias || "free-claude-universal";
    }

    const select = byId("ukModelTargetSelect");
    if (select) {
      const currentVal = state.universalModel.target_model || "auto";
      const available = state.universalModel.available_models || [];
      
      let html = `<option value="auto">auto (Smart Fallback Router)</option>`;
      let hasCustom = currentVal !== "auto";
      
      for (const m of available) {
        if (m.id === "auto") continue;
        if (m.id === currentVal) hasCustom = false;
        html += `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || m.id)}</option>`;
      }
      if (hasCustom && currentVal) {
        html += `<option value="${escapeHtml(currentVal)}">${escapeHtml(currentVal)} (Custom)</option>`;
      }
      select.innerHTML = html;
      select.value = currentVal;
    }

    const statusText = byId("ukModelStatusText");
    if (statusText) {
      const alias = state.universalModel.alias || "free-claude-universal";
      const target = state.universalModel.target_model || "auto (Smart Fallback Router)";
      statusText.innerHTML = `${escapeHtml(alias)} &rarr; <strong>${escapeHtml(target)}</strong>`;
    }

    updateConnectionDetails();
  }

  async function handleSaveUniversalModel(e) {
    if (e) e.preventDefault();
    const btn = byId("ukSaveModelBtn");
    const aliasInput = byId("ukModelAliasInput");
    const targetSelect = byId("ukModelTargetSelect");

    const alias = (aliasInput.value || "").trim();
    if (!alias) {
      alert("Please provide a valid Universal Model Identifier / Alias.");
      return;
    }

    const targetModel = targetSelect.value === "auto" ? null : targetSelect.value.trim();

    if (btn) {
      btn.disabled = true;
      btn.textContent = "Saving...";
    }

    try {
      const res = await api("/admin/api/universal-model", {
        method: "POST",
        body: JSON.stringify({
          alias: alias,
          target_model: targetModel,
        }),
      });
      state.universalModel.alias = res.alias;
      state.universalModel.target_model = res.target_model;
      renderUniversalModelUI();
      if (btn) {
        btn.textContent = "Saved!";
        setTimeout(() => { btn.textContent = "Save Model Settings"; btn.disabled = false; }, 1800);
      }
    } catch (err) {
      alert("Error saving universal model settings: " + err.message);
      if (btn) {
        btn.textContent = "Save Model Settings";
        btn.disabled = false;
      }
    }
  }

  async function handleResetUniversalModel() {
    const aliasInput = byId("ukModelAliasInput");
    const targetSelect = byId("ukModelTargetSelect");
    if (aliasInput) aliasInput.value = "free-claude-universal";
    if (targetSelect) targetSelect.value = "auto";
    await handleSaveUniversalModel();
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
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:32px;">No Universal API Keys found. Generate one above to connect Claude Code, Cline, Cursor, or external tools.</td></tr>`;
      return;
    }

    const baseUrl = getApiBaseUrl();
    const alias = state.universalModel.alias || "free-claude-universal";

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
        : `<span style="color:var(--muted); font-size:0.8rem;">(Global default: ${escapeHtml(alias)})</span>`;

      return `
        <tr data-key-id="${k.id}">
          <td><strong>${escapeHtml(k.name)}</strong></td>
          <td><code>${escapeHtml(k.key_prefix)}</code></td>
          <td>${defModel}</td>
          <td>${k.total_requests || 0}</td>
          <td style="color:var(--muted); font-size:0.8rem;">${lastUsed}</td>
          <td>${statusBadge}</td>
          <td>
            <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
              <button class="secondary-button uk-copy-prefix-btn" style="padding:4px 8px; font-size:0.75rem;" data-prefix="${escapeHtml(k.key_prefix)}" title="Copy key prefix">
                Copy Prefix
              </button>
              <button class="secondary-button uk-toggle-btn" style="padding:4px 8px; font-size:0.75rem;" data-id="${k.id}">
                ${isAct ? "Revoke" : "Activate"}
              </button>
              <button class="btn-icon-danger uk-delete-btn" style="padding:4px 8px; font-size:0.75rem;" title="Delete key" data-id="${k.id}" data-name="${escapeHtml(k.name)}">
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

    tbody.querySelectorAll(".uk-copy-prefix-btn").forEach((btn) => {
      btn.addEventListener("click", () => copyToClipboard(btn.dataset.prefix, btn, "Copied!"));
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
      
      const keyRecord = res.key || res.record || {};
      const keyName = keyRecord.name || payload.name;
      showBanner(res.raw_key, keyName);
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
    copyToClipboard(state.rawKeyGenerated, byId("ukCopyBtn"), "Key Copied!");
  }

  function copyBaseUrl() {
    copyToClipboard(getApiBaseUrl(), byId("ukCopyBaseUrlBtn"), "URL Copied!");
  }

  function copyCurlSnippet() {
    const curlElem = byId("ukCurlSnippet");
    if (!curlElem) return;
    copyToClipboard(curlElem.textContent, byId("ukCopyCurlBtn"), "cURL Copied!");
  }

  function copyModelAlias() {
    const aliasInput = byId("ukModelAliasInput");
    if (!aliasInput) return;
    copyToClipboard(aliasInput.value.trim(), byId("ukCopyModelAliasBtn"), "Copied!");
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
    const copyBaseUrlBtn = byId("ukCopyBaseUrlBtn");
    if (copyBaseUrlBtn) {
      copyBaseUrlBtn.addEventListener("click", copyBaseUrl);
    }
    const copyCurlBtn = byId("ukCopyCurlBtn");
    if (copyCurlBtn) {
      copyCurlBtn.addEventListener("click", copyCurlSnippet);
    }
    const copyModelAliasBtn = byId("ukCopyModelAliasBtn");
    if (copyModelAliasBtn) {
      copyModelAliasBtn.addEventListener("click", copyModelAlias);
    }
    const saveModelBtn = byId("ukSaveModelBtn");
    if (saveModelBtn) {
      saveModelBtn.addEventListener("click", handleSaveUniversalModel);
    }
    const resetModelBtn = byId("ukResetModelBtn");
    if (resetModelBtn) {
      resetModelBtn.addEventListener("click", handleResetUniversalModel);
    }

    updateConnectionDetails();
  }

  window.UniversalKeysUI = {
    init,
    activate: () => {
      updateConnectionDetails();
      loadUniversalModel();
      loadKeys();
    },
    refresh: () => {
      loadUniversalModel();
      loadKeys();
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
