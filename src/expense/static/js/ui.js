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

  document
    .querySelectorAll("#theme-toggle, #asset-management-btn, #home-btn")
    .forEach((btn) => {
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
    if (msg1) msg1.style.display = "none";
    if (msg2) msg2.style.display = "none";
  });
}

export function initExpenseForm() {
  const typeSelect = document.getElementById("expense-type");
  if (!typeSelect) return;

  const amountInput = document.getElementById("expense-amount");
  const memoInput = document.getElementById("expense-memo");

  const handleShortcutExpansion = (val) => {
    if (!val) return;
    const isShortcut = val.includes("/");

    if (isShortcut) {
      // ショートカットの場合は「/」で分割して各フィールドにセット
      // config.jsonで定義されたアイコンを除去
      const favoriteIcon = typeSelect.dataset.favoriteIcon;
      const frequentIcon = typeSelect.dataset.frequentIcon;
      const recentIcon = typeSelect.dataset.recentIcon;
      const icons = [favoriteIcon, frequentIcon, recentIcon].filter((i) => i);

      let cleanVal = val;
      for (const icon of icons) {
        if (val.startsWith(icon)) {
          cleanVal = val.slice(icon.length).trim();
          break;
        }
      }

      const parts = cleanVal.split("/");
      if (parts.length >= 2) {
        const type = parts[0].trim();
        // セレクトボックスの値を、ショートカットではない純粋な支出タイプに変更する
        // これにより、登録時に純粋なタイプ名が送信される
        for (let i = 0; i < typeSelect.options.length; i++) {
          if (typeSelect.options[i].value === type) {
            typeSelect.selectedIndex = i;
            break;
          }
        }

        if (parts.length === 3) {
          if (memoInput) memoInput.value = parts[1];
          if (amountInput) amountInput.value = parts[2].replace(/[^\d]/g, "");
        } else if (parts.length === 2) {
          if (memoInput) memoInput.value = "";
          if (amountInput) amountInput.value = parts[1].replace(/[^\d]/g, "");
        }
      }
    }
  };

  // ロード時の初期値に対しても適用
  handleShortcutExpansion(typeSelect.value);

  typeSelect.addEventListener("change", function() {
    handleShortcutExpansion(this.value);
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

export function initOcrReload() {
  const reloadButton = document.getElementById("ocr-reload-btn");
  const screenshotName = document.getElementById("screenshot-name-text");
  const screenshot = document.getElementById("screenshot");
  const submitButton = document.getElementById("ocr-submit-btn");
  const submitLabel = document.getElementById("ocr-submit-label");
  if (
    !reloadButton ||
    !screenshotName ||
    !screenshot ||
    !submitButton ||
    !submitLabel
  ) {
    return;
  }

  reloadButton.addEventListener("click", async () => {
    try {
      const response = await fetch("/api/ocr/latest");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.screenshot_name) return;

      screenshotName.textContent = `対象画像 : ${data.screenshot_name}`;
      screenshot.src = `data:image/png;base64,${data.screenshot_base64}`;
      screenshot.alt = data.screenshot_name;
      submitButton.disabled = data.disable_ocr;
      submitLabel.textContent = data.disable_ocr ? "登録済" : "読取実行";
    } catch (error) {
      console.error("OCR画像のリロードに失敗しました。", error);
    }
  });
}

export function initCollapsibleSections() {
  const triggers = document.querySelectorAll(".collapsible-trigger");
  const onOpenCallbacks = {
    report: () =>
      requestAnimationFrame(() =>
        Plotly.Plots.resize(document.querySelectorAll(".plotly-graph-div")),
      ),
    "asset-report": () =>
      requestAnimationFrame(() =>
        Plotly.Plots.resize(document.querySelectorAll(".plotly-graph-div")),
      ),
  };

  triggers.forEach((trigger) => {
    const key = trigger.dataset.key;
    if (!key) return;

    const container = trigger.closest(".card")?.querySelector(
      ".collapsible-content",
    );
    const isCollapsed = localStorage.getItem(`${key}Collapsed`) === "true";
    const openClass = `${key}-open`;
    const collapsedClass = `${key}-collapsed`;
    const setCollapsed = (collapsed) => {
      document.documentElement.classList.toggle(collapsedClass, collapsed);
      document.documentElement.classList.toggle(openClass, !collapsed);
      container?.classList.toggle("is-open", !collapsed);
      trigger.setAttribute("aria-expanded", String(!collapsed));
    };

    setCollapsed(isCollapsed);

    trigger.addEventListener("click", () => {
      const collapsed = !document.documentElement.classList.contains(
        collapsedClass,
      );
      setCollapsed(collapsed);
      localStorage.setItem(`${key}Collapsed`, String(collapsed));

      if (!collapsed && onOpenCallbacks[key]) {
        onOpenCallbacks[key]();
      }
    });
  });
}

export function initCardReordering() {
  const container = document.querySelector(".container");
  const cards = Array.from(container?.querySelectorAll(":scope > .card") ?? []);
  if (!container || cards.length < 2) return;

  const pageKey = location.pathname === "/asset_management" ? "asset" : "home";
  const storageKey = `expense.cardOrder.${pageKey}`;
  const cardByKey = new Map(
    cards
      .map((card) => [card.dataset.cardKey, card])
      .filter(([key]) => key),
  );

  try {
    const savedKeys = JSON.parse(localStorage.getItem(storageKey) || "[]");
    if (Array.isArray(savedKeys)) {
      savedKeys
        .filter((key) => cardByKey.has(key))
        .forEach((key) => container.appendChild(cardByKey.get(key)));
    }
  } catch {
    localStorage.removeItem(storageKey);
  }

  const saveOrder = () => {
    const order = Array.from(container.querySelectorAll(":scope > .card"))
      .map((card) => card.dataset.cardKey)
      .filter(Boolean);
    localStorage.setItem(storageKey, JSON.stringify(order));
  };

  const collapseCardsForDrag = () => {
    const states = cards.map((card) => {
      const trigger = card.querySelector(".collapsible-trigger");
      const content = card.querySelector(".collapsible-content");
      const key = trigger?.dataset.key;
      const collapsed = trigger?.getAttribute("aria-expanded") !== "true";
      card.classList.add("is-drag-collapsed");
      trigger?.setAttribute("aria-expanded", "false");
      content?.classList.remove("is-open");
      if (key) {
        document.documentElement.classList.remove(`${key}-open`);
        document.documentElement.classList.add(`${key}-collapsed`);
      }
      return { card, trigger, content, key, collapsed };
    });

    return () => {
      states.forEach(({ card, trigger, content, key, collapsed }) => {
        card.classList.remove("is-drag-collapsed");
        trigger?.setAttribute("aria-expanded", String(!collapsed));
        content?.classList.toggle("is-open", !collapsed);
        if (key) {
          document.documentElement.classList.toggle(`${key}-open`, !collapsed);
          document.documentElement.classList.toggle(`${key}-collapsed`, collapsed);
        }
      });
    };
  };

  let draggedCard = null;
  let restoreCollapsedCards = null;
  cards.forEach((card) => {
    const handle = card.querySelector(".collapsible-trigger");
    if (!handle) return;

    let touchStart = null;
    let touchDragging = false;
    let suppressClick = false;
    let touchPreview = null;
    let touchPlaceholder = null;
    let touchOffset = null;
    let touchOriginalStyle = null;
    let touchTimer = null;
    let touchPointerId = null;
    let touchLastY = null;
    let touchScrolling = false;

    const clearTouchDrag = (save) => {
      if (!touchDragging) return;
      if (touchPlaceholder?.parentNode) {
        touchPlaceholder.parentNode.insertBefore(card, touchPlaceholder);
        touchPlaceholder.remove();
      }
      if (touchOriginalStyle === null) {
        card.removeAttribute("style");
      } else {
        card.setAttribute("style", touchOriginalStyle);
      }
      touchPreview?.remove();
      if (save) saveOrder();
      restoreCollapsedCards?.();
      restoreCollapsedCards = null;
      card.classList.remove("is-dragging");
      cards.forEach((item) => item.classList.remove("drop-target"));
      draggedCard = null;
      touchPreview = null;
      touchPlaceholder = null;
      touchOffset = null;
      touchOriginalStyle = null;
      touchPointerId = null;
      touchDragging = false;
    };

    const startTouchDrag = (x, y) => {
      if (touchDragging) return;
      touchDragging = true;
      suppressClick = true;
      draggedCard = card;
      const initialRect = card.getBoundingClientRect();
      restoreCollapsedCards = collapseCardsForDrag();
      card.classList.add("is-dragging");
      const rect = card.getBoundingClientRect();
      touchOffset = {
        x: x - initialRect.left,
        y: y - initialRect.top,
      };
      touchPlaceholder = document.createElement("div");
      touchPlaceholder.className = "card-drop-placeholder";
      touchPlaceholder.style.height = `${rect.height}px`;
      touchOriginalStyle = card.getAttribute("style");
      container.insertBefore(touchPlaceholder, card);
      card.style.position = "fixed";
      card.style.left = "-10000px";
      card.style.top = "-10000px";
      card.style.pointerEvents = "none";
      touchPreview = card.cloneNode(true);
      touchPreview.classList.add("card-drag-preview");
      touchPreview.style.width = `${rect.width}px`;
      touchPreview.style.left = `${x - touchOffset.x}px`;
      touchPreview.style.top = `${y - touchOffset.y}px`;
      touchPreview.style.transform = "rotate(0deg)";
      document.body.appendChild(touchPreview);
      handle.setPointerCapture(touchPointerId);
    };

    handle.draggable = true;
    handle.classList.add("card-drag-handle");
    handle.addEventListener("dragstart", (event) => {
      draggedCard = card;
      restoreCollapsedCards = collapseCardsForDrag();
      card.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.cardKey || "");
    });
    handle.addEventListener("dragend", () => {
      restoreCollapsedCards?.();
      restoreCollapsedCards = null;
      card.classList.remove("is-dragging");
      draggedCard = null;
      cards.forEach((item) => item.classList.remove("drop-target"));
    });

    handle.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "touch") return;
      handle.draggable = false;
      touchStart = { x: event.clientX, y: event.clientY };
      touchLastY = event.clientY;
      touchScrolling = false;
      touchPointerId = event.pointerId;
      touchDragging = false;
      suppressClick = false;
      touchTimer = setTimeout(
        () => startTouchDrag(touchStart.x, touchStart.y),
        300,
      );
    });
    handle.addEventListener(
      "pointermove",
      (event) => {
        if (event.pointerType !== "touch" || !touchStart) return;
        const distance = Math.hypot(
          event.clientX - touchStart.x,
          event.clientY - touchStart.y,
        );
        if (!touchDragging) {
          if (distance >= 8) {
            clearTimeout(touchTimer);
            touchScrolling = true;
            suppressClick = true;
          }
          if (touchScrolling) {
            window.scrollBy(0, touchLastY - event.clientY);
            touchLastY = event.clientY;
          }
          return;
        }

        event.preventDefault();
        touchPreview.style.left = `${event.clientX - touchOffset.x}px`;
        touchPreview.style.top = `${event.clientY - touchOffset.y}px`;
        const tilt = Math.max(-4, Math.min(4, (event.clientX - touchStart.x) / 8));
        touchPreview.style.transform = `rotate(${tilt}deg)`;
        const target = document
          .elementFromPoint(event.clientX, event.clientY)
          ?.closest(".card");
        if (!target || !cardByKey.has(target.dataset.cardKey) || target === card) {
          return;
        }

        cards.forEach((item) => item.classList.remove("drop-target"));
        target.classList.add("drop-target");
        const rect = target.getBoundingClientRect();
        const insertBefore = event.clientY < rect.top + rect.height / 2;

        const previousPositions = new Map(
          cards.map((item) => [item, item.getBoundingClientRect()]),
        );
        container.insertBefore(
          touchPlaceholder,
          insertBefore ? target : target.nextSibling,
        );

        cards.forEach((item) => {
          const previous = previousPositions.get(item);
          const current = item.getBoundingClientRect();
          if (!previous) return;
          const offsetY = previous.top - current.top;
          if (offsetY === 0) return;
          item.getAnimations().forEach((animation) => animation.cancel());
          item.animate(
            [
              { transform: `translateY(${offsetY}px)` },
              { transform: "translateY(0)" },
            ],
            {
              duration: 180,
              easing: "ease-out",
            },
          );
        });
      },
      { passive: false },
    );
    handle.addEventListener("pointerup", (event) => {
      if (event.pointerType !== "touch") return;
      const hasCapture = handle.hasPointerCapture(event.pointerId);
      clearTimeout(touchTimer);
      clearTouchDrag(true);
      if (hasCapture) {
        handle.releasePointerCapture(event.pointerId);
      }
      handle.draggable = true;
      touchStart = null;
      touchLastY = null;
      touchScrolling = false;
    });
    handle.addEventListener("pointercancel", () => {
      clearTimeout(touchTimer);
      clearTouchDrag(false);
      handle.draggable = true;
      touchStart = null;
      touchLastY = null;
      touchScrolling = false;
    });
    handle.addEventListener("click", (event) => {
      if (!suppressClick) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      suppressClick = false;
    });
  });

  cards.forEach((card) => {
    card.addEventListener("dragover", (event) => {
      if (!draggedCard || draggedCard === card) return;
      event.preventDefault();
      cards.forEach((item) => item.classList.remove("drop-target"));
      card.classList.add("drop-target");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drop-target"));
    card.addEventListener("drop", (event) => {
      event.preventDefault();
      if (!draggedCard || draggedCard === card) return;
      const rect = card.getBoundingClientRect();
      const insertBefore = event.clientY < rect.top + rect.height / 2;
      container.insertBefore(draggedCard, insertBefore ? card : card.nextSibling);
      card.classList.remove("drop-target");
      saveOrder();
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
      elements[group][field] = document.getElementById(
        `${group === "new" ? "new-expense" : group + "-record"}-${field}`,
      );
    }
  }

  function showOverlay(row) {
    const [date, type, amount, memo] = Array.from(row.children).map(
      (cell) => cell.textContent,
    );

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
    row.addEventListener("mousedown", () => {
      pressTimer = setTimeout(() => showOverlay(row), longPressTime);
    });
    row.addEventListener("mouseup", () => clearTimeout(pressTimer));
    row.addEventListener("mouseleave", () => clearTimeout(pressTimer));
    row.addEventListener(
      "touchstart",
      () => {
        pressTimer = setTimeout(() => showOverlay(row), longPressTime);
      },
      { passive: true },
    );
    row.addEventListener("touchend", () => clearTimeout(pressTimer));
    row.addEventListener("touchmove", () => clearTimeout(pressTimer));
  });

  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      overlay.style.display = "none";
    });
  }

  overlay.addEventListener("click", function(e) {
    if (dialog && !dialog.contains(e.target)) {
      overlay.style.display = "none";
    }
  });
}

export function initAssetAllocationLongPress() {
  const overlay = document.getElementById("allocation-tickers-overlay");
  const dialog = document.getElementById("allocation-tickers-dialog");
  const list = document.getElementById("allocation-tickers-list");
  const closeBtn = document.getElementById("allocation-tickers-close-btn");
  const rows = document.querySelectorAll("#asset-allocation-container tbody tr");
  if (!overlay || !dialog || !list || !closeBtn || !rows.length) return;

  let pressTimer;
  const close = () => {
    overlay.style.display = "none";
  };
  const show = (row) => {
    let tickers;
    try {
      tickers = JSON.parse(row.dataset.tickers || "null");
    } catch {
      return;
    }
    if (!Array.isArray(tickers) || !tickers.length) return;

    list.replaceChildren(
      ...tickers.map((ticker) => {
        const item = document.createElement("li");
        item.textContent = ticker;
        return item;
      }),
    );
    overlay.style.display = "flex";
  };
  const cancel = () => clearTimeout(pressTimer);
  const start = (row) => {
    cancel();
    pressTimer = setTimeout(() => show(row), 500);
  };

  rows.forEach((row) => {
    row.addEventListener("contextmenu", (event) => event.preventDefault());
    row.addEventListener("mousedown", () => start(row));
    row.addEventListener("mouseup", cancel);
    row.addEventListener("mouseleave", cancel);
    row.addEventListener("touchstart", () => start(row), { passive: true });
    row.addEventListener("touchend", cancel);
    row.addEventListener("touchmove", cancel);
  });

  closeBtn.addEventListener("click", close);
  overlay.addEventListener("click", (event) => {
    if (!dialog.contains(event.target)) close();
  });
}

export function initMemoAutocomplete() {
  const memoInputs = [
    document.getElementById("expense-memo"),
    document.getElementById("new-expense-memo"),
  ];

  memoInputs.forEach((input) => {
    if (!input) return;

    let isComposing = false;

    const updateList = (el) => {
      if (isComposing) return;
      if (el.value.length >= 2) {
        if (el.getAttribute("list") !== "memo-list") {
          el.setAttribute("list", "memo-list");
        }
      } else {
        if (el.hasAttribute("list")) {
          el.removeAttribute("list");
        }
      }
    };

    input.addEventListener("compositionstart", () => {
      isComposing = true;
    });

    input.addEventListener("compositionend", function() {
      isComposing = false;
      updateList(this);
    });

    input.addEventListener("input", function() {
      updateList(this);
    });
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

export function initAssetMasking() {
  const amountEl = document.getElementById("total-asset-amount");
  if (!amountEl) return;

  const originalValue = amountEl.dataset.originalValue;
  // 数字のみを1文字ずつspanで囲み、伏せ字にする
  const maskedValue = originalValue.replace(
    /\d/g,
    '<span class="digit-span">*</span>',
  );
  // 元の値も、文字幅を揃えるために同じ構造にする（数字をspanで囲む）
  const formattedOriginal = originalValue.replace(
    /\d/g,
    (d) => `<span class="digit-span">${d}</span>`,
  );

  let isMasked = localStorage.getItem("isAssetMasked") === "true";
  amountEl.innerHTML = isMasked ? maskedValue : formattedOriginal;

  // 初期ロード時のちらつき防止用クラスを削除
  if (isMasked) {
    document.documentElement.classList.remove("asset-masked");
  }

  amountEl.addEventListener("click", () => {
    isMasked = !isMasked;
    amountEl.innerHTML = isMasked ? maskedValue : formattedOriginal;
    localStorage.setItem("isAssetMasked", isMasked);
  });
}

export function initChartReloadUI() {
  // Chart reload UI initialization hook
}
