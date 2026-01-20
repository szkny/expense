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
