// src/expense/static/js/main.js
import { initializeCharts } from "./chart.js";
import { initializeTableFilter } from "./table.js";
import { initSimulator } from "./simulator.js";
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
}

function initAssetAdvisor() {
  const card = document.querySelector('[data-card-key="asset-advice"]');
  const status = document.getElementById("asset-advice-status");
  const content = document.getElementById("asset-advice-content");
  const retryButton = document.getElementById("asset-advice-retry");
  if (!card || !status || !content || !retryButton) return;

  let loading = false;
  const loadAdvice = async () => {
    if (loading) return;
    loading = true;
    retryButton.hidden = true;
    status.textContent = "資産データをもとにアドバイスを生成しています...";
    try {
      const response = await fetch("/api/asset_advice", { method: "POST" });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error || `HTTP ${response.status}`);
      content.textContent = result.advice;
      content.hidden = false;
      status.textContent = result.cached
        ? "本日生成済みのアドバイスです。"
        : "本日のアドバイスです。";
    } catch (error) {
      status.textContent = error.message;
      retryButton.hidden = false;
    } finally {
      loading = false;
    }
  };

  retryButton.addEventListener("click", loadAdvice);
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
