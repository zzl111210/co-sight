(() => {
  "use strict";

  const API = "/api/netheal/v1";
  const byId = (id) => document.getElementById(id);
  let toastTimer;

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value;
  }

  function setBadge(id, label, state) {
    const element = byId(id);
    if (!element) return;
    element.textContent = label;
    element.className = "status-badge" + (state ? " " + state : "");
  }

  function notify(message) {
    const toast = byId("settings-toast");
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2800);
  }

  async function api(path, options = {}) {
    const response = await fetch(API + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-NetHeal-Actor": "settings-console",
        "X-NetHeal-Role": "operator",
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || payload.message || "????");
    }
    return payload;
  }

  function renderStatus(status) {
    const llm = status.llm || {};
    const tools = status.optional_tools || {};
    const security = status.security || {};
    const configuredTools = [tools.tavily_configured, tools.google_search_configured]
      .filter(Boolean).length;

    setText("auth-mode", security.auth_mode || "--");
    setText("auth-mode-detail", security.auth_mode || "--");
    setText("llm-readiness", llm.configured ? "???" : "???");
    setText("tool-readiness", configuredTools + "/2 ????");
    setText("network-write", security.real_network_write_enabled ? "???" : "??");
    setText("model-name", llm.model_name || "???");
    setText("model-endpoint", llm.api_base_url || "???");
    setText("model-timeout", (llm.timeout_seconds || 60) + " ?");
    setText("model-key-state", llm.api_key_present ? "?????????" : "???");
    setText("token-secret-state", security.token_secret_configured ? "?????????" : "????????");
    setText("tavily-state", tools.tavily_configured ? "???" : "???");
    setText("google-state", tools.google_search_configured ? "???" : "???");

    setBadge("llm-badge", llm.configured ? "???" : "???", llm.configured ? "success" : "warning");
    setBadge(
      "auth-badge",
      security.auth_mode === "production" ? "????" : "????",
      security.auth_mode === "production" ? "success" : "warning"
    );
    setBadge("tools-badge", configuredTools + "/2 ???", configuredTools ? "success" : "warning");
  }

  async function loadStatus(showToast = false) {
    try {
      const [health, status] = await Promise.all([api("/health"), api("/config/status")]);
      setText("service-state", health.status === "healthy" ? "????" : "????");
      renderStatus(status);
      if (showToast) notify("???????");
    } catch (error) {
      setText("service-state", "????");
      notify(error.message);
    }
  }

  async function checkLlm() {
    const button = byId("check-llm");
    button.disabled = true;
    setText("connection-result", "???????????????");
    try {
      const result = await api("/config/llm/check", { method: "POST" });
      if (result.ok) {
        setText(
          "connection-result",
          "???? ? HTTP " + result.status_code + " ? " + result.latency_ms + " ms ? " + result.model_name
        );
        setBadge("llm-badge", "????", "success");
        notify("????????");
      } else {
        setText("connection-result", "????? ? " + (result.reason || "???????"));
        setBadge("llm-badge", "????", "warning");
        notify("?????????");
      }
    } catch (error) {
      setText("connection-result", "???? ? " + error.message);
      setBadge("llm-badge", "????", "warning");
      notify(error.message);
    } finally {
      button.disabled = false;
    }
  }

  function updateClock() {
    setText(
      "system-clock",
      new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(new Date())
    );
  }

  byId("refresh-status").addEventListener("click", () => loadStatus(true));
  byId("check-llm").addEventListener("click", checkLlm);
  updateClock();
  window.setInterval(updateClock, 1000);
  loadStatus();
})();
