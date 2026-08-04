(() => {
  "use strict";

  function initLandingExperience() {
    const input = document.getElementById("initial-message-input");
    const sendButton = document.getElementById("initial-send-button");
    const characterCount = document.getElementById("landing-character-count");
    const templates = document.querySelectorAll(".prompt-template");

    if (!input || !sendButton) return;

    const syncComposerState = () => {
      const length = input.value.length;
      const hasTask = input.value.trim().length > 0;
      sendButton.disabled = !hasTask;
      if (characterCount) characterCount.textContent = String(length);
      input.closest(".initial-input-field-container")?.classList.toggle("has-value", hasTask);
    };

    templates.forEach((template) => {
      template.addEventListener("click", () => {
        input.value = template.dataset.prompt || "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      });
    });

    input.addEventListener("input", syncComposerState);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        input.value = "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    syncComposerState();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initLandingExperience);
  } else {
    initLandingExperience();
  }
})();
