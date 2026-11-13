// src/expense/static/js/chart.js
import { initAssetMasking } from "./ui.js";

const allChartConfigs = {
  report: [
    {
      id: "pie",
      endpoint: "/api/pie_chart",
      hasDropdown: true,
      optionLabel: (month) =>
        month === "average" ? "月平均" : month.replace("-", "年") + "月",
    },
    { id: "daily", endpoint: "/api/daily_chart", hasDropdown: true },
    { id: "bar", endpoint: "/api/bar_chart", hasDropdown: false },
    {
      id: "annual-fiscal-report",
      endpoint: "/api/annual_fiscal_report_chart",
      hasDropdown: true,
      dateParam: "year",
      optionLabel: (year) => `${year}年度`,
    },
    {
      id: "annual-fiscal-sankey",
      endpoint: "/api/annual_fiscal_sankey_chart",
      hasDropdown: true,
      dateParam: "year",
      optionLabel: (year) => `${year}年度`,
    },
    {
      id: "fiscal-asset-history",
      endpoint: "/api/fiscal_asset_history_chart",
      hasDropdown: true,
      dateParam: "year",
      defaultParams: () => ({ year: getCurrentFiscalYear() }),
      optionLabel: (year) => `${year}年度`,
    },
  ],
  asset: [
    { id: "asset-pie", endpoint: "/api/asset_pie_chart", hasDropdown: false },
    {
      id: "asset-heatmap",
      endpoint: "/api/asset_heatmap_chart",
      hasDropdown: false,
    },
    {
      id: "asset-recently-history",
      endpoint: "/api/asset_recently_history_chart",
      hasDropdown: false,
    },
    {
      id: "asset-waterfall",
      endpoint: "/api/asset_waterfall_chart",
      hasDropdown: false,
    },
    {
      id: "asset-monthly-history",
      endpoint: "/api/asset_monthly_history_chart",
      hasDropdown: false,
    },
    {
      id: "asset-profit-history",
      endpoint: "/api/asset_profit_history_chart",
      hasDropdown: false,
    },
    {
      id: "asset-drawdown-history",
      endpoint: "/api/asset_drawdown_history_chart",
      hasDropdown: false,
    },
  ],
};

const CHART_CACHE_PREFIX = "expense:chart:";
const CHART_CACHE_TTL = 30 * 24 * 60 * 60 * 1000;
let plotlyLoadPromise;

function ensurePlotlyLoaded() {
  if (window.Plotly) return Promise.resolve();
  if (!plotlyLoadPromise) {
    plotlyLoadPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      const version = document.body.dataset.plotlyVersion || "1";
      script.src = `/plotly.js?v=${encodeURIComponent(version)}`;
      script.onload = resolve;
      script.onerror = () => reject(new Error("Failed to load Plotly.js"));
      document.head.appendChild(script);
    });
  }
  return plotlyLoadPromise;
}

function getCurrentFiscalYear() {
  const today = new Date();
  return String(today.getFullYear() - (today.getMonth() + 1 < 4 ? 1 : 0));
}

function getReloadIcon() {
  return document.body?.dataset?.reloadIcon || "↻";
}

function createReloadButton(onClickHandler) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn-reload";
  btn.title = "グラフをリロード";
  btn.innerHTML = getReloadIcon();
  btn.addEventListener("click", onClickHandler);
  return btn;
}

function renderChartPlaceholder(container) {
  container.replaceChildren();
  const placeholder = document.createElement("p");
  placeholder.className = "chart-placeholder";
  placeholder.textContent = "表示するデータがありません";
  container.appendChild(placeholder);
}

function getChartCacheKey(config) {
  const theme = document.documentElement.classList.contains("dark")
    ? "dark"
    : "light";
  return `${CHART_CACHE_PREFIX}v2:${location.pathname}:${theme}:${config.id}`;
}

function cleanupExpiredChartCaches() {
  try {
    const now = Date.now();
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(CHART_CACHE_PREFIX)) continue;

      try {
        const cached = JSON.parse(localStorage.getItem(key) || "null");
        const age = now - cached?.savedAt;
        if (!Number.isFinite(age) || age < 0 || age > CHART_CACHE_TTL) {
          localStorage.removeItem(key);
        }
      } catch {
        localStorage.removeItem(key);
      }
    }
  } catch {
    // Graph rendering must continue when browser storage is unavailable.
  }
}

function readCachedChart(config) {
  try {
    const cached = JSON.parse(
      localStorage.getItem(getChartCacheKey(config)) || "null",
    );
    const age = Date.now() - cached?.savedAt;
    if (
      !cached ||
      !Number.isFinite(age) ||
      age < 0 ||
      age > CHART_CACHE_TTL ||
      typeof cached.html !== "string" ||
      !Array.isArray(cached.options) ||
      !cached.params ||
      typeof cached.params !== "object"
    ) {
      return null;
    }
    return cached;
  } catch {
    return null;
  }
}

function saveChartCache(config, html, options, params) {
  const savedAt = Date.now();
  try {
    localStorage.setItem(
      getChartCacheKey(config),
      JSON.stringify({ html, options, params, savedAt }),
    );
  } catch {
    // A full or unavailable local store must not interrupt graph rendering.
  }
  return savedAt;
}

function showCachedChartStatus(container, savedAt) {
  container.querySelector(".chart-cache-status")?.remove();
  const status = document.createElement("p");
  status.className = "chart-cache-status";
  status.setAttribute("role", "status");
  status.textContent = `更新できませんでした。前回のデータを表示しています（${new Date(Number(savedAt)).toLocaleString("ja-JP")}）`;
  container.appendChild(status);
}

function showChartRenderErrorStatus(container) {
  container.querySelector(".chart-cache-status")?.remove();
  const status = document.createElement("p");
  status.className = "chart-cache-status";
  status.setAttribute("role", "status");
  status.textContent = "グラフの描画に失敗しました。再読み込みしてください。";
  container.appendChild(status);
}

function showChartLoadingOverlay(container) {
  const overlay = document.createElement("div");
  overlay.className = "chart-loading-overlay";
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-label", "グラフを更新中");
  overlay.innerHTML = '<div class="spinner"></div>';

  return {
    attach: () => {
      container.classList.add("chart-refreshing");
      container.appendChild(overlay);
    },
    remove: () => {
      container.classList.remove("chart-refreshing");
      overlay.remove();
    },
  };
}

async function runChartScripts(container) {
  const scripts = container.getElementsByTagName("script");
  if (scripts.length > 0) await ensurePlotlyLoaded();
  for (let i = 0; i < scripts.length; i++) {
    new Function(scripts[i].innerHTML)();
  }
}

async function restoreCachedChart(config) {
  const container = document.getElementById(`${config.id}-chart-container`);
  const cached = readCachedChart(config);
  if (!container || !cached) return null;

  if (cached.html) {
    container.innerHTML = cached.html;
  } else {
    renderChartPlaceholder(container);
  }
  container.classList.remove("loading");
  container.dataset.loaded = "true";
  container.dataset.cacheSavedAt = String(cached.savedAt);

  if (config.hasDropdown) {
    const param = config.dateParam || "month";
    setupDropdownAndReload(
      config,
      cached.options,
      cached.params[param] || cached.options[0],
    );
  } else {
    setupReloadButtonOnly(config);
  }

  const loadingOverlay = showChartLoadingOverlay(container);
  loadingOverlay.attach();
  try {
    await runChartScripts(container);
  } catch (error) {
    console.error("Failed to restore cached graph:", config.id, error);
    delete container.dataset.loaded;
    delete container.dataset.cacheSavedAt;
    return null;
  } finally {
    loadingOverlay.remove();
  }
  return cached;
}

async function loadChartWithCache(config, params = {}) {
  const cached = await restoreCachedChart(config);
  const refreshParams =
    cached && Object.keys(params).length === 0 ? cached.params : params;
  await fetchAndRenderChart(config, refreshParams, Boolean(cached));
}

export async function fetchAndRenderChart(config, params = {}, force = false) {
  if (Object.keys(params).length === 0 && config.defaultParams) {
    params = config.defaultParams();
  }
  const container = document.getElementById(`${config.id}-chart-container`);
  if (
    !container ||
    (!force && container.dataset.loaded && Object.keys(params).length === 0)
  )
    return;

  const hasPreviousChart = container.dataset.loaded === "true";
  let chartReplaced = false;
  let loadingOverlay = null;
  if (!hasPreviousChart) {
    container.classList.add("loading");
    container.innerHTML = '<div class="spinner"></div>';
  } else {
    loadingOverlay = showChartLoadingOverlay(container);
    loadingOverlay.attach();
  }

  let url = config.endpoint;
  const urlParams = new URLSearchParams();
  for (const key in params) {
    if (
      params[key] !== null &&
      params[key] !== undefined &&
      params[key] !== ""
    ) {
      urlParams.append(key, params[key]);
    }
  }
  const queryString = urlParams.toString();
  if (queryString) {
    url += `?${queryString}`;
  }

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Network response was not ok");

    let html;
    let options = [];
    let cacheParams = { ...params };
    if (config.hasDropdown) {
      const data = await response.json();
      html = data.html || "";
      options = data.months || data.years || [];
      const param = config.dateParam || "month";
      if (!cacheParams[param] && options.length > 0) {
        cacheParams[param] = options[0];
      }
      if (html) {
        container.innerHTML = html;
      } else {
        renderChartPlaceholder(container);
      }
      chartReplaced = true;
      setupDropdownAndReload(config, options, cacheParams[param]);
    } else {
      html = await response.text();
      if (html) {
        container.innerHTML = html;
      } else {
        renderChartPlaceholder(container);
      }
      chartReplaced = true;
      setupReloadButtonOnly(config);
    }
    loadingOverlay?.attach();
    container.dataset.loaded = "true";
    container.classList.remove("loading");
    if (config.id === "asset-summary") {
      initAssetMasking();
    }
    await runChartScripts(container);
    container.dataset.cacheSavedAt = String(
      saveChartCache(config, html, options, cacheParams),
    );
    loadingOverlay?.remove();
  } catch (error) {
    if (!hasPreviousChart) {
      container.innerHTML = "<p>Error loading graph.</p>";
    } else if (chartReplaced) {
      delete container.dataset.loaded;
      delete container.dataset.cacheSavedAt;
      showChartRenderErrorStatus(container);
    } else if (container.dataset.cacheSavedAt) {
      showCachedChartStatus(container, container.dataset.cacheSavedAt);
    }
    container.classList.remove("loading");
    loadingOverlay?.remove();
    console.error("Fetch error for " + url + ":", error);
  }
}

function setupReloadButtonOnly(config) {
  if (config.id === "asset-monthly-history") return;

  const controlsContainer = document.getElementById(
    `${config.id}-chart-controls`,
  );
  if (!controlsContainer) return;

  if (controlsContainer.querySelector(".btn-reload")) return;

  const btn = createReloadButton(() => {
    fetchAndRenderChart(config, {}, true);
  });
  controlsContainer.appendChild(btn);
}

function setupDropdownAndReload(config, months, selectedValue) {
  const controlsContainer = document.getElementById(
    `${config.id}-chart-controls`,
  );
  if (!controlsContainer) return;

  let select = controlsContainer.querySelector("select");
  if (!select && months.length > 0) {
    controlsContainer.innerHTML = "";
    select = document.createElement("select");
    select.id = `${config.id}-month-select`;

    select.addEventListener("change", (e) => {
      const param = config.dateParam || "month";
      fetchAndRenderChart(config, { [param]: e.target.value });
    });

    controlsContainer.appendChild(select);
  }

  if (select && months.length > 0) {
    const currentValue = selectedValue || select.value;
    const currentMonth = months.includes(currentValue)
      ? currentValue
      : months[0];
    select.replaceChildren();
    months.forEach((month) => {
      const option = document.createElement("option");
      option.value = month;
      option.textContent = config.optionLabel
        ? config.optionLabel(month)
        : month.replace("-", "年") + "月";
      option.selected = month === currentMonth;
      select.appendChild(option);
    });
  }

  if (!controlsContainer.querySelector(".btn-reload")) {
    const btn = createReloadButton(() => {
      const currentSelect = document.getElementById(
        `${config.id}-month-select`,
      );
      const value = currentSelect ? currentSelect.value : null;
      const param = config.dateParam || "month";
      fetchAndRenderChart(config, { [param]: value }, true);
    });
    controlsContainer.appendChild(btn);
  }
}

function initAssetSimulation() {
  const controls = document.getElementById(
    "asset-monthly-history-chart-controls",
  );
  if (!controls) return;

  const yieldInput = document.getElementById("sim-yield");
  const investmentInput = document.getElementById("sim-investment");
  const yearsInput = document.getElementById("sim-years");

  const config = allChartConfigs.asset.find(
    (c) => c.id === "asset-monthly-history",
  );

  const getParams = () => ({
    annual_yield: yieldInput ? yieldInput.value : "",
    monthly_investment: investmentInput ? investmentInput.value : "",
    duration_years: yearsInput ? yearsInput.value : "",
  });

  if (config && !controls.querySelector(".btn-reload")) {
    const btn = createReloadButton(() => {
      const params = getParams();
      fetchAndRenderChart(config, params, true);
    });
    controls.appendChild(btn);
  }

  const saved = localStorage.getItem("simParams");
  if (saved) {
    try {
      const loadedParams = JSON.parse(saved);
      if (loadedParams.annual_yield && yieldInput)
        yieldInput.value = loadedParams.annual_yield;
      if (loadedParams.monthly_investment && investmentInput)
        investmentInput.value = loadedParams.monthly_investment;
      if (loadedParams.duration_years && yearsInput)
        yearsInput.value = loadedParams.duration_years;
    } catch (e) {
      console.error("Failed to parse simParams", e);
    }
  }

  if (yieldInput && investmentInput && yearsInput && config) {
    const updateSim = () => {
      const params = getParams();
      localStorage.setItem("simParams", JSON.stringify(params));
      if (
        yieldInput.value === "" ||
        investmentInput.value === "" ||
        yearsInput.value === ""
      ) {
        return;
      }
      fetchAndRenderChart(config, params);
    };

    [yieldInput, investmentInput, yearsInput].forEach((input) => {
      input.addEventListener("change", updateSim);
    });
  }

  return getParams;
}

let tradingViewLoadPromise;

function ensureTradingViewLoaded() {
  if (window.TradingView) return Promise.resolve();
  if (!tradingViewLoadPromise) {
    tradingViewLoadPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/tv.js";
      script.onload = resolve;
      script.onerror = () => reject(new Error("Failed to load TradingView"));
      document.head.appendChild(script);
    });
  }
  return tradingViewLoadPromise;
}

function initTradingViewChart() {
  const symbolSelect = document.getElementById("symbol-select");
  const chartContainerId = "asset-tradingview-chart-container";
  const chartContainer = document.getElementById(chartContainerId);
  const controlsContainer = document.getElementById(
    "asset-tradingview-chart-controls",
  );
  if (!symbolSelect || !chartContainer) return;

  const theme = document.documentElement.classList.contains("dark")
    ? "dark"
    : "light";

  const loadChart = async (symbol) => {
    if (!symbol) return;
    try {
      await ensureTradingViewLoaded();
    } catch (error) {
      console.error("Failed to load TradingView:", error);
      return;
    }
    let tvSymbol = symbol;
    if (symbol === "USDJPY") {
      tvSymbol = "FX:USDJPY";
    } else if (symbol === "High Yield Spread") {
      tvSymbol = "FRED:BAMLH0A0HYM2";
    }

    chartContainer.innerHTML = "";

    const isIndicator = ["VIX", "FRED:BAMLH0A0HYM2"].includes(tvSymbol);

    new TradingView.widget({
      container_id: chartContainerId,
      autosize: true,
      symbol: tvSymbol,
      interval: "D",
      timezone: "Asia/Tokyo",
      theme: theme,
      style: isIndicator ? "2" : "1",
      backgroundColor: theme === "dark" ? "#1f2937" : "#ffffff",
      enable_publishing: false,
      hide_top_toolbar: false,
      save_image: false,
      studies: isIndicator
        ? []
        : ["RSI@tv-basicstudies", "MASimple@tv-basicstudies"],
      studies_overrides: isIndicator
        ? {}
        : {
            "moving average.length": 200,
            "moving average.source": "close",
          },
    });
  };

  if (controlsContainer && !controlsContainer.querySelector(".btn-reload")) {
    const btn = createReloadButton(() => {
      loadChart(symbolSelect.value);
    });
    controlsContainer.appendChild(btn);
  }

  const savedSymbol = localStorage.getItem("assetSymbol");
  if (
    savedSymbol &&
    Array.from(symbolSelect.options).some(
      (option) => option.value === savedSymbol,
    )
  ) {
    symbolSelect.value = savedSymbol;
  }

  if (symbolSelect.value) {
    loadChart(symbolSelect.value);
  }

  symbolSelect.addEventListener("change", (e) => {
    localStorage.setItem("assetSymbol", e.target.value);
    loadChart(e.target.value);
  });
}

function loadWhenNearViewport(container, loadChart) {
  if (!("IntersectionObserver" in window)) {
    loadChart();
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      loadChart();
    },
    { rootMargin: "300px" },
  );
  observer.observe(container);
}

export function initializeCharts() {
  cleanupExpiredChartCaches();
  const reportContainer = document.getElementById("report-container");
  const assetChartContainer = document.getElementById("asset-chart-container");

  if (!reportContainer && !assetChartContainer) return;

  if (reportContainer) {
    allChartConfigs.report.forEach((config) => {
      const container = document.getElementById(`${config.id}-chart-container`);
      if (!container) return;
      loadWhenNearViewport(container, () => loadChartWithCache(config));
    });
  }

  if (assetChartContainer) {
    let initialized = false;
    const initAssetChart = () => {
      if (initialized) return;
      initialized = true;
      const getSimulationParams = initAssetSimulation() || (() => ({}));
      allChartConfigs.asset.forEach((config) => {
        const container = document.getElementById(
          `${config.id}-chart-container`,
        );
        if (!container) return;

        const loadChart = () =>
          loadChartWithCache(
            config,
            config.id === "asset-monthly-history" ? getSimulationParams() : {},
          );
        loadWhenNearViewport(container, loadChart);
      });
      const tradingViewContainer = document.getElementById(
        "asset-tradingview-chart-container",
      );
      if (tradingViewContainer) {
        if (!("IntersectionObserver" in window)) {
          initTradingViewChart();
        } else {
          const observer = new IntersectionObserver(
            (entries) => {
              if (!entries.some((entry) => entry.isIntersecting)) return;
              observer.disconnect();
              initTradingViewChart();
            },
            { rootMargin: "300px" },
          );
          observer.observe(tradingViewContainer);
        }
      }
    };

    const trigger = document.querySelector("[data-key='asset-chart']");
    const isCollapsed = document.documentElement.classList.contains(
      "asset-chart-collapsed",
    );

    if (!isCollapsed) {
      initAssetChart();
    }
    if (trigger) {
      trigger.addEventListener("click", initAssetChart);
    }
  }
}
