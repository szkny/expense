// src/expense/static/js/main.js
import { initializeCharts } from "./chart.js";
import { initializeTableFilter } from "./table.js";
import {
  initMenu,
  initClosableMessages,
  initExpenseForm,
  initFormLoaders,
  initThemeToggle,
  initScreenshotZoom,
  initCollapsibleSections,
  initRecordEditor,
  initPwaInstall,
  initAssetMasking,
} from "./ui.js";

function onDOMContentLoaded() {
  initCollapsibleSections();
  initializeCharts();
  initializeTableFilter();
  initMenu();
  initClosableMessages();
  initExpenseForm();
  initFormLoaders();
  initThemeToggle();
  initScreenshotZoom();
  initRecordEditor();
  initPwaInstall();
  initAssetMasking();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", onDOMContentLoaded);
} else {
  onDOMContentLoaded();
}
