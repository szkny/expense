// src/expense/static/js/main.js
import { initializeCharts } from "./chart.js";
import { initializeTableFilter } from "./table.js";
import { initSimulator } from "./simulator.js";
import { initNotifications } from "./notifications.js";
import {
  initMenu,
  initClosableMessages,
  initExpenseForm,
  initFormLoaders,
  initThemeToggle,
  initScreenshotZoom,
  initOcrReload,
  initCollapsibleSections,
  initRecordEditor,
  initPwaInstall,
  initAssetMasking,
  initMemoAutocomplete,
  initChartReloadUI,
  initAssetAllocationLongPress,
  initCardReordering,
} from "./ui.js";

function onDOMContentLoaded() {
  initCardReordering();
  initAssetAdvisor();
  initCollapsibleSections();
  initializeCharts();
  initChartReloadUI();
  initializeTableFilter();
  initMenu();
  initClosableMessages();
  initExpenseForm();
  initFormLoaders();
  initThemeToggle();
  initScreenshotZoom();
  initOcrReload();
  initRecordEditor();
  initPwaInstall();
  initAssetMasking();
  initMemoAutocomplete();
  initSimulator();
  initAssetAllocationLongPress();
  initNotifications().catch(() => {
    console.error("Web Push initialization failed");
  });
}

function initAssetAdvisor() {
  const card = document.querySelector('[data-card-key="asset-advice"]');
  const status = document.getElementById("asset-advice-status");
  const content = document.getElementById("asset-advice-content");
  const retryButton = document.getElementById("asset-advice-retry");
  if (!card || !status || !content || !retryButton) return;

  let loading = false;
  const loadAdvice = async (force = false) => {
    if (loading) return;
    loading = true;
    retryButton.hidden = true;
    status.textContent = "資産データをもとに分析中...";
    try {
      const endpoint = force
        ? "/api/asset_advice?force=true"
        : "/api/asset_advice";
      const response = await fetch(endpoint, { method: "POST" });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || `HTTP ${response.status}`);
      content.innerHTML = result.advice_html;
      content.hidden = false;
      retryButton.hidden = false;
      status.textContent = result.cached
        ? "生成済みの分析結果を再提示しています。"
        : "今日の分析結果です。";
    } catch (error) {
      status.textContent = error.message;
      retryButton.hidden = false;
    } finally {
      loading = false;
    }
  };

  retryButton.addEventListener("click", () => loadAdvice(true));
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        loadAdvice();
      },
      { rootMargin: "160px" },
    );
    observer.observe(card);
  } else {
    window.setTimeout(loadAdvice, 0);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", onDOMContentLoaded);
} else {
  onDOMContentLoaded();
}
