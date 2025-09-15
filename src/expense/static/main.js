// 右クリック / 長押しメニューを無効化
document.addEventListener("DOMContentLoaded", () => {
  document.addEventListener("contextmenu", (e) => {
    e.preventDefault();
  });
});

// 経費タイプ選択に応じた入力欄の表示・非表示
(function() {
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
})();

// フォーム送信時にローディング表示
(function() {
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", () => {
      document.getElementById("loader").style.display = "flex";
    });
  });
})();

// テーマ切り替え処理
(function() {
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const isDark = document.documentElement.classList.toggle("dark");
    const newTheme = isDark ? "dark" : "light";
    localStorage.setItem("theme", newTheme);
    document.cookie = `theme=${newTheme};path=/;max-age=31536000`;
    location.reload();
  });
})();

// スクショの拡大・縮小動作
(function() {
  const screenshot = document.getElementById("screenshot");
  const overlay = document.getElementById("img-overlay");
  let isZoomed = false;
  screenshot.addEventListener("click", () => {
    if (isZoomed) {
      screenshot.style.transform = "scale(1)";
      overlay.style.display = "none";
      isZoomed = false;
    } else {
      screenshot.style.transform = "scale(5.5)";
      overlay.style.display = "flex";
      isZoomed = true;
    }
  });
  overlay.addEventListener("click", () => {
    screenshot.style.transform = "scale(1)";
    overlay.style.display = "none";
    isZoomed = false;
  });
})();

// レポートの折りたたみ処理
(function() {
  const sectionReport = document.getElementById("report-section");
  const toggleBtnReport = document.getElementById("report-toggle");
  const reportContainer = document.getElementById("report-container");
  // ページ読み込み時に前回の折りたたみ状態を復元
  const collapsed = localStorage.getItem("reportCollapsed") === "true";
  if (collapsed) {
    reportContainer.style.display = "none";
    toggleBtnReport.textContent = "▼";
  }
  sectionReport.addEventListener("click", () => {
    const isCollapsed = reportContainer.style.display === "none";
    if (isCollapsed) {
      reportContainer.style.display = "block";
      toggleBtnReport.textContent = "▲";
      localStorage.setItem("reportCollapsed", "false");
    } else {
      reportContainer.style.display = "none";
      toggleBtnReport.textContent = "▼";
      localStorage.setItem("reportCollapsed", "true");
    }
  });
})();

// テーブルの折りたたみ処理
(function() {
  const sectionTable = document.getElementById("table-section");
  const toggleBtnTable = document.getElementById("table-toggle");
  const recordsContainer = document.getElementById("records-container");
  // ページ読み込み時に前回の折りたたみ状態を復元
  const collapsed = localStorage.getItem("recordsCollapsed") === "true";
  if (collapsed) {
    recordsContainer.style.display = "none";
    toggleBtnTable.textContent = "▼";
  }
  sectionTable.addEventListener("click", () => {
    const isCollapsed = recordsContainer.style.display === "none";
    if (isCollapsed) {
      recordsContainer.style.display = "block";
      toggleBtnTable.textContent = "▲";
      localStorage.setItem("recordsCollapsed", "false");
    } else {
      recordsContainer.style.display = "none";
      toggleBtnTable.textContent = "▼";
      localStorage.setItem("recordsCollapsed", "true");
    }
  });
})();

// カタカナ -> ひらがな
const HIRAGANA_START = "ぁ".charCodeAt(0);
const KATAKANA_START = "ァ".charCodeAt(0);
const KATAKANA_END = "ヶ".charCodeAt(0);
const OFFSET = KATAKANA_START - HIRAGANA_START;
function katakanaToHiragana(str) {
  return str
    .split("")
    .map((ch) => {
      const code = ch.charCodeAt(0);
      if (code >= KATAKANA_START && code <= KATAKANA_END) {
        return String.fromCharCode(code - OFFSET);
      }
      return ch;
    })
    .join("");
}
// ファジーマッチによる検索
function fuzzyMatch(pattern, text) {
  pattern = katakanaToHiragana(pattern.toLowerCase());
  text = katakanaToHiragana(text.toLowerCase());
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
    const date = cells[0].textContent || "";
    const expenseType = cells[1].textContent || "";
    const memo = cells[3].textContent || "";
    const text = date + " " + expenseType + " " + memo;
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
    totalAmount.style.display = "block";
  } else {
    totalAmount.textContent = "";
    totalAmount.style.display = "none";
  }
  document.getElementById("clear-search").style.display = "block";
}

// 検索入力窓をクリア
(function() {
  document.getElementById("clear-search").addEventListener("click", () => {
    const input = document.getElementById("search-input");
    input.value = "";
    filterTable();
    document.getElementById("clear-search").style.display = "none";
  });
})();

// レコード長押し処理
(function() {
  document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.getElementById("confirmation-overlay");
    const dialog = document.getElementById("confirmation-dialog");
    const deleteDate = document.getElementById("delete-record-date");
    const deleteType = document.getElementById("delete-record-type");
    const deleteAmount = document.getElementById("delete-record-amount");
    const deleteMemo = document.getElementById("delete-record-memo");
    const targetDate = document.getElementById("target-record-date");
    const targetType = document.getElementById("target-record-type");
    const targetAmount = document.getElementById("target-record-amount");
    const targetMemo = document.getElementById("target-record-memo");
    const showDate = document.getElementById("show-record-date");
    const newType = document.getElementById("new-expense-type");
    const newAmount = document.getElementById("new-expense-amount");
    const newMemo = document.getElementById("new-expense-memo");

    // Overlay表示処理
    function showOverlay(row) {
      const date = row.children[0].textContent;
      const type = row.children[1].textContent;
      const amount = row.children[2].textContent;
      const memo = row.children[3].textContent;
      deleteDate.value = date;
      deleteType.value = type;
      deleteAmount.value = amount;
      deleteMemo.value = memo;
      targetDate.value = date;
      targetType.value = type;
      targetAmount.value = amount;
      targetMemo.value = memo;
      showDate.value = date;
      newType.value = type;
      newAmount.value = amount;
      newMemo.value = memo;
      overlay.style.display = "flex";
    }

    // 各行に長押しイベントを登録
    let pressTimer;
    const longPressTime = 500;
    document.querySelectorAll("tbody tr").forEach((row) => {
      // PC用（マウス押しっぱなし）
      row.addEventListener("mousedown", (_) => {
        pressTimer = setTimeout(() => showOverlay(row), longPressTime);
      });
      row.addEventListener("mouseup", () => clearTimeout(pressTimer));
      row.addEventListener("mouseleave", () => clearTimeout(pressTimer));
      // スマホ用（タッチ押しっぱなし）
      row.addEventListener("touchstart", () => {
        pressTimer = setTimeout(() => showOverlay(row), longPressTime);
      });
      row.addEventListener("touchend", () => clearTimeout(pressTimer));
      row.addEventListener("touchmove", () => clearTimeout(pressTimer));
    });

    // 閉じるボタンをクリックして確認ダイアログを閉じる
    document
      .getElementById("confirmation-close-btn")
      .addEventListener("click", () => {
        overlay.style.display = "none";
      });

    // オーバーレイをクリックしたら閉じる
    overlay.addEventListener("click", function(e) {
      // クリック対象がダイアログ自身ではない場合のみ閉じる
      if (!dialog.contains(e.target)) {
        overlay.style.display = "none";
      }
    });
  });
})();

// PWA インストール処理
(function() {
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
})();
