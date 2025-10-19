// src/expense/static/js/ui.js

export function initMenu() {
  const menuBtn = document.getElementById("hamburger-menu-btn");
  const menu = document.getElementById("menu-container");
  if (!menuBtn || !menu) return;

  const closeMenu = () => {
    menu.classList.remove("show");
    menuBtn.classList.remove("clicked");
    menuBtn.textContent = "☰";
  };

  document.querySelectorAll("#theme-toggle, #asset-management-btn, #home-btn").forEach(btn => {
    btn.addEventListener("click", closeMenu);
  });

  menuBtn.addEventListener("click", () => {
    menu.classList.toggle("show");
    menuBtn.classList.toggle("clicked");
    menuBtn.textContent = menuBtn.textContent === "✕" ? "☰" : "✕";
  });

  document.addEventListener("click", (e) => {
    if (!menu.contains(e.target) && !menuBtn.contains(e.target)) {
      closeMenu();
    }
  });
}

export function initClosableMessages() {
  const closeBtn = document.getElementById("msg-close-btn");
  if (!closeBtn) return;

  const msg1 = document.getElementById("success-msg");
  const msg2 = document.getElementById("failed-msg");

  closeBtn.addEventListener("click", () => {
    if(msg1) msg1.style.display = "none";
    if(msg2) msg2.style.display = "none";
  });
}

export function initExpenseForm() {
  const typeSelect = document.getElementById("expense-type");
  if (!typeSelect) return;

  const amountInput = document.getElementById("expense-amount");
  const memoInput = document.getElementById("expense-memo");

  typeSelect.addEventListener("change", function() {
    const isShortcut = this.value.includes("/");
    if (amountInput) {
        amountInput.style.display = isShortcut ? "none" : "block";
        amountInput.required = !isShortcut;
    }
    if (memoInput) {
        memoInput.style.display = isShortcut ? "none" : "block";
    }
  });
}

export function initFormLoaders() {
  const forms = document.querySelectorAll("form");
  const loader = document.getElementById("loader");
  if (forms.length === 0 || !loader) return;

  forms.forEach((form) => {
    form.addEventListener("submit", () => {
      loader.style.display = "flex";
    });
  });
}

export function initThemeToggle() {
  const themeToggle = document.getElementById("theme-toggle");
  if (!themeToggle) return;

  themeToggle.addEventListener("click", () => {
    const isDark = document.documentElement.classList.toggle("dark");
    const newTheme = isDark ? "dark" : "light";
    localStorage.setItem("theme", newTheme);
    document.cookie = `theme=${newTheme};path=/;max-age=31536000`;
    location.reload();
  });
}

export function initScreenshotZoom() {
  const screenshot = document.getElementById("screenshot");
  const overlay = document.getElementById("img-overlay");
  if (!screenshot || !overlay) return;

  screenshot.addEventListener("click", () => {
    overlay.innerHTML = "";
    const zoomedImg = screenshot.cloneNode();
    overlay.appendChild(zoomedImg);
    requestAnimationFrame(() => {
      overlay.classList.add("show");
    });
  });

  overlay.addEventListener("click", () => {
    overlay.classList.remove("show");
    overlay.addEventListener(
      "transitionend",
      () => {
        if (!overlay.classList.contains("show")) {
          overlay.innerHTML = "";
        }
      },
      { once: true },
    );
  });
}

export function initCollapsibleSections() {
  const onOpenCallbacks = {
    report: () => requestAnimationFrame(() => Plotly.Plots.resize(document.querySelectorAll(".plotly-graph-div"))),
    "asset-report": () => requestAnimationFrame(() => Plotly.Plots.resize(document.querySelectorAll(".plotly-graph-div"))),
  };

  document.querySelectorAll(".collapsible-trigger").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const key = trigger.dataset.key;
      if (!key) return;

      const openClass = `${key}-open`;
      const collapsedClass = `${key}-collapsed`;
      const isCollapsed = document.documentElement.classList.contains(collapsedClass);

      if (isCollapsed) {
        document.documentElement.classList.remove(collapsedClass);
        document.documentElement.classList.add(openClass);
        localStorage.setItem(`${key}Collapsed`, "false");
        if (onOpenCallbacks[key]) {
          onOpenCallbacks[key]();
        }
      } else {
        document.documentElement.classList.remove(openClass);
        document.documentElement.classList.add(collapsedClass);
        localStorage.setItem(`${key}Collapsed`, "true");
      }
    });
  });
}

export function initRecordEditor() {
  const overlay = document.getElementById("confirmation-overlay");
  if (!overlay) return;

  const dialog = document.getElementById("confirmation-dialog");
  const closeBtn = document.getElementById("confirmation-close-btn");

  const fields = {
      delete: ["date", "type", "amount", "memo"],
      target: ["date", "type", "amount", "memo"],
      new: ["date", "type", "amount", "memo"],
  };
  const elements = {};
  for (const group in fields) {
      elements[group] = {};
      for (const field of fields[group]) {
          elements[group][field] = document.getElementById(`${group === 'new' ? 'new-expense' : group + '-record'}-${field}`);
      }
  }

  function showOverlay(row) {
    const [date, type, amount, memo] = Array.from(row.children).map(cell => cell.textContent);
    
    elements.delete.date.value = date;
    elements.delete.type.value = type;
    elements.delete.amount.value = amount;
    elements.delete.memo.value = memo;

    elements.target.date.value = date;
    elements.target.type.value = type;
    elements.target.amount.value = amount;
    elements.target.memo.value = memo;

    elements.new.date.value = date.replace(/\([月火水木金土日]\)/, "");
    elements.new.type.value = type;
    elements.new.amount.value = amount;
    elements.new.memo.value = memo;

    overlay.style.display = "flex";
  }

  let pressTimer;
  const longPressTime = 500;
  document.querySelectorAll("tbody tr").forEach((row) => {
    row.addEventListener("contextmenu", (e) => e.preventDefault());
    row.addEventListener("mousedown", () => { pressTimer = setTimeout(() => showOverlay(row), longPressTime); });
    row.addEventListener("mouseup", () => clearTimeout(pressTimer));
    row.addEventListener("mouseleave", () => clearTimeout(pressTimer));
    row.addEventListener("touchstart", () => { pressTimer = setTimeout(() => showOverlay(row), longPressTime); }, { passive: true });
    row.addEventListener("touchend", () => clearTimeout(pressTimer));
    row.addEventListener("touchmove", () => clearTimeout(pressTimer));
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", () => { overlay.style.display = "none"; });
  }

  overlay.addEventListener("click", function(e) {
    if (dialog && !dialog.contains(e.target)) {
      overlay.style.display = "none";
    }
  });
}

export function initPwaInstall() {
  const installBtn = document.getElementById("install-btn");
  if (!installBtn) return;

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/service-worker.js");
  }

  let deferredPrompt;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    installBtn.style.display = "block";
  });

  installBtn.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
  });
}
