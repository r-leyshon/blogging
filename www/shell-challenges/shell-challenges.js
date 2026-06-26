(function () {
  const challenges = document.querySelectorAll(".shell-challenge[data-challenge-id]");
  if (!challenges.length) {
    return;
  }

  const dock = document.getElementById("shell-dock");
  const iframe = dock?.querySelector("iframe[data-src]");
  let sandboxReady = false;
  let pendingMessages = [];

  function getIframeWindow() {
    return iframe?.contentWindow || null;
  }

  function postToSandbox(message) {
    const payload = { source: "shell-challenges", ...message };
    const target = getIframeWindow();
    if (sandboxReady && target) {
      target.postMessage(payload, "*");
      return;
    }
    pendingMessages.push(payload);
  }

  function flushPendingMessages() {
    if (!sandboxReady) {
      return;
    }
    const target = getIframeWindow();
    if (!target) {
      return;
    }
    while (pendingMessages.length > 0) {
      target.postMessage(pendingMessages.shift(), "*");
    }
  }

  function openDock() {
    if (!dock) {
      return;
    }
    dock.classList.remove("shell-dock--collapsed");
    dock.classList.add("shell-dock--open");
    document.body.classList.add("shell-dock-open");

    const toggleBtn = dock.querySelector(".shell-dock-toggle");
    if (toggleBtn) {
      toggleBtn.textContent = "Hide sandbox";
      toggleBtn.setAttribute("aria-expanded", "true");
    }

    if (iframe && !iframe.getAttribute("src")) {
      iframe.setAttribute("src", iframe.dataset.src || "/www/shell-sandbox/index.html");
      iframe.addEventListener(
        "load",
        () => {
          const body = dock.querySelector(".shell-dock-body");
          body?.classList.add("is-ready");
        },
        { once: true }
      );
    }
  }

  function setStatus(block, className, html) {
    const status = block.querySelector(".shell-challenge-status");
    if (!status) {
      return;
    }
    status.className = `shell-challenge-status ${className}`.trim();
    status.innerHTML = html;
  }

  function renderResults(block, payload) {
    const status = block.querySelector(".shell-challenge-status");
    if (!status) {
      return;
    }

    const listItems = payload.results
      .map((item) => {
        const icon = item.passed ? "✓" : "✗";
        const className = item.passed ? "is-passed" : "is-failed";
        const detail = item.passed ? "" : ` — ${item.message}`;
        return `<li class="${className}">${icon} ${item.label}${detail}</li>`;
      })
      .join("");

    const overallClass = payload.passed ? "is-passed" : "is-failed";
    const overallText = payload.passed
      ? "All checks passed. Nice work."
      : "Not quite yet — see the checks below.";

    status.className = `shell-challenge-status ${overallClass}`;
    status.innerHTML = `<strong>${overallText}</strong><ul class="shell-challenge-results">${listItems}</ul>`;
  }

  function enableCheckButton(block) {
    const checkBtn = block.querySelector(".shell-challenge-check");
    if (checkBtn) {
      checkBtn.disabled = false;
    }
  }

  challenges.forEach((block) => {
    const exerciseId = block.dataset.challengeId;
    const startBtn = block.querySelector(".shell-challenge-start");
    const checkBtn = block.querySelector(".shell-challenge-check");

    startBtn?.addEventListener("click", () => {
      openDock();
      setStatus(block, "is-active", "Resetting sandbox for this challenge…");
      if (checkBtn) {
        checkBtn.disabled = true;
      }
      postToSandbox({ type: "shell:reset", exerciseId });
    });

    checkBtn?.addEventListener("click", () => {
      setStatus(block, "is-active", "Checking your work…");
      postToSandbox({ type: "shell:check", exerciseId });
    });
  });

  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || data.source !== "shell-sandbox") {
      return;
    }

    if (data.type === "shell:ready") {
      sandboxReady = true;
      flushPendingMessages();
      return;
    }

    if (data.type === "shell:reset-complete") {
      const block = document.querySelector(
        `.shell-challenge[data-challenge-id="${data.exerciseId}"]`
      );
      if (block) {
        setStatus(
          block,
          "is-active",
          `Challenge ready: <strong>${data.title}</strong>. Complete the task in the sandbox, then check your work.`
        );
        enableCheckButton(block);
      }
      return;
    }

    if (data.type === "shell:check-result") {
      const block = document.querySelector(
        `.shell-challenge[data-challenge-id="${data.exerciseId}"]`
      );
      if (block) {
        renderResults(block, data);
      }
      return;
    }

    if (data.type === "shell:error") {
      const block = document.querySelector(
        `.shell-challenge[data-challenge-id="${data.exerciseId}"]`
      );
      if (block) {
        setStatus(block, "is-failed", `Sandbox error: ${data.message}`);
      }
    }
  });
})();
