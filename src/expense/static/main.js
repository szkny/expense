// ハンバーガーメニュー
(function() {
  const menuBtn = document.getElementById("hamburger-menu-btn");
  const menu = document.getElementById("menu-container");
  if (menuBtn && menu) {
    const themeBtn = document.getElementById("theme-toggle");
    const assetBtn = document.getElementById("asset-management-btn");
    const homeBtn = document.getElementById("home-btn");
    function closeMenu() {
      menu.classList.remove("show");
      menuBtn.classList.remove("clicked");
      menuBtn.textContent = "☰";
    }
    if (themeBtn) themeBtn.addEventListener("click", closeMenu);
    if (assetBtn) assetBtn.addEventListener("click", closeMenu);
    if (homeBtn) homeBtn.addEventListener("click", closeMenu);
    menuBtn.addEventListener("click", () => {
      menu.classList.toggle("show");
      menuBtn.classList.toggle("clicked");
      menuBtn.textContent = menuBtn.textContent == "✕" ? "☰" : "✕";
    });
    // メニューの外側をクリックしたら閉じる
    document.addEventListener("click", (e) => {
      if (!menu.contains(e.target) && !menuBtn.contains(e.target)) {
        menu.classList.remove("show");
        menuBtn.classList.remove("clicked");
        menuBtn.textContent = "☰";
      }
    });
  }
})();

// メッセージの閉じるボタン
(function() {
  const closeBtn = document.getElementById("msg-close-btn");
  const msg1 = document.getElementById("success-msg");
  const msg2 = document.getElementById("failed-msg");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      msg1.style.display = "none";
      msg2.style.display = "none";
    });
  }
})();

// 経費タイプ選択に応じた入力欄の表示・非表示
(function() {
  const typeSelect = document.getElementById("expense-type");
  if (typeSelect) {
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
  }
})();

// フォーム送信時にローディング表示
(function() {
  const forms = document.querySelectorAll("form");
  const loader = document.getElementById("loader");
  if (forms.length > 0 && loader) {
    forms.forEach((form) => {
      form.addEventListener("submit", () => {
        loader.style.display = "flex";
      });
    });
  }
})();

// テーマ切り替え処理
(function() {
  const themeToggle = document.getElementById("theme-toggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const isDark = document.documentElement.classList.toggle("dark");
      const newTheme = isDark ? "dark" : "light";
      localStorage.setItem("theme", newTheme);
      document.cookie = `theme=${newTheme};path=/;max-age=31536000`;
      location.reload();
    });
  }
})();

// スクショの拡大・縮小動作
(function() {
  const screenshot = document.getElementById("screenshot");
  const overlay = document.getElementById("img-overlay");
  if (screenshot && overlay) {
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
})();

// 折りたたみ処理
(function() {
  const onOpenCallbacks = {
    report: () => {
      requestAnimationFrame(() => {
        const graphs = document.querySelectorAll(".plotly-graph-div");
        graphs.forEach((g) => Plotly.Plots.resize(g));
      });
    },
    "asset-report": () => {
      requestAnimationFrame(() => {
        const graphs = document.querySelectorAll(".plotly-graph-div");
        graphs.forEach((g) => Plotly.Plots.resize(g));
      });
    },
  };

  document.querySelectorAll(".collapsible-trigger").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const key = trigger.dataset.key;
      if (!key) return;

      const openClass = key + "-open";
      const collapsedClass = key + "-collapsed";
      const localVarId = key + "Collapsed";
      const isCollapsed =
        document.documentElement.classList.contains(collapsedClass);

      if (isCollapsed) {
        // 開く
        document.documentElement.classList.remove(collapsedClass);
        document.documentElement.classList.add(openClass);
        localStorage.setItem(localVarId, "false");
        if (onOpenCallbacks[key]) {
          onOpenCallbacks[key]();
        }
      } else {
        // 閉じる
        document.documentElement.classList.remove(openClass);
        document.documentElement.classList.add(collapsedClass);
        localStorage.setItem(localVarId, "true");
      }
    });
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
  const inputElement = document.getElementById("search-input");
  if (!inputElement) return;
  const input = inputElement.value.trim();
  const table = document.querySelector("table tbody");
  if (!table) return;
  const rows = table.getElementsByTagName("tr");
  let total = 0;
  let n_match = 0;
  // ヘッダーをチェックしてテーブルの種類を判別
  const headers = Array.from(document.querySelectorAll("thead th")).map(
    (th) => th.textContent,
  );
  const isAssetTable = headers.includes("銘柄");
  for (let i = 0; i < rows.length; i++) {
    const cells = rows[i].getElementsByTagName("td");
    let text = "";
    if (isAssetTable) {
      // 資産テーブルの場合：銘柄(1列目)を検索対象にする
      if (cells.length > 0) {
        text = cells[0].textContent || "";
      }
    } else {
      // 経費テーブルの場合
      if (cells.length < 4) continue;
      const date = cells[0].textContent || "";
      const expenseType = cells[1].textContent || "";
      const memo = cells[3].textContent || "";
      text = date + " " + expenseType + " " + memo;
    }
    const score = fuzzyMatch(input, text);
    if (!input || score > 0) {
      rows[i].style.display = "";
      if (!isAssetTable) {
        // 経費テーブルの場合のみ合計金額を計算
        const amountText = cells[2].textContent.replace(/[^\d]/g, "");
        total += parseInt(amountText, 10) || 0;
        n_match += 1;
      }
    } else {
      rows[i].style.display = "none";
    }
  }
  // 合計金額の表示は経費テーブルの場合のみ
  if (!isAssetTable) {
    const totalAmount = document.getElementById("total-amount");
    if (totalAmount) {
      if (input && total) {
        totalAmount.textContent = `合計: ¥${total.toLocaleString()}  (${n_match}件)`;
        totalAmount.style.display = "block";
      } else {
        totalAmount.textContent = "";
        totalAmount.style.display = "none";
      }
    }
  }
  const clearButton = document.getElementById("clear-search");
  if (clearButton) {
    clearButton.style.display = input ? "block" : "none";
  }
}

// 検索入力窓をクリア
(function() {
  const clearButton = document.getElementById("clear-search");
  if (clearButton) {
    clearButton.addEventListener("click", () => {
      const input = document.getElementById("search-input");
      if (input) {
        input.value = "";
        filterTable();
        clearButton.style.display = "none";
      }
    });
  }
})();

// レコード長押し処理
(function() {
  document.addEventListener("DOMContentLoaded", () => {
    const overlay = document.getElementById("confirmation-overlay");
    if (!overlay) return; // このページに機能がなければ何もしない
    const dialog = document.getElementById("confirmation-dialog");
    const deleteDate = document.getElementById("delete-record-date");
    const deleteType = document.getElementById("delete-record-type");
    const deleteAmount = document.getElementById("delete-record-amount");
    const deleteMemo = document.getElementById("delete-record-memo");
    const targetDate = document.getElementById("target-record-date");
    const targetType = document.getElementById("target-record-type");
    const targetAmount = document.getElementById("target-record-amount");
    const targetMemo = document.getElementById("target-record-memo");
    const newDate = document.getElementById("new-expense-date");
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
      newDate.value = date.replace(/\([月火水木金土日]\)/, "");
      newType.value = type;
      newAmount.value = amount;
      newMemo.value = memo;
      overlay.style.display = "flex";
    }

    // 各行に長押しイベントを登録
    let pressTimer;
    const longPressTime = 500;
    document.querySelectorAll("tbody tr").forEach((row) => {
      // 右クリック / 長押しメニューを無効化
      row.addEventListener("contextmenu", (e) => {
        e.preventDefault();
      });
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
    const closeBtn = document.getElementById("confirmation-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        overlay.style.display = "none";
      });
    }

    // オーバーレイをクリックしたら閉じる
    overlay.addEventListener("click", function(e) {
      // クリック対象がダイアログ自身ではない場合のみ閉じる
      if (dialog && !dialog.contains(e.target)) {
        overlay.style.display = "none";
      }
    });
  });
})();

// PWA インストール処理
(function() {
  const installBtn = document.getElementById("install-btn");
  if (installBtn) {
    // Service Worker 登録
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/static/service-worker.js");
    }
    // インストールイベント処理
    let deferredPrompt;
    window.addEventListener("beforeinstallprompt", (e) => {
      e.preventDefault();
      deferredPrompt = e;
      installBtn.style.display = "block";
    });
    installBtn.addEventListener("click", () => {
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(() => (deferredPrompt = null));
    });
  }
})();

// グラフの非同期読み込み処理
(function() {
  const reportContainer = document.getElementById("report-container");
  const assetReportContainer = document.getElementById(
    "asset-report-container",
  );

  if (!reportContainer && !assetReportContainer) return;

  const allChartConfigs = {
    report: [
      { id: "pie", endpoint: "/api/pie_chart", hasDropdown: true },
      { id: "daily", endpoint: "/api/daily_chart", hasDropdown: true },
      { id: "bar", endpoint: "/api/bar_chart", hasDropdown: false },
    ],
    asset: [
      { id: "asset-pie", endpoint: "/api/asset_pie_chart", hasDropdown: false },
      {
        id: "asset-waterfall",
        endpoint: "/api/asset_waterfall_chart",
        hasDropdown: false,
      },
    ],
  };

  const fetchAndRenderChart = async (config, month = null) => {
    const container = document.getElementById(`${config.id}-chart-container`);
    if (!container || (container.dataset.loaded && !month)) return;

    container.classList.add("loading");
    container.innerHTML = '<div class="spinner"></div>';

    let url = config.endpoint;
    if (month) {
      url += `?month=${month}`;
    }

    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Network response was not ok");

      if (config.hasDropdown) {
        const data = await response.json();
        if (data.html) {
          container.innerHTML = data.html;
          if (!month) {
            createDropdown(config, data.months);
          }
        } else {
          container.innerHTML = "";
        }
      } else {
        const html = await response.text();
        if (html) {
          container.innerHTML = html;
        }
      }

      container.dataset.loaded = "true";
      container.classList.remove("loading");
      const scripts = container.getElementsByTagName("script");
      for (let i = 0; i < scripts.length; i++) {
        new Function(scripts[i].innerHTML)();
      }
    } catch (error) {
      container.innerHTML = "<p>Error loading graph.</p>";
      console.error("Fetch error for " + url + ":", error);
    }
  };

  const createDropdown = (config, months) => {
    const controlsContainer = document.getElementById(
      `${config.id}-chart-controls`,
    );
    if (!controlsContainer || months.length === 0) return;

    const select = document.createElement("select");
    select.id = `${config.id}-month-select`;

    const currentMonth = months[0];
    months.forEach((month) => {
      const option = document.createElement("option");
      option.value = month;
      option.textContent = month.replace("-", "年") + "月";
      if (month === currentMonth) {
        option.selected = true;
      }
      select.appendChild(option);
    });

    select.addEventListener("change", (e) => {
      fetchAndRenderChart(config, e.target.value);
    });

    controlsContainer.innerHTML = "";
    controlsContainer.appendChild(select);
  };

  if (reportContainer) {
    allChartConfigs.report.forEach((config) => fetchAndRenderChart(config));
  }

  if (assetReportContainer) {
    const initAssetChart = () => {
      allChartConfigs.asset.forEach((config) => fetchAndRenderChart(config));
    };

    const trigger = document.querySelector("[data-key='asset-report']");
    const isCollapsed = document.documentElement.classList.contains(
      "asset-report-collapsed",
    );

    if (!isCollapsed) {
      initAssetChart();
    }
    if (trigger) {
      trigger.addEventListener("click", initAssetChart);
    }
  }
})();
