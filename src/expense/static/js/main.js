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

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", onDOMContentLoaded);
} else {
  onDOMContentLoaded();
}
