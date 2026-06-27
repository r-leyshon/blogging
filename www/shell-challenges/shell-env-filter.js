(function () {
  const TAB_MAP = {
    "browser-sandbox": "browser",
    "local-terminal": "local",
    "what-is-codespaces": "codespaces",
  };

  const STORAGE_KEY = "shell-tutorial-env";
  const EXERCISES_URL = "/www/shell-sandbox/exercises.json";

  /** @type {Record<string, "full" | "partial" | "local">} */
  let exerciseCompat = {};

  function normalizeEnv(env) {
    if (env === "browser" || env === "local" || env === "codespaces") {
      return env;
    }
    return "browser";
  }

  function envFromTabId(tabId) {
    return TAB_MAP[tabId] || "browser";
  }

  function tabIdFromHash() {
    const hash = window.location.hash.replace(/^#/, "");
    return TAB_MAP[hash] ? hash : null;
  }

  function findTabset() {
    const heading = document.getElementById("choose-your-environment");
    if (heading) {
      const section = heading.closest("section");
      const tabset = section?.querySelector(".panel-tabset");
      if (tabset) {
        return tabset;
      }
    }
    return document.querySelector(".panel-tabset");
  }

  function getActiveTabId(tabset) {
    const activePane = tabset.querySelector(".tab-pane.active");
    if (activePane?.id) {
      return activePane.id;
    }
    const activeLink = tabset.querySelector('.nav-tabs .nav-link.active, .nav-tabs a.active');
    const href = activeLink?.getAttribute("href") || activeLink?.getAttribute("data-bs-target");
    if (href?.startsWith("#")) {
      return href.slice(1);
    }
    return "browser-sandbox";
  }

  function activateTab(tabset, tabId) {
    const link = tabset.querySelector(`a[href="#${tabId}"], a[data-bs-target="#${tabId}"]`);
    if (!link) {
      return false;
    }
    if (window.bootstrap?.Tab) {
      window.bootstrap.Tab.getOrCreateInstance(link).show();
      return true;
    }
    link.click();
    return true;
  }

  function compatAllows(env, compatAttr) {
    if (!compatAttr) {
      return true;
    }
    const allowed = compatAttr.trim().split(/\s+/);
    if (allowed.includes(env)) {
      return true;
    }
    if (env === "codespaces" && allowed.includes("local")) {
      return true;
    }
    if (env === "local" && allowed.includes("codespaces")) {
      return true;
    }
    return false;
  }

  function applyExerciseCompat() {
    document.querySelectorAll(".shell-challenge[id]").forEach((block) => {
      const id = block.id;
      const level = exerciseCompat[id];
      if (!level) {
        return;
      }
      block.dataset.shellBrowserCompat = level;
    });
  }

  function tryItSectionHasVisibleContent(section) {
    for (const child of section.children) {
      if (child.tagName === "H3") {
        continue;
      }
      if (!child.classList.contains("shell-env-hidden")) {
        return true;
      }
    }
    return false;
  }

  function updateTryItSections() {
    document.querySelectorAll("section.level3[id^='try-it']").forEach((section) => {
      const show = tryItSectionHasVisibleContent(section);
      section.classList.toggle("shell-env-hidden", !show);
      section.setAttribute("aria-hidden", show ? "false" : "true");
    });
  }

  function ensureLocalSelfCheckNote(block) {
    if (block.querySelector(".shell-challenge-local-note")) {
      return;
    }
    const note = document.createElement("p");
    note.className = "shell-challenge-local-note";
    note.innerHTML =
      "<strong>Self-check on your terminal.</strong> Complete the steps above and compare your output to the expected results described in the challenge.";
    const actions = block.querySelector(".shell-challenge-actions");
    if (actions) {
      actions.insertAdjacentElement("afterend", note);
    } else {
      block.appendChild(note);
    }
  }

  function applyFiltering(env) {
    const normalized = normalizeEnv(env);
    document.body.dataset.shellEnv = normalized;

    document.querySelectorAll(".shell-dock-open-btn").forEach((btn) => {
      const show = normalized === "browser";
      btn.classList.toggle("shell-env-hidden", !show);
    });

    document.querySelectorAll("[data-shell-compat]").forEach((el) => {
      const show = compatAllows(normalized, el.dataset.shellCompat);
      el.classList.toggle("shell-env-hidden", !show);
      el.setAttribute("aria-hidden", show ? "false" : "true");
    });

    const dock = document.getElementById("shell-dock");
    if (dock) {
      const showDock = normalized === "browser";
      dock.classList.toggle("shell-env-hidden", !showDock);
      dock.setAttribute("aria-hidden", showDock ? "false" : "true");
    }

    document.querySelectorAll(".shell-challenge[id]").forEach((block) => {
      const level = block.dataset.shellBrowserCompat || exerciseCompat[block.id] || "full";
      const actions = block.querySelector(".shell-challenge-actions");
      const localNote = block.querySelector(".shell-challenge-local-note");

      if (normalized === "browser") {
        if (actions) {
          actions.classList.remove("shell-env-hidden");
          actions.setAttribute("aria-hidden", "false");
        }
        if (localNote) {
          localNote.classList.add("shell-env-hidden");
        }
        block.classList.remove("shell-env-hidden");
        if (level === "local") {
          block.classList.add("shell-env-hidden");
          block.setAttribute("aria-hidden", "true");
        } else {
          block.setAttribute("aria-hidden", "false");
        }
      } else {
        block.classList.remove("shell-challenge--partial");
        if (block.querySelector(".shell-challenge-partial-note")) {
          block.querySelector(".shell-challenge-partial-note")?.remove();
        }
        if (level === "local") {
          block.classList.add("shell-env-hidden");
          block.setAttribute("aria-hidden", "true");
          return;
        }
        block.classList.remove("shell-env-hidden");
        block.setAttribute("aria-hidden", "false");
        if (actions) {
          actions.classList.add("shell-env-hidden");
          actions.setAttribute("aria-hidden", "true");
        }
        ensureLocalSelfCheckNote(block);
        if (localNote) {
          localNote.classList.remove("shell-env-hidden");
        }
      }
    });

    updateTryItSections();

    try {
      sessionStorage.setItem(STORAGE_KEY, normalized);
    } catch {
      /* ignore */
    }
  }

  function bindTabset(tabset) {
    tabset.addEventListener("shown.bs.tab", (event) => {
      const target = event.target?.getAttribute("href") || event.target?.getAttribute("data-bs-target");
      if (target?.startsWith("#")) {
        applyFiltering(envFromTabId(target.slice(1)));
      }
    });

    tabset.querySelectorAll('.nav-tabs a[data-bs-toggle="tab"], .nav-tabs a.nav-link').forEach((link) => {
      link.addEventListener("click", () => {
        const href = link.getAttribute("href") || link.getAttribute("data-bs-target");
        if (href?.startsWith("#")) {
          window.setTimeout(() => applyFiltering(envFromTabId(href.slice(1))), 0);
        }
      });
    });
  }

  async function loadExerciseCompat() {
    try {
      const response = await fetch(EXERCISES_URL);
      if (!response.ok) {
        return;
      }
      const catalog = await response.json();
      exerciseCompat = {};
      for (const exercise of catalog.exercises || []) {
        if (exercise.browserCompat) {
          exerciseCompat[exercise.id] = exercise.browserCompat;
        }
      }
      applyExerciseCompat();
    } catch {
      /* optional enhancement */
    }
  }

  function resolveInitialEnv(tabset) {
    const fromHash = tabIdFromHash();
    if (fromHash) {
      activateTab(tabset, fromHash);
      return envFromTabId(fromHash);
    }

    try {
      const stored = sessionStorage.getItem(STORAGE_KEY);
      if (stored === "local" || stored === "codespaces") {
        const tabId = stored === "local" ? "local-terminal" : "what-is-codespaces";
        activateTab(tabset, tabId);
        return stored;
      }
    } catch {
      /* ignore */
    }

    return envFromTabId(getActiveTabId(tabset));
  }

  async function init() {
    if (!document.getElementById("shell-dock")) {
      return;
    }

    await loadExerciseCompat();

    const tabset = findTabset();
    if (!tabset) {
      applyFiltering("browser");
      return;
    }

    bindTabset(tabset);
    const initialEnv = resolveInitialEnv(tabset);
    applyFiltering(initialEnv);

    window.addEventListener("hashchange", () => {
      const tabId = tabIdFromHash();
      if (tabId) {
        activateTab(tabset, tabId);
        applyFiltering(envFromTabId(tabId));
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
