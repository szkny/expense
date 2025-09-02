const typeSelect = document.getElementById("expense-type");
const amountInput = document.getElementById("expense-amount");
const memoInput = document.getElementById("expense-memo");
typeSelect.addEventListener("change", function() {
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
const sectionTable = document.getElementById("table-section");
const toggleBtnTable = document.getElementById("table-toggle");
const recordsContainer = document.getElementById("records-container");
// ページ読み込み時に前回の折りたたみ状態を復元
const collapsed = localStorage.getItem("recordsCollapsed") === "true";
if (collapsed) {
  recordsContainer.style.display = "none";
  toggleBtnTable.textContent = "▲";
}
sectionTable.addEventListener("click", () => {
  const isCollapsed = recordsContainer.style.display === "none";
  if (isCollapsed) {
    recordsContainer.style.display = "block";
    toggleBtnTable.textContent = "▼";
    localStorage.setItem("recordsCollapsed", "false");
  } else {
    recordsContainer.style.display = "none";
    toggleBtnTable.textContent = "▲";
    localStorage.setItem("recordsCollapsed", "true");
  }
});

// ファジーマッチによる検索
function fuzzyMatch(pattern, text) {
  pattern = pattern.toLowerCase();
  text = text.toLowerCase();
  let patternIdx = 0;
  let textIdx = 0;
  let score = 0;
  while (patternIdx < pattern.length && textIdx < text.length) {
    if (pattern[patternIdx] === text[textIdx]) {
      score += 1;
      patternIdx++;
    }
    textIdx++;
  }
  return patternIdx === pattern.length ? score : 0;
}
// 検索入力に応じてテーブルをフィルタリング
function filterTable() {
  const input = document.getElementById("search-input").value.trim();
  const table = document.querySelector("table tbody");
  const rows = table.getElementsByTagName("tr");
  let total = 0;
  let n_match = 0;
  for (let i = 0; i < rows.length; i++) {
    const cells = rows[i].getElementsByTagName("td");
    if (cells.length < 4) continue;
    const expenseType = cells[1].textContent || "";
    const memo = cells[3].textContent || "";
    const text = expenseType + " " + memo;
    const score = fuzzyMatch(input, text);
    if (!input || score > 0) {
      rows[i].style.display = "";
      // 金額を数値化して加算
      const amountText = cells[2].textContent.replace(/[^\d]/g, "");
      total += parseInt(amountText, 10) || 0;
      n_match += 1;
    } else {
      rows[i].style.display = "none";
    }
  }
  // 合計を表示
  totalAmount = document.getElementById("total-amount");
  if (input && total) {
    totalAmount.textContent = `合計: ¥${total.toLocaleString()}  (${n_match}件)`;
    totalAmount.hidden = false;
  } else {
    totalAmount.textContent = "";
    totalAmount.hidden = true;
  }
  document.getElementById("clear-search").style.display = "block";
}
// 検索入力窓をクリア
document.getElementById("clear-search").addEventListener("click", () => {
  const input = document.getElementById("search-input");
  input.value = "";
  filterTable();
  document.getElementById("clear-search").style.display = "none";
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
