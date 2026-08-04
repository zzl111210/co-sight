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
      throw new Error(payload.detail || payload.message || "请求失败");
    }
    return payload;
  }

  function renderStatus(status) {
    const llm = status.llm || {};
    const tools = status.optional_tools || {};
    const security = status.security || {};
    const configuredTools = tools.tavily_configured ? 1 : 0;

    setText("auth-mode", security.auth_mode || "--");
    setText("auth-mode-detail", security.auth_mode || "--");
    setText("llm-readiness", llm.configured ? "已就绪" : "待配置");
    setText("tool-readiness", configuredTools + "/2 可选工具");
    setText("network-write", security.real_network_write_enabled ? "已启用" : "禁用");
    setText("model-name", llm.model_name || "未配置");
    setText("model-endpoint", llm.api_base_url || "未配置");
    setText("model-timeout", (llm.timeout_seconds || 60) + " 秒");
    setText("model-key-state", llm.api_key_present ? "已配置（内容隐藏）" : "未配置");
    setText("token-secret-state", security.token_secret_configured ? "已配置（内容隐藏）" : "开发模式临时密钥");
    setText("tavily-state", tools.tavily_configured ? "已配置" : "未配置");

    setBadge("llm-badge", llm.configured ? "已就绪" : "待配置", llm.configured ? "success" : "warning");
    setBadge(
      "auth-badge",
      security.auth_mode === "production" ? "生产模式" : "开发模式",
      security.auth_mode === "production" ? "success" : "warning"
    );
    setBadge("tools-badge", configuredTools + "/1 已配置", configuredTools ? "success" : "warning");
  }

  async function loadStatus(showToast = false) {
    try {
      const [health, status] = await Promise.all([api("/health"), api("/config/status")]);
      setText("service-state", health.status === "healthy" ? "系统在线" : "服务异常");
      renderStatus(status);
      if (showToast) notify("配置状态已刷新");
    } catch (error) {
      setText("service-state", "连接异常");
      notify(error.message);
    }
  }

  async function checkLlm() {
    const button = byId("check-llm");
    button.disabled = true;
    setText("connection-result", "正在检查模型提供商，请稍候……");
    try {
      const result = await api("/config/llm/check", { method: "POST" });
      if (result.ok) {
        setText(
          "connection-result",
          "连接成功 · HTTP " + result.status_code + " · " + result.latency_ms + " ms · " + result.model_name
        );
        setBadge("llm-badge", "连接正常", "success");
        notify("模型服务连接成功");
      } else {
        setText("connection-result", "连接未通过 · " + (result.reason || "提供商返回异常"));
        setBadge("llm-badge", "连接异常", "warning");
        notify("模型服务连接未通过");
      }
    } catch (error) {
      setText("connection-result", "检查失败 · " + error.message);
      setBadge("llm-badge", "检查失败", "warning");
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
