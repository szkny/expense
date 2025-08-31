const typeSelect = document.getElementById("expense-type");
const amountInput = document.getElementById("expense-amount");
const memoInput = document.getElementById("expense-memo");
typeSelect.addEventListener("change", function () {
  if (this.value.includes("/")) {
    amountInput.style.display = "none";
    memoInput.style.display = "none";
    amountInput.required = false;
  } else {
    amountInput.style.display = "block";
    memoInput.style.display = "block";
    amountInput.required = true;
  }
});

// テーマ切り替え処理
const toggleBtnTheme = document.getElementById("theme-toggle");
const body = document.body;

// ページ読み込み時に前回の設定を反映
if (localStorage.getItem("theme") === "dark") {
  body.classList.add("dark");
  toggleBtnTheme.textContent = "☀️";
}

toggleBtnTheme.addEventListener("click", () => {
  body.classList.toggle("dark");
  const isDark = body.classList.contains("dark");
  toggleBtnTheme.textContent = isDark ? "☀️" : "🌙";
  localStorage.setItem("theme", isDark ? "dark" : "light");
});

// テーブルの折りたたみ処理
const toggleBtnTable = document.getElementById("table-toggle");
const recordsContainer = document.getElementById("records-container");
// ページ読み込み時に前回の折りたたみ状態を復元
const collapsed = localStorage.getItem("recordsCollapsed") === "true";
if (collapsed) {
  recordsContainer.style.display = "none";
  toggleBtnTable.textContent = "▲ テーブルを非表示";
}
toggleBtnTable.addEventListener("click", () => {
  const isCollapsed = recordsContainer.style.display === "none";
  if (isCollapsed) {
    recordsContainer.style.display = "block";
    toggleBtnTable.textContent = "▼ テーブルを表示";
    localStorage.setItem("recordsCollapsed", "false");
  } else {
    recordsContainer.style.display = "none";
    toggleBtnTable.textContent = "▲ テーブルを非表示";
    localStorage.setItem("recordsCollapsed", "true");
  }
});

// Service Worker 登録
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/static/service-worker.js");
}
// インストールイベント処理
let deferredPrompt;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  document.getElementById("install-btn").style.display = "block";
});
document.getElementById("install-btn").addEventListener("click", () => {
  deferredPrompt.prompt();
  deferredPrompt.userChoice.then(() => (deferredPrompt = null));
});
