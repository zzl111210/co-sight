(() => {
  "use strict";

  const API_BASE = "/api/netheal/v1";
  const state = {
    overview: {},
    incidents: [],
    selectedId: null,
    selected: null,
    topology: { nodes: [], links: [] },
    workflow: [],
    audit: [],
    scenarios: [],
    filter: "all",
    busy: false,
  };

  const els = {};
  const byId = (id) => document.getElementById(id);
  const pick = (obj, keys, fallback = undefined) => {
    for (const key of keys) {
      if (obj && obj[key] !== undefined && obj[key] !== null) return obj[key];
    }
    return fallback;
  };
  const asArray = (value) => Array.isArray(value) ? value : [];
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const statusMeta = {
    detected: ["已发现", "danger"],
    diagnosing: ["诊断中", "active"],
    approval_pending: ["待审批", "warning"],
    approved: ["已审批", "active"],
    executing: ["执行中", "active"],
    verifying: ["验证中", "active"],
    closed: ["已闭环", "success"],
    needs_review: ["需复核", "danger"],
  };
  const severityNames = {
    critical: "严重",
    major: "重要",
    minor: "次要",
    warning: "警告",
    info: "提示",
  };

  function initElements() {
    [
      "system-clock", "role-selector", "scenario-selector", "run-demo", "reset-demo", "metric-health",
      "metric-active", "metric-critical", "metric-confidence", "metric-compression",
      "metric-closure", "health-progress", "health-caption", "incident-count",
      "incident-list", "topology-svg", "topology-empty", "detail-status",
      "incident-hero", "detail-content", "detail-id", "detail-site", "detail-time",
      "detail-title", "detail-summary", "detail-confidence", "detail-root-cause",
      "detail-impact", "evidence-count", "evidence-grid", "repair-list",
      "action-diagnose", "action-approve", "action-execute", "action-verify",
      "action-download-report",
      "workflow-rail", "validation-badge", "kpi-comparison", "audit-list",
      "incident-timeline", "refresh-audit", "toast-stack", "operation-overlay", "operation-title",
      "operation-message", "operation-progress-bar",
      "kpi-timeseries-svg", "kpi-timeseries-empty", "kpi-timeseries-view", "kpi-comparison-view",
    ].forEach((id) => { els[id] = byId(id); });
  }

  async function api(path, options = {}) {
    const role = els["role-selector"]?.value || "operator";
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-NetHeal-Actor": `dashboard-${role}`,
        "X-NetHeal-Role": role,
        ...(options.headers || {}),
      },
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = { detail: `服务返回了无法解析的响应（HTTP ${response.status}）` };
    }
    if (!response.ok) {
      const message = pick(payload, ["detail", "message", "error"], `请求失败（HTTP ${response.status}）`);
      throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    return payload;
  }

  function unwrap(payload, key) {
    if (payload === null || payload === undefined) return payload;
    if (key && payload[key] !== undefined) return payload[key];
    if (payload.data !== undefined) {
      if (key && payload.data?.[key] !== undefined) return payload.data[key];
      return payload.data;
    }
    return payload;
  }

  function normalizeIncident(raw) {
    const diagnosis = pick(raw, ["diagnosis", "root_cause_analysis"], {}) || {};
    const rootCauseCode = pick(raw, ["root_cause"], pick(diagnosis, ["root_cause", "cause"], ""));
    const rootCauseNames = {
      UPF_OVERLOAD: "UPF 节点过载",
      BACKHAUL_LINK_DOWN: "基站回传链路中断",
      SLICE_CAPACITY_SHORTAGE: "网络切片资源配置不足",
    };
    const repairRoot = pick(raw, ["repair", "repair_plan"], {}) || {};
    const verification = pick(
      raw,
      ["verification", "verification_result"],
      pick(repairRoot, ["verification"], {}),
    ) || {};
    const repair = Array.isArray(repairRoot)
      ? repairRoot
      : pick(repairRoot, ["actions"], pick(repairRoot.plan, ["actions"], []));
    return {
      ...raw,
      id: String(pick(raw, ["id", "incident_id"], "")),
      siteId: pick(raw, ["site_id", "site"], "campus-5g"),
      scenarioId: pick(raw, ["scenario_id", "scenario"], ""),
      title: pick(raw, ["title", "name"], "未命名网络事件"),
      summary: pick(raw, ["summary", "description"], ""),
      severity: String(pick(raw, ["severity", "level"], "major")).toLowerCase(),
      status: String(pick(raw, ["status", "state"], "detected")).toLowerCase(),
      detectedAt: pick(raw, ["detected_at", "created_at", "timestamp"], ""),
      updatedAt: pick(raw, ["updated_at", "modified_at"], ""),
      rootCauseCode,
      rootCause: rootCauseNames[rootCauseCode] || rootCauseCode,
      rootResource: pick(raw, ["root_resource", "resource_id"], ""),
      confidence: Number(pick(raw, ["confidence"], pick(diagnosis, ["confidence", "score"], 0))) || 0,
      impact: pick(raw, ["impact_scope", "impact"], pick(diagnosis, ["impact_scope", "impact"], pick(raw, ["affected_service"], ""))),
      evidence: pick(raw, ["evidence", "evidence_chain"], pick(diagnosis, ["evidence"], {})) || {},
      repairPlan: Array.isArray(repair) ? repair : asArray(pick(repair, ["actions", "steps"], [])),
      verification,
      verificationPassed: Boolean(pick(raw, ["verification_passed"], pick(verification, ["passed", "success"], false))),
    };
  }

  function statusInfo(status) {
    return statusMeta[status] || [status || "未知", "muted"];
  }

  function formatTime(value, includeDate = false) {
    if (!value) return "--";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return parsed.toLocaleString("zh-CN", {
      month: includeDate ? "2-digit" : undefined,
      day: includeDate ? "2-digit" : undefined,
      hour: "2-digit",
      minute: "2-digit",
      second: includeDate ? "2-digit" : undefined,
      hour12: false,
    });
  }

  function percentage(value, fallback = 0) {
    let result = Number(value);
    if (!Number.isFinite(result)) result = fallback;
    if (result > 0 && result <= 1) result *= 100;
    return Math.max(0, Math.min(100, result));
  }

  function renderOverview() {
    const overview = state.overview || {};
    const activeFallback = state.incidents.filter((item) => item.status !== "closed").length;
    const criticalFallback = state.incidents.filter(
      (item) => item.status !== "closed" && item.severity === "critical",
    ).length;
    const confidenceValues = state.incidents.filter((item) => item.confidence > 0).map((item) => item.confidence);
    const confidenceFallback = confidenceValues.length
      ? confidenceValues.reduce((sum, item) => sum + percentage(item), 0) / confidenceValues.length
      : 0;
    const closedCount = state.incidents.filter((item) => item.status === "closed").length;
    const closureFallback = state.incidents.length ? (closedCount / state.incidents.length) * 100 : 100;

    const health = Math.round(percentage(pick(overview, ["network_health_score", "network_health", "health_score", "health"], 88), 88));
    const active = Number(pick(overview, ["active_incidents", "active_count"], activeFallback));
    const critical = Number(pick(overview, ["critical_incidents", "critical_count"], criticalFallback));
    const confidence = Math.round(percentage(
      pick(overview, ["mean_confidence_pct", "ai_confidence", "average_confidence"], confidenceFallback),
      confidenceFallback,
    ));
    const compression = Math.round(percentage(
      pick(overview, ["alarm_compression_rate", "compression_rate"], 77.78),
      77.78,
    ));
    const closure = Math.round(percentage(
      pick(overview, ["auto_closure_rate_pct", "closure_rate", "closed_loop_rate"], closureFallback),
      closureFallback,
    ));

    els["metric-health"].textContent = health;
    els["metric-active"].textContent = active;
    els["metric-critical"].textContent = critical;
    els["metric-confidence"].textContent = confidence;
    els["metric-compression"].textContent = compression;
    els["metric-closure"].textContent = closure;
    els["health-progress"].style.width = `${health}%`;
    els["health-caption"].textContent = health >= 90
      ? "网络整体运行稳健"
      : health >= 75
        ? "存在局部性能退化"
        : "需要立即介入处置";
  }

  function filteredIncidents() {
    if (state.filter === "active") return state.incidents.filter((item) => item.status !== "closed");
    if (state.filter === "closed") return state.incidents.filter((item) => item.status === "closed");
    return state.incidents;
  }

  function renderIncidents() {
    const items = filteredIncidents();
    els["incident-count"].textContent = state.incidents.length;
    if (!items.length) {
      els["incident-list"].innerHTML = `
        <div class="empty-state compact">
          <i class="fa-solid fa-inbox"></i><p>当前筛选条件下没有事件。</p>
        </div>`;
      return;
    }
    els["incident-list"].innerHTML = items.map((incident) => {
      const [statusName, statusClass] = statusInfo(incident.status);
      return `
        <button class="incident-item severity-${escapeHtml(incident.severity)} ${incident.id === state.selectedId ? "selected" : ""}"
                data-incident-id="${escapeHtml(incident.id)}">
          <div class="incident-topline">
            <span>${escapeHtml(incident.id)}</span>
            <span>${escapeHtml(formatTime(incident.detectedAt))}</span>
          </div>
          <h3>${escapeHtml(incident.title)}</h3>
          <div class="incident-bottomline">
            <span>${escapeHtml(severityNames[incident.severity] || incident.severity)}</span>
            <span class="mini-status ${statusClass}">${escapeHtml(statusName)}</span>
          </div>
        </button>`;
    }).join("");

    els["incident-list"].querySelectorAll("[data-incident-id]").forEach((button) => {
      button.addEventListener("click", () => selectIncident(button.dataset.incidentId));
    });
  }

  function evidenceEntries(evidence) {
    const iconMap = {
      alarms: "fa-bell",
      alarm: "fa-bell",
      kpi: "fa-chart-line",
      metrics: "fa-chart-line",
      topology: "fa-network-wired",
      knowledge: "fa-book-medical",
      historical_case: "fa-clock-rotate-left",
      logs: "fa-file-waveform",
    };
    const labelMap = {
      alarms: "告警关联",
      alarm: "告警关联",
      kpi: "KPI 异常",
      metrics: "KPI 异常",
      topology: "拓扑路径",
      knowledge: "专家知识",
      historical_case: "历史案例",
      logs: "设备日志",
    };
    if (Array.isArray(evidence)) {
      return evidence.map((item, index) => ({
        key: String(pick(item, ["type", "source"], `evidence_${index}`)),
        label: pick(item, ["label", "source", "type"], `证据 ${index + 1}`),
        value: pick(item, ["summary", "value", "content"], JSON.stringify(item)),
      }));
    }
    if (!evidence || typeof evidence !== "object") return [];
    return Object.entries(evidence).map(([key, value]) => ({
      key,
      label: labelMap[key] || key.replaceAll("_", " "),
      icon: iconMap[key] || "fa-circle-nodes",
      value: summarizeValue(value),
    }));
  }

  function summarizeValue(value) {
    if (value === null || value === undefined || value === "") return "暂无有效数据";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (Array.isArray(value)) {
      if (!value.length) return "0 条记录";
      const first = value[0];
      if (typeof first === "string") return `${value.length} 条 · ${first}`;
      return `${value.length} 条记录`;
    }
    return pick(value, ["summary", "name", "root_cause", "value", "status"], `${Object.keys(value).length} 个字段`);
  }

  function repairItems(plan) {
    return asArray(plan).map((item, index) => {
      if (typeof item === "string") return { action: item, risk: index === 0 ? "中风险" : "低风险" };
      return {
        action: pick(item, ["action", "step", "description", "name", "command"], `处置动作 ${index + 1}`),
        risk: pick(item, ["risk", "risk_level"], index === 0 ? "中风险" : "低风险"),
      };
    });
  }

  function renderSelected() {
    const incident = state.selected;
    if (!incident) {
      els["incident-hero"].classList.remove("hidden");
      els["detail-content"].classList.add("hidden");
      els["detail-status"].textContent = "未选择";
      els["detail-status"].className = "status-pill muted";
      return;
    }

    els["incident-hero"].classList.add("hidden");
    els["detail-content"].classList.remove("hidden");
    const [statusName, statusClass] = statusInfo(incident.status);
    els["detail-status"].textContent = statusName;
    els["detail-status"].className = `status-pill ${statusClass}`;
    els["detail-id"].textContent = incident.id;
    els["detail-site"].textContent = incident.siteId;
    els["detail-time"].textContent = formatTime(incident.detectedAt, true);
    els["detail-title"].textContent = incident.title;
    els["detail-summary"].textContent = incident.summary || "该事件由 NetHeal 告警关联引擎自动创建。";
    els["detail-confidence"].textContent = `${Math.round(percentage(incident.confidence))}%`;
    els["detail-root-cause"].textContent = incident.rootCause || "等待多智能体完成证据融合";
    els["detail-impact"].textContent = incident.impact || "尚未完成业务影响面分析。";

    const entries = evidenceEntries(incident.evidence);
    els["evidence-count"].textContent = `${entries.length} 项`;
    els["evidence-grid"].innerHTML = entries.length
      ? entries.map((entry) => `
          <article class="evidence-card">
            <header><i class="fa-solid ${escapeHtml(entry.icon || "fa-circle-nodes")}"></i>${escapeHtml(entry.label)}</header>
            <strong title="${escapeHtml(entry.value)}">${escapeHtml(entry.value)}</strong>
          </article>`).join("")
      : `<div class="empty-state compact"><p>启动诊断后生成告警、KPI、拓扑和知识库证据。</p></div>`;

    const repairs = repairItems(incident.repairPlan);
    els["repair-list"].innerHTML = repairs.length
      ? repairs.map((item) => `
          <li><span>${escapeHtml(item.action)}</span><em class="risk-tag">${escapeHtml(item.risk)}</em></li>`).join("")
      : `<li><span>等待根因定位完成后生成分级处置方案</span><em class="risk-tag">待评估</em></li>`;

    updateActionAvailability(incident.status);
    renderTimeline();
    renderWorkflow();
    renderKpis();
    renderCandidateComparison(incident);
  }

  function renderTimeline() {
    const events = asArray(state.selected?.events);
    if (!events.length) {
      els["incident-timeline"].innerHTML = `
        <div class="empty-state compact"><p>事件推进后将在此记录智能体与人工操作。</p></div>`;
      return;
    }
    const eventNames = {
      incident_seeded: "事件进入智能事件中心",
      incident_detected: "监控告警触发事件",
      status_changed: "生命周期状态变更",
      diagnosis_completed: "多智能体根因诊断完成",
      repair_executed: "仿真修复事务执行完成",
    };
    const eventIcons = {
      incident_seeded: "fa-database",
      incident_detected: "fa-bell",
      status_changed: "fa-arrow-right-arrow-left",
      diagnosis_completed: "fa-brain",
      repair_executed: "fa-terminal",
    };
    els["incident-timeline"].innerHTML = events.slice().reverse().map((event) => {
      const type = String(pick(event, ["event_type", "type"], "event"));
      return `
        <div class="timeline-item">
          <span class="timeline-marker"><i class="fa-solid ${eventIcons[type] || "fa-circle"}"></i></span>
          <div>
            <strong>${escapeHtml(eventNames[type] || type)}</strong>
            <p>${escapeHtml(pick(event, ["message", "detail"], "状态已更新"))} · ${escapeHtml(pick(event, ["actor"], "system"))}</p>
          </div>
          <time>${escapeHtml(formatTime(pick(event, ["created_at", "timestamp"], "")))}</time>
        </div>`;
    }).join("");
  }

  function updateActionAvailability(status) {
    const role = els["role-selector"].value;
    const permission = {
      viewer: [],
      operator: ["diagnose", "execute", "verify"],
      approver: ["diagnose", "approve", "execute", "verify"],
      admin: ["diagnose", "approve", "execute", "verify"],
    }[role] || [];
    const stateAllowed = {
      diagnose: ["detected", "needs_review"],
      approve: ["approval_pending"],
      execute: ["approved"],
      verify: ["executing", "verifying"],
    };
    [
      ["action-diagnose", "diagnose"],
      ["action-approve", "approve"],
      ["action-execute", "execute"],
      ["action-verify", "verify"],
    ].forEach(([id, action]) => {
      els[id].disabled = state.busy || !permission.includes(action) || !stateAllowed[action].includes(status);
    });

    // 报告下载按钮：仅在 closed 或 needs_review（即有完整报告时）启用
    const hasReport = state.selected?.repair?.report || state.selected?.verificationPassed !== undefined;
    els["action-download-report"].disabled = state.busy || !(status === "closed" || status === "needs_review" || hasReport);
  }

  function workflowDefaults() {
    return [
      { id: "alarm", name: "告警解析智能体", description: "压缩与清洗", icon: "fa-bell" },
      { id: "topology", name: "拓扑关联智能体", description: "影响路径分析", icon: "fa-share-nodes" },
      { id: "diagnosis", name: "根因定位智能体", description: "多源证据融合", icon: "fa-brain" },
      { id: "repair", name: "修复决策智能体", description: "风险分级决策", icon: "fa-screwdriver-wrench" },
      { id: "verify", name: "验证评估智能体", description: "KPI 闭环验证", icon: "fa-shield-check" },
    ];
  }

  function workflowProgress(status) {
    const completed = {
      detected: 0,
      diagnosing: 1,
      approval_pending: 3,
      approved: 3,
      executing: 4,
      verifying: 4,
      closed: 5,
      needs_review: 4,
    }[status] ?? 0;
    return { completed, running: status === "closed" ? -1 : Math.min(completed, 4) };
  }

  function renderWorkflow() {
    const defaults = workflowDefaults();
    const supplied = asArray(state.workflow);
    const nodes = defaults.map((item, index) => {
      const candidate = supplied[index] || supplied.find((step) => {
        const id = String(pick(step, ["id", "agent", "name"], "")).toLowerCase();
        return id.includes(item.id);
      });
      return candidate ? {
        ...item,
        name: pick(candidate, ["name", "agent_name", "title"], item.name),
        description: pick(candidate, ["description", "responsibility", "subtitle"], item.description),
      } : item;
    });
    const progress = workflowProgress(state.selected?.status || "detected");
    els["workflow-rail"].innerHTML = nodes.map((node, index) => {
      const nodeClass = index < progress.completed ? "completed" : index === progress.running ? "running" : "";
      const icon = index < progress.completed ? "fa-check" : node.icon;
      const caption = index < progress.completed ? "已完成" : index === progress.running ? "运行中" : node.description;
      return `
        <div class="agent-node ${nodeClass}">
          <div class="agent-icon"><i class="fa-solid ${escapeHtml(icon)}"></i></div>
          <div><h3>${escapeHtml(node.name)}</h3><small>${escapeHtml(caption)}</small></div>
        </div>`;
    }).join("");
  }

  function normalizeMetric(metric, key) {
    const before = Number(pick(metric, ["before", "pre", "original"], NaN));
    const after = Number(pick(metric, ["after", "post", "current"], NaN));
    const unitDefaults = {
      latency_ms: "ms",
      packet_loss_pct: "%",
      cpu_usage_pct: "%",
      throughput_mbps: "Mbps",
      attach_success_pct: "%",
      availability_pct: "%",
      bandwidth_utilization_pct: "%",
    };
    return {
      key,
      label: pick(metric, ["label", "name"], ({
        latency_ms: "业务时延",
        packet_loss_pct: "丢包率",
        cpu_usage_pct: "UPF CPU",
        throughput_mbps: "吞吐量",
        attach_success_pct: "接入成功率",
        availability_pct: "链路可用率",
        bandwidth_utilization_pct: "带宽利用率",
      })[key] || key),
      before,
      after,
      unit: pick(metric, ["unit"], unitDefaults[key] || ""),
    };
  }

  function verificationMetrics(verification) {
    if (!verification || typeof verification !== "object") return [];
    let source = pick(verification, ["metrics", "kpi_comparison", "comparison"], {});
    if (Array.isArray(source)) {
      return source.map((item, index) => normalizeMetric(item, pick(item, ["key", "metric"], `metric_${index}`)));
    }
    const checks = pick(verification, ["checks"], []);
    if (Array.isArray(checks) && checks.length) {
      return checks.map((item, index) => normalizeMetric(item, pick(item, ["metric"], `metric_${index}`)));
    }
    if (!source || typeof source !== "object") source = {};
    const results = [];
    Object.entries(source).forEach(([key, value]) => {
      if (typeof value === "object" && value) results.push(normalizeMetric(value, key));
    });
    ["latency", "packet_loss", "cpu", "throughput", "access_success_rate", "bandwidth_utilization"].forEach((key) => {
      const before = verification[`before_${key}`];
      const after = verification[`after_${key}`];
      if (before !== undefined || after !== undefined) {
        results.push(normalizeMetric({ before, after }, key));
      }
    });
    return results.filter((item, index, list) => list.findIndex((other) => other.key === item.key) === index);
  }

  function renderKpis() {
    const incident = state.selected;
    const metrics = verificationMetrics(incident?.verification);
    if (!incident || !metrics.length) {
      els["validation-badge"].className = "validation-badge";
      els["validation-badge"].innerHTML = '<i class="fa-solid fa-minus"></i> 等待验证';
      els["kpi-comparison"].innerHTML = `
        <div class="empty-state compact">
          <i class="fa-solid fa-chart-line"></i><p>执行修复并验证后展示前后指标对比。</p>
        </div>`;
      return;
    }

    const passed = incident.verificationPassed;
    els["validation-badge"].className = `validation-badge ${passed ? "passed" : "failed"}`;
    els["validation-badge"].innerHTML = `<i class="fa-solid ${passed ? "fa-check" : "fa-xmark"}"></i> ${passed ? "恢复达标" : "未达阈值"}`;
    els["kpi-comparison"].innerHTML = metrics.slice(0, 4).map((metric) => {
      const valid = Number.isFinite(metric.before) && Number.isFinite(metric.after);
      const improvement = valid && metric.before !== 0
        ? Math.abs(((metric.after - metric.before) / metric.before) * 100)
        : 0;
      return `
        <article class="kpi-item">
          <header><span>${escapeHtml(metric.label)}</span><strong>${valid ? `${improvement.toFixed(1)}%` : "--"}</strong></header>
          <div class="kpi-values">
            <div><span>修复前</span><strong>${valid ? escapeHtml(metric.before) : "--"}${escapeHtml(metric.unit)}</strong></div>
            <i class="fa-solid fa-arrow-right"></i>
            <div><span>修复后</span><strong>${valid ? escapeHtml(metric.after) : "--"}${escapeHtml(metric.unit)}</strong></div>
          </div>
        </article>`;
    }).join("");

    // Render KPI timeseries chart
    renderKpiTimeseries();
  }

  // ---- P2-2: Candidate root-cause comparison ----
  function renderCandidateComparison(incident) {
    const candidates = incident?.evidence?.ranked_candidates;
    if (!candidates || !candidates.length || candidates.length < 2) return;

    const section = els["evidence-grid"]?.parentNode;
    if (!section) return;

    // Remove existing comparison if any
    const existing = document.getElementById("candidate-comparison");
    if (existing) existing.remove();

    const container = document.createElement("div");
    container.id = "candidate-comparison";
    container.innerHTML = `
      <div class="section-title"><span>候选根因对比</span><small>${candidates.length} 个候选</small></div>
      <div class="candidate-list">
        ${candidates.slice(0, 4).map((c, i) => `
          <div class="candidate-item ${i === 0 ? 'primary' : ''}">
            <div class="candidate-rank">#${i + 1}</div>
            <div class="candidate-info">
              <strong>${escapeHtml(c.title || c.root_cause || '未知')}</strong>
              <div class="candidate-bar">
                <span style="width:${Math.round((c.confidence || 0) * 100)}%"></span>
              </div>
              <div class="candidate-meta">
                <span>置信度 ${Math.round((c.confidence || 0) * 100)}%</span>
                <span>证据 ${Math.round((c.evidence_coverage || 0) * 100)}%</span>
                <span>${(c.matched_alarm_count || 0)} 告警</span>
                <span>${(c.matched_kpi_count || 0)} KPI</span>
              </div>
            </div>
          </div>
        `).join("")}
      </div>`;

    section.after(container);
  }

  // ---- P2-1: KPI Timeseries Chart ----
  function renderKpiTimeseries() {
    const svg = d3.select(els["kpi-timeseries-svg"]);
    svg.selectAll("*").remove();
    const incident = state.selected;
    if (!incident || !incident.scenarioId) {
      els["kpi-timeseries-empty"].classList.remove("hidden");
      return;
    }
    els["kpi-timeseries-empty"].classList.add("hidden");

    // Fetch metrics data
    api(`/metrics?scenario_id=${encodeURIComponent(incident.scenarioId)}`).then((payload) => {
      const series = asArray(pick(payload, ["series"], []));
      if (!series.length) return;
      renderTimeseriesChart(series);
    }).catch(() => {});

    function renderTimeseriesChart(series) {
      const width = els["kpi-timeseries-svg"].clientWidth || 400;
      const height = els["kpi-timeseries-svg"].clientHeight || 180;
      svg.attr("viewBox", `0 0 ${width} ${height}`);

      const phases = ["baseline", "incident", "post_repair"];
      const phaseColors = { baseline: "#39e7a5", incident: "#ff607d", post_repair: "#29d8ff" };
      const phaseLabels = { baseline: "正常基线", incident: "故障期", post_repair: "修复后" };

      // Group by metric
      const metricMap = {};
      series.forEach((row) => {
        const key = row.metric || "unknown";
        if (!metricMap[key]) metricMap[key] = [];
        metricMap[key].push(row);
      });

      const metrics = Object.keys(metricMap).slice(0, 3);
      const margin = { top: 28, right: 20, bottom: 30, left: 45 };
      const chartW = width - margin.left - margin.right;
      const chartH = height - margin.top - margin.bottom;

      // Phase bands
      const bandWidth = chartW / 3;
      phases.forEach((phase, i) => {
        svg.append("rect")
          .attr("x", margin.left + i * bandWidth)
          .attr("y", margin.top)
          .attr("width", bandWidth)
          .attr("height", chartH)
          .attr("fill", phaseColors[phase])
          .attr("opacity", 0.06);

        svg.append("text")
          .attr("x", margin.left + i * bandWidth + bandWidth / 2)
          .attr("y", margin.top - 6)
          .attr("text-anchor", "middle")
          .attr("fill", phaseColors[phase])
          .attr("font-size", "10px")
          .attr("font-weight", "600")
          .text(phaseLabels[phase]);
      });

      // Draw line for each metric
      metrics.forEach((metric, mIdx) => {
        const rows = metricMap[metric];
        const values = rows.map((r) => parseFloat(r.value) || 0);
        const allVals = values;
        const maxVal = Math.max(...allVals, 1);
        const minVal = Math.min(...allVals, 0);
        const range = maxVal - minVal || 1;

        const points = rows.map((r, i) => {
          const x = margin.left + (i / Math.max(rows.length - 1, 1)) * chartW;
          const y = margin.top + chartH - ((parseFloat(r.value) - minVal) / range) * chartH;
          return [x, y];
        });

        const line = d3.line()(points);
        const colors = ["#29d8ff", "#9e82ff", "#39e7a5"];

        svg.append("path")
          .attr("d", line)
          .attr("fill", "none")
          .attr("stroke", colors[mIdx % 3])
          .attr("stroke-width", "2")
          .attr("stroke-dasharray", mIdx === 0 ? "" : "4,3");

        // Dots
        svg.selectAll(`.dot-${mIdx}`)
          .data(points)
          .join("circle")
          .attr("cx", (d) => d[0])
          .attr("cy", (d) => d[1])
          .attr("r", "3.5")
          .attr("fill", colors[mIdx % 3]);

        // Legend
        svg.append("text")
          .attr("x", margin.left + mIdx * 80 + 5)
          .attr("y", height - 6)
          .attr("fill", colors[mIdx % 3])
          .attr("font-size", "9px")
          .text(metric.replace(/_/g, " "));
      });
    }
  }

  function normalizeTopology(payload) {
    const topology = unwrap(payload, "topology") || payload || {};
    const rawNodes = asArray(pick(topology, ["nodes", "network_elements"], []));
    const rawLinks = asArray(pick(topology, ["links", "edges", "connections"], []));
    return {
      nodes: rawNodes.map((node, index) => ({
        ...node,
        id: String(pick(node, ["id", "node_id", "name"], `node-${index}`)),
        name: pick(node, ["name", "label", "id"], `Node ${index + 1}`),
        type: String(pick(node, ["type", "node_type", "category"], "network")).toLowerCase(),
        status: String(pick(node, ["health", "status"], "healthy")).toLowerCase(),
      })),
      links: rawLinks.map((link) => ({
        ...link,
        source: typeof link.source === "object" ? link.source.id : pick(link, ["source", "from"]),
        target: typeof link.target === "object" ? link.target.id : pick(link, ["target", "to"]),
        status: String(pick(link, ["status", "health"], "healthy")).toLowerCase(),
      })).filter((link) => link.source && link.target),
    };
  }

  function renderTopology() {
    const { nodes, links } = state.topology;
    const svg = d3.select(els["topology-svg"]);
    svg.selectAll("*").remove();
    if (!nodes.length) {
      els["topology-empty"].classList.remove("hidden");
      return;
    }
    els["topology-empty"].classList.add("hidden");
    const width = els["topology-svg"].clientWidth || 700;
    const height = els["topology-svg"].clientHeight || 268;
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const rootCauseText = String(state.selected?.rootCause || "").toLowerCase();
    const rootResource = String(state.selected?.rootResource || "");
    const affectedText = `${state.selected?.impact || ""} ${state.selected?.summary || ""}`.toLowerCase();
    const graphNodes = nodes.map((node) => {
      const haystack = `${node.id} ${node.name}`.toLowerCase();
      const normalizedStatus = ["normal", "online", "active", "standby"].includes(node.status)
        ? "healthy"
        : node.status === "critical" ? "root-cause" : node.status;
      let derivedStatus = normalizedStatus;
      if (node.id === rootResource) {
        derivedStatus = state.selected?.status === "closed" ? "healthy" : "root-cause";
      } else if (rootCauseText && [...haystack.split(/\s+/)].some((token) => token.length > 2 && rootCauseText.includes(token))) {
        derivedStatus = "root-cause";
      } else if (affectedText && [...haystack.split(/\s+/)].some((token) => token.length > 2 && affectedText.includes(token))) {
        derivedStatus = "affected";
      }
      return { ...node, derivedStatus };
    });
    const rootIds = new Set(graphNodes.filter((node) => node.derivedStatus === "root-cause").map((node) => node.id));
    const affectedIds = new Set(graphNodes.filter((node) => node.derivedStatus === "affected").map((node) => node.id));
    const graphLinks = links.map((link) => ({
      ...link,
      derivedStatus: link.status === "affected" || rootIds.has(String(link.source)) || rootIds.has(String(link.target))
        || affectedIds.has(String(link.source)) || affectedIds.has(String(link.target))
        ? "affected"
        : "healthy",
    }));

    const layerByType = {
      gnodeb: 0,
      base_station: 0,
      backhaul_link: 1,
      router: 1,
      switch: 1,
      upf: 2,
      core: 2,
      network_slice: 3,
      slice: 3,
      service: 4,
      user: 4,
    };
    const layerLabels = ["接入网", "承载网", "核心网", "网络切片", "业务应用"];
    const horizontalPadding = Math.max(58, width * 0.07);
    const topPadding = 46;
    const bottomPadding = 50;
    const verticalOrder = {
      "gNodeB-01": 0,
      "gNodeB-03": 1,
      "LINK-01": 0,
      "LINK-03": 1,
      "UPF-02": 0,
      "UPF-01": 1,
      "slice-video": 0,
      "slice-urllc": 1,
      "video-service": 0,
      "industrial-control": 1,
    };
    const layers = d3.group(
      graphNodes,
      (node) => layerByType[node.type] ?? 2,
    );

    for (let layer = 0; layer < layerLabels.length; layer += 1) {
      const layerNodes = asArray(layers.get(layer)).sort(
        (left, right) => (verticalOrder[left.id] ?? 99) - (verticalOrder[right.id] ?? 99)
          || left.id.localeCompare(right.id),
      );
      const x = horizontalPadding
        + (layer * (width - horizontalPadding * 2)) / (layerLabels.length - 1);
      layerNodes.forEach((node, index) => {
        const usableHeight = Math.max(70, height - topPadding - bottomPadding);
        node.x = x;
        node.y = layerNodes.length === 1
          ? topPadding + usableHeight / 2
          : topPadding + (index * usableHeight) / (layerNodes.length - 1);
      });
    }

    svg.append("g")
      .selectAll("text")
      .data(layerLabels)
      .join("text")
      .attr("class", "topology-layer-label")
      .attr("x", (_, layer) => horizontalPadding
        + (layer * (width - horizontalPadding * 2)) / (layerLabels.length - 1))
      .attr("y", 19)
      .text((label) => label);

    const nodeById = new Map(graphNodes.map((node) => [node.id, node]));
    const renderedLinks = graphLinks.map((link) => ({
      ...link,
      sourceNode: nodeById.get(String(link.source)),
      targetNode: nodeById.get(String(link.target)),
    })).filter((link) => link.sourceNode && link.targetNode);

    svg.append("g")
      .selectAll("path")
      .data(renderedLinks)
      .join("path")
      .attr("class", (link) => `topology-link ${link.derivedStatus}`)
      .attr("d", (link) => {
        const source = link.sourceNode;
        const target = link.targetNode;
        const bend = Math.max(30, Math.abs(target.x - source.x) * 0.46);
        return `M${source.x},${source.y} C${source.x + bend},${source.y} ${target.x - bend},${target.y} ${target.x},${target.y}`;
      });

    const typeIcon = {
      gnodeb: "\uf519",
      backhaul_link: "\uf6ff",
      base_station: "\uf519",
      upf: "\uf233",
      core: "\uf233",
      router: "\uf6ff",
      switch: "\uf6ff",
      slice: "\uf5fd",
      network_slice: "\uf5fd",
      service: "\uf1b2",
      user: "\uf0c0",
    };
    const nodeGroups = svg.append("g")
      .selectAll("g")
      .data(graphNodes)
      .join("g")
      .attr("class", (node) => `topology-node ${node.derivedStatus}`)
      .attr("transform", (node) => `translate(${node.x}, ${node.y})`);
    nodeGroups.append("circle").attr("r", 19);
    nodeGroups.append("text")
      .attr("class", "node-icon")
      .attr("y", 4)
      .text((node) => typeIcon[node.type] || "\uf1eb");
    nodeGroups.append("text")
      .attr("y", 34)
      .text((node) => node.name);
    nodeGroups.append("text")
      .attr("class", "node-type")
      .attr("y", 44)
      .text((node) => node.type.toUpperCase());
  }

  function renderAudit() {
    const records = state.audit.slice(0, 30);
    if (!records.length) {
      els["audit-list"].innerHTML = `
        <div class="empty-state compact"><i class="fa-solid fa-clock-rotate-left"></i><p>暂无操作记录</p></div>`;
      return;
    }
    const actionIcons = {
      diagnose: "fa-stethoscope",
      approve: "fa-user-check",
      execute: "fa-terminal",
      verify: "fa-shield-check",
      create: "fa-plus",
      reset: "fa-rotate-left",
    };
    els["audit-list"].innerHTML = records.map((record) => {
      const action = String(pick(record, ["action", "operation"], "operation"));
      const actor = pick(record, ["actor", "operator"], "system");
      const detail = pick(record, ["detail", "message", "result"], "操作完成");
      const timestamp = pick(record, ["created_at", "timestamp", "time"], "");
      const icon = Object.entries(actionIcons).find(([key]) => action.toLowerCase().includes(key))?.[1] || "fa-fingerprint";
      return `
        <div class="audit-item">
          <span class="audit-icon"><i class="fa-solid ${icon}"></i></span>
          <div><strong>${escapeHtml(actor)} · ${escapeHtml(action)}</strong><p>${escapeHtml(summarizeValue(detail))}</p></div>
          <time>${escapeHtml(formatTime(timestamp))}</time>
        </div>`;
    }).join("");
  }

  async function selectIncident(id, force = false) {
    if (!id || (id === state.selectedId && !force)) return;
    state.selectedId = id;
    renderIncidents();
    try {
      const payload = await api(`/incidents/${encodeURIComponent(id)}`);
      const incident = normalizeIncident(unwrap(payload, "incident") || payload);
      incident.events = asArray(pick(payload, ["events"], []));
      state.selected = incident;
      const index = state.incidents.findIndex((item) => item.id === state.selected.id);
      if (index >= 0) state.incidents[index] = state.selected;
      renderSelected();
      renderIncidents();
      await loadTopology();
    } catch (error) {
      showToast("事件详情加载失败", error.message, "error");
    }
  }

  async function loadScenarios() {
    try {
      const payload = await api("/scenarios");
      const rows = asArray(pick(payload, ["items", "scenarios"], unwrap(payload)));
      if (!rows.length) return;
      const current = els["scenario-selector"].value;
      state.scenarios = rows;
      els["scenario-selector"].innerHTML = rows.map((scenario) => {
        const testCaseId = pick(scenario, ["test_case_id"], "TC");
        const title = pick(scenario, ["title"], scenario.id);
        return `<option value="${escapeHtml(scenario.id)}">${escapeHtml(testCaseId)} · ${escapeHtml(title)}</option>`;
      }).join("");
      if (rows.some((scenario) => scenario.id === current)) {
        els["scenario-selector"].value = current;
      }
    } catch (error) {
      state.scenarios = [
        { id: "upf-overload", test_case_id: "TC-01", title: "UPF负载过高" },
        { id: "backhaul-link-down", test_case_id: "TC-02", title: "回传链路中断" },
        { id: "slice-capacity-shortage", test_case_id: "TC-03", title: "URLLC切片资源不足" },
      ];
      if (!els["scenario-selector"].options.length) {
        showToast("测试用例目录加载失败", humanizeError(error.message), "error");
      }
    }
  }

  async function loadOverviewAndIncidents() {
    const [overviewPayload, incidentsPayload] = await Promise.all([
      api("/overview"),
      api("/incidents"),
    ]);
    state.overview = unwrap(overviewPayload, "overview") || overviewPayload || {};
    const rawIncidents = pick(
      incidentsPayload,
      ["incidents", "items"],
      unwrap(incidentsPayload),
    );
    state.incidents = asArray(rawIncidents).map(normalizeIncident);
    state.incidents.sort((left, right) => {
      const severityOrder = { critical: 0, major: 1, minor: 2, warning: 3, info: 4 };
      if (left.status === "closed" && right.status !== "closed") return 1;
      if (left.status !== "closed" && right.status === "closed") return -1;
      return (severityOrder[left.severity] ?? 5) - (severityOrder[right.severity] ?? 5);
    });
    renderOverview();
    renderIncidents();
    if (!state.selectedId && state.incidents.length) {
      await selectIncident(state.incidents[0].id);
    }
  }

  async function loadTopology() {
    try {
      const incidentQuery = state.selectedId
        ? `?incident_id=${encodeURIComponent(state.selectedId)}`
        : "";
      const payload = await api(`/topology${incidentQuery}`);
      state.topology = normalizeTopology(payload);
      renderTopology();
    } catch (error) {
      showToast("拓扑加载失败", error.message, "error");
      renderTopology();
    }
  }

  async function loadWorkflow() {
    try {
      const payload = await api("/workflow");
      const value = unwrap(payload, "workflow") || payload;
      state.workflow = asArray(pick(value, ["agents", "steps", "nodes"], value));
    } catch {
      state.workflow = [];
    }
    renderWorkflow();
  }

  async function loadAudit(silent = true) {
    try {
      const payload = await api("/audit");
      state.audit = asArray(
        pick(
          payload,
          ["audit", "records", "items"],
          unwrap(payload),
        ),
      );
      renderAudit();
      if (!silent) showToast("审计日志已刷新", `已载入 ${state.audit.length} 条记录`, "success");
    } catch (error) {
      if (!silent) showToast("审计日志加载失败", error.message, "error");
    }
  }

  async function refreshAll(silent = true) {
    try {
      await Promise.all([loadOverviewAndIncidents(), loadTopology(), loadWorkflow(), loadAudit(true)]);
      if (state.selectedId) await selectIncident(state.selectedId, true);
    } catch (error) {
      if (!silent) showToast("数据同步失败", error.message, "error");
    }
  }

  function setBusy(value, title = "", message = "") {
    state.busy = value;
    els["operation-overlay"].classList.toggle("hidden", !value);
    if (title) els["operation-title"].textContent = title;
    if (message) els["operation-message"].textContent = message;
    els["run-demo"].disabled = value;
    els["reset-demo"].disabled = value;
    els["scenario-selector"].disabled = value;
    if (state.selected) updateActionAvailability(state.selected.status);
  }

  async function performAction(action) {
    if (!state.selectedId || state.busy) return;
    const config = {
      diagnose: {
        path: "/incidents/diagnose",
        body: { scenario_id: state.selected.scenarioId, incident_id: state.selectedId },
        title: "多智能体正在联合诊断",
        message: "聚合告警、KPI、拓扑和专家知识，生成可解释根因排序。",
        success: "诊断完成",
      },
      approve: {
        path: `/incidents/${encodeURIComponent(state.selectedId)}/approve`,
        body: { comment: "驾驶舱人工复核通过，批准模拟执行。" },
        title: "正在记录变更审批",
        message: "校验审批角色、方案风险与状态流转，并写入审计记录。",
        success: "方案已审批",
      },
      execute: {
        path: `/incidents/${encodeURIComponent(state.selectedId)}/execute`,
        body: { dry_run: true },
        title: "正在执行安全仿真",
        message: "生成配置命令并在隔离仿真环境执行，不触碰真实网元。",
        success: "模拟执行完成",
      },
      verify: {
        path: `/incidents/${encodeURIComponent(state.selectedId)}/verify`,
        title: "正在验证网络恢复",
        message: "对比修复前后 KPI 与业务 SLA，决定闭环或回溯诊断。",
        success: "恢复验证完成",
      },
    }[action];
    if (!config) return;
    setBusy(true, config.title, config.message);
    try {
      await api(config.path, {
        method: "POST",
        body: JSON.stringify(config.body || {}),
      });
      await refreshAll(true);
      showToast(config.success, `${state.selected?.title || state.selectedId} 状态已更新。`, "success");
    } catch (error) {
      showToast("操作未完成", humanizeError(error.message), "error");
    } finally {
      setBusy(false);
    }
  }

  const DEMO_STAGES = [
    { id: "detected", label: "创建事件", icon: "fa-plus" },
    { id: "diagnosing", label: "四路并行取证", icon: "fa-magnifying-glass-chart" },
    { id: "approval_pending", label: "根因排序与方案审批", icon: "fa-brain" },
    { id: "executing", label: "仿真执行修复", icon: "fa-terminal" },
    { id: "verifying", label: "KPI 恢复验证", icon: "fa-shield-check" },
    { id: "closed", label: "生成闭环报告", icon: "fa-file-lines" },
  ];

  function setProgressStage(stageIndex, total) {
    const progressBar = els["operation-progress-bar"];
    if (progressBar) {
      progressBar.style.width = `${Math.round(((stageIndex + 1) / total) * 100)}%`;
    }
  }

  async function runDemo() {
    if (state.busy) return;
    const scenarioId = els["scenario-selector"].value || "upf-overload";
    const scenario = state.scenarios.find((item) => item.id === scenarioId);
    const testCaseId = pick(scenario, ["test_case_id"], "测试用例");
    const scenarioTitle = pick(scenario, ["title"], scenarioId);
    const demoId = `DEMO-${Date.now().toString(36).toUpperCase()}`;

    setBusy(
      true,
      `${testCaseId} 全自动闭环运行中 [${demoId}]`,
      `${scenarioTitle}：五类智能体正通过 Co-Sight DAG 完成诊断、决策、仿真执行与验证。`,
    );
    setProgressStage(0, DEMO_STAGES.length);

    try {
      // 分阶段展示进度
      const stageMessages = [
        "正在创建网络事件…",
        "告警/KPI/拓扑/知识库四路并行取证…",
        "多源证据融合，生成根因排序与修复方案…",
        "生成仿真配置命令并安全执行…",
        "对比修复前后 KPI，验证 SLA 恢复…",
        "生成 Markdown/HTML 闭环报告…",
      ];

      const payload = await api("/demo/run", {
        method: "POST",
        body: JSON.stringify({ scenario_id: scenarioId }),
      });

      // 模拟阶段进度动画
      for (let i = 1; i < DEMO_STAGES.length; i++) {
        await new Promise((resolve) => setTimeout(resolve, 180));
        setProgressStage(i, DEMO_STAGES.length);
        els["operation-message"].textContent = stageMessages[i] || stageMessages[0];
      }

      const result = unwrap(payload, "incident") || unwrap(payload, "result") || payload;
      const id = pick(result, ["id", "incident_id"], state.selectedId);
      if (id) state.selectedId = String(id);
      await refreshAll(true);
      showToast(
        `${testCaseId} 闭环测试通过 [${demoId}]`,
        `${scenarioTitle}已完成诊断、审批、仿真执行、KPI 恢复验证和报告生成。可点击"下载报告"获取完整闭环文档。`,
        "success",
      );
    } catch (error) {
      showToast(`${testCaseId} 闭环测试未通过`, humanizeError(error.message), "error");
    } finally {
      setBusy(false);
    }
  }

  async function resetDemo() {
    if (state.busy) return;
    const previousRole = els["role-selector"].value;
    if (previousRole !== "admin") {
      showToast("需要管理员权限", "请将右上角角色切换为“系统管理员”后重置演示数据。", "error");
      return;
    }
    setBusy(true, "正在重置演示环境", "清理事件状态并重新载入三类 5G 专网基准故障。");
    try {
      await api("/demo/reset", { method: "POST", body: "{}" });
      state.selectedId = null;
      state.selected = null;
      await refreshAll(true);
      showToast("演示环境已重置", "已恢复到初始事件队列。", "success");
    } catch (error) {
      showToast("重置失败", humanizeError(error.message), "error");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport() {
    if (!state.selectedId) {
      showToast("无法下载", "请先选择一个已完成闭环的事件。", "error");
      return;
    }
    const incident = state.selected;
    const reportData = incident?.repair?.report;
    const hasReport = reportData || (incident?.status === "closed");

    if (!hasReport) {
      showToast("报告不可用", "该事件尚未完成全流程闭环，请先运行诊断→审批→执行→验证。", "error");
      return;
    }

    setBusy(true, "正在获取闭环报告", "从服务器下载 HTML 和 Markdown 格式的故障闭环报告…");
    try {
      // 尝试下载 HTML 报告
      const htmlUrl = `${API_BASE}/incidents/${encodeURIComponent(state.selectedId)}/report/download/html`;
      const response = await fetch(htmlUrl, {
        headers: {
          "X-NetHeal-Actor": `dashboard-${els["role-selector"].value}`,
          "X-NetHeal-Role": els["role-selector"].value,
        },
      });
      if (response.ok) {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `NetHeal_Report_${state.selectedId}.html`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        showToast("报告已下载", `HTML 闭环报告已保存到本地。`, "success");
      } else {
        // 回退：通过 /report?format=both 获取路径信息
        const info = await api(`/incidents/${encodeURIComponent(state.selectedId)}/report?format=both`);
        if (info.html_path || info.markdown_path) {
          showToast(
            "报告就绪",
            `HTML: ${info.html_path || "未生成"} | Markdown: ${info.markdown_path || "未生成"}`,
            "success",
          );
        } else {
          showToast("报告未找到", "闭环报告文件尚未生成，请确保事件已完成全流程。", "error");
        }
      }
    } catch (error) {
      showToast("报告下载失败", humanizeError(error.message), "error");
    } finally {
      setBusy(false);
    }
  }

  function humanizeError(message) {
    const value = String(message || "未知错误");
    if (value.includes("permission") || value.includes("Permission") || value.includes("权限")) {
      return "当前角色没有执行该操作的权限，请切换到具备相应授权的角色。";
    }
    if (value.includes("transition") || value.includes("状态")) {
      return "当前事件状态不允许此操作，请按诊断、审批、执行、验证的顺序推进。";
    }
    return value;
  }

  function showToast(title, message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icon = type === "success" ? "fa-check" : type === "error" ? "fa-triangle-exclamation" : "fa-circle-info";
    toast.innerHTML = `
      <i class="fa-solid ${icon}"></i>
      <div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(message)}</p></div>
      <button aria-label="关闭提示"><i class="fa-solid fa-xmark"></i></button>`;
    toast.querySelector("button").addEventListener("click", () => toast.remove());
    els["toast-stack"].appendChild(toast);
    window.setTimeout(() => toast.remove(), 5000);
  }

  function bindEvents() {
    document.querySelectorAll(".filter-chip").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".filter-chip").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
        state.filter = button.dataset.filter;
        renderIncidents();
      });
    });
    els["role-selector"].addEventListener("change", () => {
      if (state.selected) updateActionAvailability(state.selected.status);
      showToast("操作角色已切换", `当前身份：${els["role-selector"].selectedOptions[0].textContent}`, "info");
    });
    els["scenario-selector"].addEventListener("change", async () => {
      const scenario = state.scenarios.find((item) => item.id === els["scenario-selector"].value);
      const existing = state.incidents.find((item) => item.scenarioId === els["scenario-selector"].value);
      if (existing) await selectIncident(existing.id);
      if (scenario) {
        showToast(
          `已选择 ${scenario.test_case_id}`,
          scenario.description || scenario.title,
          "info",
        );
      }
    });
    els["action-diagnose"].addEventListener("click", () => performAction("diagnose"));
    els["action-approve"].addEventListener("click", () => performAction("approve"));
    els["action-execute"].addEventListener("click", () => performAction("execute"));
    els["action-verify"].addEventListener("click", () => performAction("verify"));
    els["action-download-report"].addEventListener("click", downloadReport);
    els["run-demo"].addEventListener("click", runDemo);
    els["reset-demo"].addEventListener("click", resetDemo);
    els["refresh-audit"].addEventListener("click", () => loadAudit(false));

    // P2-1: KPI tab switching
    document.querySelectorAll(".kpi-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".kpi-tab").forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        const view = tab.dataset.view;
        els["kpi-comparison-view"].classList.toggle("hidden", view !== "comparison");
        els["kpi-timeseries-view"].classList.toggle("hidden", view !== "timeseries");
      });
    });

    window.addEventListener("resize", debounce(renderTopology, 180));
  }

  function debounce(fn, wait) {
    let timer;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), wait);
    };
  }

  function updateClock() {
    els["system-clock"].textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  }

  async function boot() {
    initElements();
    bindEvents();
    renderWorkflow();
    updateClock();
    window.setInterval(updateClock, 1000);
    try {
      await loadScenarios();
      await refreshAll(false);
    } catch (error) {
      showToast("NetHeal 服务尚未就绪", `${error.message}。请确认后端已启动。`, "error");
    }
    window.setInterval(() => {
      if (!state.busy && document.visibilityState === "visible") refreshAll(true);
    }, 8000);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
