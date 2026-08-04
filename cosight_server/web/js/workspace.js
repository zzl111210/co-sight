/* Interaction layer for the wide-screen execution workspace. */

(function () {
  "use strict";

  let lastToolPanel = null;
  let layoutTimer = null;
  let synchronizingPanels = false;

  function scheduleLayout(fit = true) {
    window.clearTimeout(layoutTimer);
    layoutTimer = window.setTimeout(() => {
      if (typeof window.handleResize === "function") {
        window.handleResize();
      }
      if (fit && typeof window.fitToScreen === "function") {
        window.setTimeout(() => window.fitToScreen(), 320);
      }
    }, 80);
  }

  function syncWorkspaceMode() {
    const middle = document.querySelector(".middle-container");
    const active = Boolean(middle && middle.classList.contains("show"));
    document.body.classList.toggle("workspace-mode", active);
    if (active) {
      scheduleLayout(true);
    }
  }

  function syncReportLayout() {
    const middle = document.querySelector(".middle-container");
    const rightPanel = document.getElementById("right-container");
    if (!middle || !rightPanel) return;

    middle.classList.toggle(
      "report-open",
      rightPanel.classList.contains("show")
    );
    scheduleLayout(true);
  }

  function visibleToolPanels() {
    return Array.from(
      document.querySelectorAll(
        "#tool-call-panels-container .tool-call-panel.show"
      )
    );
  }

  function syncToolDrawer(preferredPanel = null) {
    if (synchronizingPanels) return;
    synchronizingPanels = true;

    let panels = visibleToolPanels();
    const activePanel =
      preferredPanel && preferredPanel.classList.contains("show")
        ? preferredPanel
        : panels[panels.length - 1];

    if (activePanel) {
      lastToolPanel = activePanel;
      panels.forEach((panel) => {
        if (panel !== activePanel) {
          panel.classList.remove("show");
        }
      });
      panels = [activePanel];
    }

    const stage = document.getElementById("dag-stage");
    if (stage) {
      stage.classList.toggle("tool-drawer-open", panels.length > 0);
    }

    const drawerButton = document.querySelector(
      ".dag-toolbar-actions .workspace-icon-button:last-child"
    );
    if (drawerButton) {
      drawerButton.classList.toggle("active", panels.length > 0);
      drawerButton.setAttribute("aria-expanded", String(panels.length > 0));
    }

    synchronizingPanels = false;
    scheduleLayout(true);
  }

  function panelFromMutation(record) {
    if (
      record.type === "attributes" &&
      record.target.classList &&
      record.target.classList.contains("tool-call-panel")
    ) {
      return record.target;
    }
    for (const node of record.addedNodes || []) {
      if (!(node instanceof HTMLElement)) continue;
      if (node.matches(".tool-call-panel.show")) return node;
      const child = node.querySelector?.(".tool-call-panel.show");
      if (child) return child;
    }
    return null;
  }

  function observeWorkspace() {
    const middle = document.querySelector(".middle-container");
    if (middle) {
      new MutationObserver(syncWorkspaceMode).observe(middle, {
        attributes: true,
        attributeFilter: ["class"],
      });
    }

    const rightPanel = document.getElementById("right-container");
    if (rightPanel) {
      new MutationObserver(syncReportLayout).observe(rightPanel, {
        attributes: true,
        attributeFilter: ["class"],
      });
    }

    const toolContainer = document.getElementById(
      "tool-call-panels-container"
    );
    if (toolContainer) {
      new MutationObserver((records) => {
        let preferred = null;
        records.forEach((record) => {
          const candidate = panelFromMutation(record);
          if (candidate?.classList.contains("show")) {
            preferred = candidate;
          }
        });
        syncToolDrawer(preferred);
      }).observe(toolContainer, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["class"],
      });
    }

    const stage = document.getElementById("dag-stage");
    if (stage && "ResizeObserver" in window) {
      let resizeTimer = null;
      new ResizeObserver(() => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => scheduleLayout(false), 100);
      }).observe(stage);
    }

    const status = document.getElementById("right-container-status");
    if (status) {
      new MutationObserver(() => {
        status.title = status.textContent.trim();
      }).observe(status, { childList: true, subtree: true });
    }
  }

  function enhanceEmbeddedReport() {
    const iframe = document.getElementById("content-iframe");
    if (!iframe) return;
    iframe.addEventListener("load", () => {
      try {
        const doc = iframe.contentDocument;
        if (!doc || !/netheal/i.test(doc.title + " " + doc.body?.textContent)) {
          return;
        }
        if (doc.getElementById("cosight-report-readability")) return;
        const style = doc.createElement("style");
        style.id = "cosight-report-readability";
        style.textContent = [
          "body{font-size:17px!important;line-height:1.65!important}",
          "main{max-width:none!important;padding:30px 28px!important}",
          "h1{font-size:36px!important}",
          "h2{font-size:24px!important}",
          "th,td{padding:12px!important}",
        ].join("");
        doc.head.appendChild(style);
      } catch (_) {
        // Cross-origin reports remain untouched.
      }
    });
  }

  window.workspaceFitDag = function () {
    if (typeof window.fitToScreen === "function") {
      window.fitToScreen();
    } else {
      scheduleLayout(false);
    }
  };

  window.workspaceToggleToolDrawer = function () {
    const panels = visibleToolPanels();
    if (panels.length) {
      panels.forEach((panel) => panel.classList.remove("show"));
      syncToolDrawer();
      return;
    }
    if (lastToolPanel && lastToolPanel.isConnected) {
      lastToolPanel.classList.add("show");
      syncToolDrawer(lastToolPanel);
    }
  };

  window.workspaceOpenReport = function () {
    const iframe = document.getElementById("content-iframe");
    const source = iframe?.src || "";
    if (source && source !== "about:blank") {
      window.open(source, "_blank", "noopener,noreferrer");
      return;
    }
    const right = document.getElementById("right-container");
    if (right?.classList.contains("show") && !right.classList.contains("maximized")) {
      if (typeof window.toggleMaximizePanel === "function") {
        window.toggleMaximizePanel();
      }
    }
  };

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const panels = visibleToolPanels();
    if (panels.length) {
      panels.forEach((panel) => panel.classList.remove("show"));
      syncToolDrawer();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    observeWorkspace();
    enhanceEmbeddedReport();
    syncWorkspaceMode();
    syncReportLayout();
    syncToolDrawer();
  });
})();
