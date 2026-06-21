(function () {
  const dock = document.getElementById("shell-dock");
  if (!dock) {
    return;
  }

  const toggleBtn = dock.querySelector(".shell-dock-toggle");
  const header = dock.querySelector(".shell-dock-header");
  const body = dock.querySelector(".shell-dock-body");
  const iframe = dock.querySelector("iframe[data-src]");
  const openButtons = document.querySelectorAll(".shell-dock-open-btn");

  const SANDBOX_URL = "/www/shell-sandbox/index.html";

  function isOpen() {
    return dock.classList.contains("shell-dock--open");
  }

  function loadIframe() {
    if (!iframe || iframe.getAttribute("src")) {
      return;
    }
    iframe.setAttribute("src", iframe.dataset.src || SANDBOX_URL);
    iframe.addEventListener("load", function () {
      if (body) {
        body.classList.add("is-ready");
      }
    });
  }

  function setOpen(open) {
    dock.classList.toggle("shell-dock--collapsed", !open);
    dock.classList.toggle("shell-dock--open", open);
    document.body.classList.toggle("shell-dock-open", open);

    if (toggleBtn) {
      toggleBtn.textContent = open ? "Hide sandbox" : "Show sandbox";
      toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
    }

    if (open) {
      loadIframe();
    }
  }

  function toggleDock() {
    setOpen(!isOpen());
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleDock();
    });
  }

  if (header) {
    header.addEventListener("click", toggleDock);
  }

  openButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setOpen(true);
    });
  });
})();
