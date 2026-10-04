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
        ? "/api/asset_advice/stream?force=true"
        : "/api/asset_advice/stream";
      const response = await fetch(endpoint, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (!response.body) throw new Error("ストリームを受信できません。");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (!completed) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const eventText of events) {
          const dataLine = eventText
            .split("\n")
            .find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const result = JSON.parse(dataLine.slice(6));
          if (result.error) throw new Error(result.error);
          content.innerHTML = result.advice_html;
          content.hidden = false;
          status.textContent = result.done
            ? result.cached
              ? "生成済みの分析結果を再提示しています。"
              : "今日の分析結果です。"
            : "資産データをもとに分析中...";
          completed = result.done;
        }
        if (done) break;
      }
      if (!completed) throw new Error("分析結果の受信が途中で終了しました。");
      retryButton.hidden = false;
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
