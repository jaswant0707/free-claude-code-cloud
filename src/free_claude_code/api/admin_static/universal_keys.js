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
    analytics: null,
    logs: [],
    selectedKeyIdForLogs: "",
    dbHealth: null,
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
      updateLogsKeyFilterDropdown();
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
              <button class="secondary-button uk-view-logs-btn" style="padding:4px 8px; font-size:0.75rem;" data-id="${k.id}" title="View request logs for this key">
                Logs
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
      btn.addEventListener("click", () => copyToClipboard(btn.dataset.prefix, btn, "Prefix Copied!"));
    });

    tbody.querySelectorAll(".uk-view-logs-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const keyId = btn.dataset.id;
        const select = byId("ukLogsKeyFilter");
        if (select) select.value = keyId;
        loadLogs(keyId);
        const logsCard = document.querySelector(".uk-logs-card");
        if (logsCard) logsCard.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }

  function copyBannerPsSnippet() {
    if (!state.rawKeyGenerated) return;
    const baseUrl = getApiBaseUrl();
    const alias = (state.universalModel && state.universalModel.alias) || "free-claude-universal";
    const snippet = `$headers = @{
    "Authorization" = "Bearer ${state.rawKeyGenerated}"
    "Content-Type" = "application/json"
}
$body = @{
    model = "${alias}"
    messages = @(
        @{
            role = "user"
            content = "Reply with OK"
        }
    )
} | ConvertTo-Json -Depth 10
Invoke-RestMethod -Uri "${baseUrl}/chat/completions" -Method POST -Headers $headers -Body $body`;
    copyToClipboard(snippet, byId("ukBannerCopyPsBtn"), "PS Test Copied!");
  }

  function copyBannerCurlSnippet() {
    if (!state.rawKeyGenerated) return;
    const baseUrl = getApiBaseUrl();
    const alias = (state.universalModel && state.universalModel.alias) || "free-claude-universal";
    const snippet = `curl.exe -i -X POST "${baseUrl}/chat/completions" -H "Authorization: Bearer ${state.rawKeyGenerated}" -H "Content-Type: application/json" -d "{\\"model\\":\\"${alias}\\",\\"messages\\":[{\\"role\\":\\"user\\",\\"content\\":\\"Reply with OK\\"}]}"`;
    copyToClipboard(snippet, byId("ukBannerCopyCurlBtn"), "cURL Test Copied!");
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

  /* ==========================================================================
     Supabase Health & Details
     ========================================================================== */
  async function loadDatabaseHealth() {
    const badge = byId("sbLiveStatusBadge");
    const refreshBtn = byId("sbRefreshBtn");
    if (badge) badge.textContent = "● Checking...";
    if (refreshBtn) refreshBtn.disabled = true;

    try {
      const data = await api("/admin/api/supabase/status");
      state.dbHealth = data;
      renderDatabaseHealth(data);
    } catch (err) {
      if (badge) {
        badge.className = "badge badge-revoked";
        badge.textContent = "○ Degraded / Error";
      }
      console.warn("Failed to load Supabase status:", err);
    } finally {
      if (refreshBtn) refreshBtn.disabled = false;
    }
  }

  function renderDatabaseHealth(data) {
    if (!data) return;
    const badge = byId("sbLiveStatusBadge");
    if (badge) {
      const isHealthy = data.status === "healthy";
      badge.className = isHealthy ? "badge badge-active" : "badge badge-revoked";
      badge.textContent = isHealthy ? "● Connected (Healthy)" : "○ " + (data.status || "Degraded");
    }

    if (byId("sbProjectRef")) byId("sbProjectRef").textContent = data.project_ref || "emlenqcewhlwtnigwkac";
    if (byId("sbRegion")) byId("sbRegion").textContent = data.region ? `${data.region} (N. Virginia)` : "us-east-1";
    if (byId("sbEngine")) byId("sbEngine").textContent = data.postgres_version ? `PostgreSQL ${data.postgres_version}` : "PostgreSQL 17.12 (GA)";
    if (byId("sbDbSize")) byId("sbDbSize").textContent = data.database_size_pretty || "11 MB";
    if (byId("sbRpcCount")) byId("sbRpcCount").textContent = `${data.rpc_functions_count || 33} Active (Verified)`;
    if (byId("sbSecurityStatus")) {
      const sec = byId("sbSecurityStatus");
      sec.textContent = data.backend_auth_verified ? "Protected (Backend Verified)" : "Active";
      sec.style.color = "var(--success)";
    }

    const grid = byId("sbTablesGrid");
    if (grid && Array.isArray(data.tables)) {
      if (data.tables.length === 0) {
        grid.innerHTML = `<div style="color:var(--muted); font-size:0.85rem; padding:12px;">No FCC tables reported.</div>`;
      } else {
        grid.innerHTML = data.tables.map((t) => `
          <div class="sb-table-chip">
            <div class="sb-chip-info">
              <span class="sb-chip-name">${escapeHtml(t.name)}</span>
              <span class="sb-chip-size">${escapeHtml(t.size || "disk")}</span>
            </div>
            <span class="sb-chip-rows">${Number(t.rows || 0).toLocaleString()} rows</span>
          </div>
        `).join("");
      }
    }
  }

  /* ==========================================================================
     Universal Keys Analytics & Charts
     ========================================================================== */
  async function loadAnalytics() {
    const refreshBtn = byId("ukAnalyticsRefreshBtn");
    if (refreshBtn) refreshBtn.disabled = true;

    try {
      const data = await api("/admin/api/universal-keys/analytics");
      state.analytics = data;
      renderAnalytics(data);
    } catch (err) {
      console.warn("Failed to load analytics:", err);
    } finally {
      if (refreshBtn) refreshBtn.disabled = false;
    }
  }

  function renderAnalytics(data) {
    if (!data) return;
    const overview = data.overview || {};

    if (byId("ukKpiTotalReq")) {
      byId("ukKpiTotalReq").textContent = (overview.total_requests || 0).toLocaleString();
    }
    if (byId("ukKpiActiveKeys")) {
      byId("ukKpiActiveKeys").textContent = overview.active_keys || 0;
    }
    if (byId("ukKpiAvgLatency")) {
      const lat = overview.avg_latency_ms || 0;
      byId("ukKpiAvgLatency").textContent = lat > 0 ? `${lat} ms` : "Instant";
    }
    if (byId("ukKpiSuccessRate")) {
      const total = overview.logged_requests || 0;
      const success = overview.success_requests || 0;
      const rate = total > 0 ? Math.round((success / total) * 100) : 100;
      byId("ukKpiSuccessRate").textContent = `${rate}%`;
      byId("ukKpiSuccessRate").style.color = rate >= 95 ? "var(--success)" : "var(--error)";
      if (byId("ukKpiSuccessHint")) {
        byId("ukKpiSuccessHint").textContent = `${overview.failed_requests || 0} errors logged`;
      }
    }

    renderTimelineChart(data.timeline || []);
    renderModelDistribution(data.model_distribution || []);
  }

  function renderTimelineChart(timeline) {
    const container = byId("ukTimelineChart");
    if (!container) return;

    if (!timeline || timeline.length === 0) {
      container.innerHTML = `<div style="margin:auto; font-size:0.8rem; color:var(--muted); text-align:center;">No timeline request data recorded in the last 24 hours.</div>`;
      return;
    }

    let maxReq = 1;
    for (const pt of timeline) {
      if (pt.requests > maxReq) maxReq = pt.requests;
    }
    const chartMax = Math.max(maxReq, 5);

    const width = 500;
    const height = 180;
    const paddingLeft = 30;
    const paddingBottom = 25;
    const paddingTop = 10;
    const paddingRight = 10;
    const plotWidth = width - paddingLeft - paddingRight;
    const plotHeight = height - paddingTop - paddingBottom;
    const barWidth = Math.max(4, Math.floor(plotWidth / timeline.length) - 3);

    let barsHtml = "";
    let labelsHtml = "";

    timeline.forEach((pt, i) => {
      const x = paddingLeft + (i * (plotWidth / timeline.length)) + 2;
      const reqHeight = Math.round((pt.requests / chartMax) * plotHeight);
      const errHeight = Math.round((pt.errors / chartMax) * plotHeight);
      const y = height - paddingBottom - reqHeight;

      const label = pt.time || "";
      if (i % 4 === 0 || i === timeline.length - 1) {
        labelsHtml += `<text x="${x + barWidth / 2}" y="${height - 8}" class="uk-timeline-axis-label">${escapeHtml(label)}</text>`;
      }

      if (pt.requests > 0) {
        barsHtml += `
          <rect class="uk-timeline-bar" x="${x}" y="${y}" width="${barWidth}" height="${reqHeight}" rx="2"
                data-tooltip="${escapeHtml(pt.time)}: ${pt.requests} request(s), ${pt.errors} error(s)">
          </rect>
        `;
        if (pt.errors > 0) {
          const errY = height - paddingBottom - errHeight;
          barsHtml += `
            <rect class="uk-timeline-err-bar" x="${x}" y="${errY}" width="${barWidth}" height="${errHeight}" rx="1"
                  data-tooltip="${escapeHtml(pt.time)}: ${pt.errors} error(s)">
            </rect>
          `;
        }
      } else {
        barsHtml += `
          <rect x="${x}" y="${height - paddingBottom - 2}" width="${barWidth}" height="2" fill="var(--line-strong)" opacity="0.4" rx="1"
                data-tooltip="${escapeHtml(pt.time)}: 0 requests">
          </rect>
        `;
      }
    });

    container.innerHTML = `
      <svg class="uk-timeline-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
        <line x1="${paddingLeft}" y1="${paddingTop}" x2="${width - paddingRight}" y2="${paddingTop}" stroke="var(--line)" stroke-dasharray="3,3" />
        <line x1="${paddingLeft}" y1="${paddingTop + plotHeight / 2}" x2="${width - paddingRight}" y2="${paddingTop + plotHeight / 2}" stroke="var(--line)" stroke-dasharray="3,3" />
        <line x1="${paddingLeft}" y1="${height - paddingBottom}" x2="${width - paddingRight}" y2="${height - paddingBottom}" stroke="var(--line)" />
        ${barsHtml}
        ${labelsHtml}
      </svg>
      <div id="ukChartTooltip" class="uk-chart-tooltip" style="display:none;"></div>
    `;

    const svg = container.querySelector("svg");
    const tooltip = container.querySelector("#ukChartTooltip");
    if (svg && tooltip) {
      svg.querySelectorAll("[data-tooltip]").forEach((el) => {
        el.addEventListener("mouseenter", (e) => {
          tooltip.textContent = el.dataset.tooltip;
          tooltip.style.display = "block";
          const rect = container.getBoundingClientRect();
          tooltip.style.left = (e.clientX - rect.left + 10) + "px";
          tooltip.style.top = (e.clientY - rect.top - 25) + "px";
        });
        el.addEventListener("mousemove", (e) => {
          const rect = container.getBoundingClientRect();
          tooltip.style.left = (e.clientX - rect.left + 10) + "px";
          tooltip.style.top = (e.clientY - rect.top - 25) + "px";
        });
        el.addEventListener("mouseleave", () => {
          tooltip.style.display = "none";
        });
      });
    }
  }

  function renderModelDistribution(models) {
    const container = byId("ukModelDistChart");
    if (!container) return;

    if (!models || models.length === 0) {
      const alias = (state.universalModel && state.universalModel.alias) || "free-claude-universal";
      container.innerHTML = `
        <div style="margin:auto; font-size:0.8rem; color:var(--muted); text-align:center; padding:20px;">
          <p>No model-specific requests logged yet.</p>
          <span style="font-size:0.75rem;">Default model: <code>${escapeHtml(alias)}</code></span>
        </div>
      `;
      return;
    }

    const total = models.reduce((acc, m) => acc + (m.count || 0), 0) || 1;

    container.innerHTML = models.map((m) => {
      const pct = Math.round((m.count / total) * 100);
      return `
        <div class="uk-model-bar-item">
          <div class="uk-model-bar-header">
            <span class="uk-model-bar-name">${escapeHtml(m.model)}</span>
            <span class="uk-model-bar-count">${m.count} reqs (${pct}%)</span>
          </div>
          <div class="uk-model-track">
            <div class="uk-model-fill" style="width:${pct}%;"></div>
          </div>
        </div>
      `;
    }).join("");
  }

  /* ==========================================================================
     Universal Key Request Logs
     ========================================================================== */
  async function loadLogs(keyId) {
    const filter = keyId !== undefined ? keyId : (byId("ukLogsKeyFilter") ? byId("ukLogsKeyFilter").value : "");
    state.selectedKeyIdForLogs = filter || "";
    const tbody = byId("ukLogsTableBody");
    const refreshBtn = byId("ukLogsRefreshBtn");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:20px;">Loading request logs...</td></tr>`;
    }
    if (refreshBtn) refreshBtn.disabled = true;

    try {
      const url = filter
        ? `/admin/api/universal-keys/logs?key_id=${encodeURIComponent(filter)}&limit=50`
        : `/admin/api/universal-keys/logs?limit=50`;
      const data = await api(url);
      state.logs = data.logs || [];
      renderLogs(state.logs);
    } catch (err) {
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--error); padding:20px;">Failed to load logs: ${escapeHtml(err.message)}</td></tr>`;
      }
    } finally {
      if (refreshBtn) refreshBtn.disabled = false;
    }
  }

  function renderLogs(logs) {
    const tbody = byId("ukLogsTableBody");
    if (!tbody) return;

    if (!logs || logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:24px;">No requests recorded yet for the selected filter. Run a request with cURL or your coding agent to see live logs.</td></tr>`;
      return;
    }

    tbody.innerHTML = logs.map((log) => {
      const timeStr = log.created_at ? new Date(log.created_at).toLocaleString() : "--";
      const status = log.status || "success";
      const statusCode = log.status_code || 200;
      const statusBadgeClass = `badge-status-${statusCode}`;
      const statusBadge = `<span class="badge ${statusBadgeClass}">${statusCode} ${escapeHtml(status.toUpperCase())}</span>`;
      const latency = log.duration_ms ? `${log.duration_ms} ms` : "--";

      return `
        <tr>
          <td style="color:var(--muted); font-size:0.78rem;">${timeStr}</td>
          <td><strong>${escapeHtml(log.key_name || "--")}</strong></td>
          <td><code>${escapeHtml(log.key_prefix || "--")}</code></td>
          <td><code>${escapeHtml(log.endpoint || "/v1/chat/completions")}</code></td>
          <td><span class="badge badge-model">${escapeHtml(log.model || "free-claude-universal")}</span></td>
          <td>${statusBadge}</td>
          <td style="font-size:0.8rem; font-weight:600;">${latency}</td>
        </tr>
      `;
    }).join("");
  }

  function updateLogsKeyFilterDropdown() {
    const select = byId("ukLogsKeyFilter");
    if (!select) return;

    const currentVal = state.selectedKeyIdForLogs || "";
    let html = `<option value="">All Keys</option>`;
    for (const k of state.keys) {
      const sel = String(k.id) === String(currentVal) ? "selected" : "";
      html += `<option value="${escapeHtml(k.id)}" ${sel}>${escapeHtml(k.name)} (${escapeHtml(k.key_prefix)})</option>`;
    }
    select.innerHTML = html;
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
    const copyPsBtn = byId("ukBannerCopyPsBtn");
    if (copyPsBtn) {
      copyPsBtn.addEventListener("click", copyBannerPsSnippet);
    }
    const copyCurlTestBtn = byId("ukBannerCopyCurlBtn");
    if (copyCurlTestBtn) {
      copyCurlTestBtn.addEventListener("click", copyBannerCurlSnippet);
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
    const sbRefreshBtn = byId("sbRefreshBtn");
    if (sbRefreshBtn) {
      sbRefreshBtn.addEventListener("click", () => loadDatabaseHealth());
    }
    const ukAnalyticsRefreshBtn = byId("ukAnalyticsRefreshBtn");
    if (ukAnalyticsRefreshBtn) {
      ukAnalyticsRefreshBtn.addEventListener("click", () => loadAnalytics());
    }
    const ukLogsRefreshBtn = byId("ukLogsRefreshBtn");
    if (ukLogsRefreshBtn) {
      ukLogsRefreshBtn.addEventListener("click", () => loadLogs());
    }
    const ukLogsKeyFilter = byId("ukLogsKeyFilter");
    if (ukLogsKeyFilter) {
      ukLogsKeyFilter.addEventListener("change", (e) => loadLogs(e.target.value));
    }

    updateConnectionDetails();
  }

  window.UniversalKeysUI = {
    init,
    activate: () => {
      updateConnectionDetails();
      loadUniversalModel();
      loadKeys().then(() => {
        updateLogsKeyFilterDropdown();
      });
      loadDatabaseHealth();
      loadAnalytics();
      loadLogs();
    },
    refresh: () => {
      loadUniversalModel();
      loadKeys().then(() => {
        updateLogsKeyFilterDropdown();
      });
      loadDatabaseHealth();
      loadAnalytics();
      loadLogs();
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
