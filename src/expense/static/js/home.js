const container = document.getElementById("home-content");
const registerTrigger = document.querySelector(
  '.collapsible-trigger[data-key="register"]',
);
let syncStatusTimer;

if (registerTrigger) {
  const registerContainer = document.getElementById("register-container");
  registerTrigger.dataset.collapsibleInitialized = "true";
  registerTrigger.setAttribute(
    "aria-expanded",
    String(document.documentElement.classList.contains("register-open")),
  );
  registerTrigger.addEventListener("click", () => {
    const collapsed =
      !document.documentElement.classList.contains("register-collapsed");
    document.documentElement.classList.toggle("register-collapsed", collapsed);
    document.documentElement.classList.toggle("register-open", !collapsed);
    registerContainer?.classList.toggle("is-open", !collapsed);
    registerTrigger.setAttribute("aria-expanded", String(!collapsed));
    try {
      localStorage.setItem("registerCollapsed", String(collapsed));
    } catch {
      // The input section remains usable when storage is unavailable.
    }
  });
}

async function loadHomeContent() {
  try {
    const response = await fetch("/api/home");
    if (!response.ok) throw new Error("家計簿データを取得できませんでした。");

    const html = await response.text();
    const documentFragment = new DOMParser().parseFromString(html, "text/html");
    const content = documentFragment.getElementById("home-content");
    if (!container || !content) throw new Error("家計簿画面を表示できません。");

    const currentTypeSelect = document.getElementById("expense-type");
    const loadedTypeSelect = documentFragment.getElementById("expense-type");
    if (currentTypeSelect && loadedTypeSelect) {
      const selectedType = currentTypeSelect.value;
      const wasFocused = document.activeElement === currentTypeSelect;
      currentTypeSelect.replaceChildren(
        ...Array.from(loadedTypeSelect.options, (option) =>
          option.cloneNode(true),
        ),
      );
      if (
        Array.from(currentTypeSelect.options).some(
          (option) => option.value === selectedType,
        )
      ) {
        currentTypeSelect.value = selectedType;
      }
      if (wasFocused) currentTypeSelect.focus({ preventScroll: true });
    }

    const registerCard = container.querySelector('[data-card-key="register"]');
    const loadedCards = Array.from(content.children).filter(
      (card) => card.dataset.cardKey !== "register",
    );
    container.replaceChildren(registerCard, ...loadedCards);
    try {
      await import("./main.js");
    } catch (error) {
      console.error("Failed to initialize the home page:", error);
    }
    loadSpreadsheetUrl();
    startSyncStatusPolling();
  } catch (error) {
    if (container) {
      const card = document.createElement("div");
      card.className = "card";
      const message = document.createElement("p");
      message.textContent = error.message;
      const reloadButton = document.createElement("button");
      reloadButton.type = "button";
      reloadButton.className = "btn";
      reloadButton.textContent = "再読み込み";
      reloadButton.addEventListener("click", () => location.reload());
      card.append(message, reloadButton);
      const registerCard = container.querySelector(
        '[data-card-key="register"]',
      );
      if (registerCard) {
        container.replaceChildren(registerCard, card);
      } else {
        container.replaceChildren(card);
      }
    }
  }
}

function startSyncStatusPolling() {
  if (syncStatusTimer) return;
  const retryButton = document.getElementById("retry-sheets-sync");
  retryButton?.addEventListener("click", async () => {
    retryButton.disabled = true;
    try {
      await fetch("/api/sync/retry", { method: "POST" });
      await refreshSyncStatus();
    } finally {
      retryButton.disabled = false;
    }
  });
  refreshSyncStatus();
  syncStatusTimer = setInterval(refreshSyncStatus, 3000);
}

async function refreshSyncStatus() {
  try {
    const response = await fetch("/api/sync/status", { cache: "no-store" });
    if (!response.ok) return;
    const overview = await response.json();
    const counts = overview.counts || {};
    const retrying = counts.retrying || 0;
    const syncing = counts.syncing || 0;
    const pending = counts.pending || 0;
    const summary = document.getElementById("sheets-sync-status");
    const label = document.getElementById("sheets-sync-label");
    const retryButton = document.getElementById("retry-sheets-sync");

    if (retrying) {
      if (label)
        label.textContent = `Sheets同期エラー。自動で再試行します（${retrying}件）`;
      if (summary) summary.dataset.state = "retrying";
    } else if (syncing) {
      if (label) label.textContent = `Sheets同期中（${syncing}件）`;
      if (summary) summary.dataset.state = "syncing";
    } else if (pending) {
      if (label) label.textContent = `Sheets同期待ち（${pending}件）`;
      if (summary) summary.dataset.state = "pending";
    } else {
      if (label) label.textContent = "Sheets同期済み";
      if (summary) summary.dataset.state = "synced";
    }
    if (retryButton) retryButton.hidden = retrying === 0;

    for (const row of document.querySelectorAll("tr[data-record-id]")) {
      const state = overview.records?.[row.dataset.recordId];
      if (!state) continue;
      row.dataset.syncStatus = state.status;
      const indicator = row.querySelector(".sync-indicator");
      if (!indicator) continue;
      const stateLabel =
        {
          pending: "Sheets同期待ち",
          syncing: "Sheets同期中",
          retrying: "Sheets同期に失敗し再試行中",
          synced: "Sheets同期済み",
        }[state.status] || "Sheets同期状態不明";
      indicator.setAttribute("aria-label", stateLabel);
      indicator.title = stateLabel;
    }
  } catch {
    // The page remains usable if the sync status endpoint is unavailable.
  }
}

async function loadSpreadsheetUrl() {
  try {
    const response = await fetch("/api/spreadsheet_url");
    if (!response.ok) return;
    const { url } = await response.json();
    const link = document.getElementById("spreadsheet-link");
    if (link && typeof url === "string" && url) {
      link.href = url;
      link.hidden = false;
    }
  } catch {
    // Spreadsheet navigation is optional for rendering the page.
  }
}

loadHomeContent();
