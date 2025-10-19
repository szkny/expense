// src/expense/static/js/main.js
import { initializeCharts } from './chart.js';
import { initializeTableFilter } from './table.js';
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
} from './ui.js';

function onDOMContentLoaded() {
  initializeCharts();
  initializeTableFilter();
  initMenu();
  initClosableMessages();
  initExpenseForm();
  initFormLoaders();
  initThemeToggle();
  initScreenshotZoom();
  initCollapsibleSections();
  initRecordEditor();
  initPwaInstall();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', onDOMContentLoaded);
} else {
  onDOMContentLoaded();
}
