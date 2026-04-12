// src/expense/static/js/chart.js

const allChartConfigs = {
  report: [
    { id: "pie", endpoint: "/api/pie_chart", hasDropdown: true },
    { id: "daily", endpoint: "/api/daily_chart", hasDropdown: true },
    { id: "bar", endpoint: "/api/bar_chart", hasDropdown: false },
    {
      id: "annual-fiscal-report",
      endpoint: "/api/annual_fiscal_report_chart",
      hasDropdown: false,
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
      id: "asset-waterfall",
      endpoint: "/api/asset_waterfall_chart",
      hasDropdown: false,
    },
    {
      id: "asset-monthly-history",
      endpoint: "/api/asset_monthly_history_chart",
      hasDropdown: false,
    },
  ],
};

async function fetchAndRenderChart(config, month = null) {
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
}

function createDropdown(config, months) {
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
}

function initTradingViewChart() {
  const symbolSelect = document.getElementById("symbol-select");
  const chartContainerId = "asset-tradingview-chart-container";
  const chartContainer = document.getElementById(chartContainerId);
  if (!symbolSelect || !chartContainer) return;

  const theme = document.documentElement.classList.contains("dark")
    ? "dark"
    : "light";

  const loadChart = (symbol) => {
    if (!symbol) return;
    let tvSymbol = symbol;
    if (symbol === "USDJPY") {
      tvSymbol = "FX:USDJPY";
    } else if (symbol === "High Yield Spread") {
      tvSymbol = "FRED:BAMLH0A0HYM2";
    }

    // Clear previous widget
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

  if (symbolSelect.value) {
    loadChart(symbolSelect.value);
  }

  symbolSelect.addEventListener("change", (e) => {
    loadChart(e.target.value);
  });
}

export function initializeCharts() {
  const reportContainer = document.getElementById("report-container");
  const assetReportContainer = document.getElementById(
    "asset-report-container",
  );

  if (!reportContainer && !assetReportContainer) return;

  if (reportContainer) {
    allChartConfigs.report.forEach((config) => fetchAndRenderChart(config));
  }

  if (assetReportContainer) {
    const initAssetChart = () => {
      allChartConfigs.asset.forEach((config) => fetchAndRenderChart(config));
      initTradingViewChart();
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
}
