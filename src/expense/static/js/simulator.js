// src/expense/static/js/simulator.js

const SCENARIOS = [
  { label: "楽観", freelanceIncome: 80, monthlyExpense: 28, color: "#4ade80" },
  { label: "基本", freelanceIncome: 60, monthlyExpense: 33, color: "#60a5fa" },
  { label: "悲観", freelanceIncome: 35, monthlyExpense: 35, color: "#f87171" },
];

const PARAMS = {
  currentAge: 32,
  independenceAge: 37,
  targetAge: 40,
  currentAssets: 3920,
  monthlyReturn: 5,
  salaryMonthlyInvestment: 30,
  freelanceIncome: 60,
  monthlyExpense: 33,
};

function calcProjection(params) {
  const {
    currentAge,
    independenceAge,
    targetAge,
    currentAssets,
    salaryMonthlyInvestment,
    monthlyReturn,
    freelanceIncome,
    monthlyExpense,
  } = params;

  const annualRate = monthlyReturn / 100;
  const monthlyRate = Math.pow(1 + annualRate, 1 / 12) - 1;
  const monthlyBalance = freelanceIncome - monthlyExpense;
  const monthlyInvestmentAfter = Math.max(0, monthlyBalance);

  const points = [];
  let assets = currentAssets;
  const maxAge = Math.max(targetAge, independenceAge) + 5;

  for (let age = currentAge; age <= maxAge; age++) {
    points.push({ age, assets: Math.round(assets) });
    const isEmployed = age < independenceAge;
    const monthlyAdd = isEmployed
      ? salaryMonthlyInvestment
      : monthlyInvestmentAfter;
    for (let m = 0; m < 12; m++) {
      assets = assets * (1 + monthlyRate) + monthlyAdd;
    }
  }
  return points;
}

function updateUI() {
  const projection = calcProjection(PARAMS);
  const atIndependence =
    projection.find((p) => p.age === PARAMS.independenceAge)?.assets ?? 0;
  const atTarget =
    projection.find((p) => p.age === PARAMS.targetAge)?.assets ?? 0;
  const reachesGoal = atTarget >= 10000;
  const monthlyBalance = PARAMS.freelanceIncome - PARAMS.monthlyExpense;
  const monthlyInvestmentAfter = Math.max(0, monthlyBalance);

  // Update values display
  document.getElementById("val-independenceAge").textContent =
    `${PARAMS.independenceAge}歳`;
  document.getElementById("val-salaryMonthlyInvestment").textContent =
    `${PARAMS.salaryMonthlyInvestment}万円`;
  document.getElementById("val-freelanceIncome").textContent =
    `${PARAMS.freelanceIncome}万円/月`;
  document.getElementById("val-monthlyExpense").textContent =
    `${PARAMS.monthlyExpense}万円/月`;
  document.getElementById("val-monthlyReturn").textContent =
    `${PARAMS.monthlyReturn}%`;

  // Update investment result
  const resEl = document.getElementById("monthly-investment-result");
  resEl.textContent = `${monthlyBalance >= 0 ? "+" : ""}${monthlyBalance}万円/月`;
  resEl.style.color = monthlyBalance >= 0 ? "#60a5fa" : "#f87171";
  document.getElementById("monthly-investment-calc").textContent =
    `収入 ${PARAMS.freelanceIncome}万 − 生活費 ${PARAMS.monthlyExpense}万`;

  // Update KPIs
  document.getElementById("kpi-atIndependence").textContent =
    `${(atIndependence / 10000).toFixed(2)}億`;
  document.getElementById("kpi-sub-atIndependence").textContent =
    `${PARAMS.independenceAge}歳時点`;

  const targetKpi = document.getElementById("kpi-atTarget");
  targetKpi.textContent = `${(atTarget / 10000).toFixed(2)}億`;
  targetKpi.style.color = reachesGoal ? "#4ade80" : "#f87171";
  const targetSub = document.getElementById("kpi-sub-atTarget");
  targetSub.textContent = reachesGoal ? "✓ 目標達成" : "✗ 未達成";
  targetSub.style.color = reachesGoal ? "#4ade80" : "#f87171";
  document.getElementById("kpi-box-atTarget").style.borderColor = reachesGoal
    ? "rgba(74,222,128,0.2)"
    : "rgba(248,113,113,0.2)";

  document.getElementById("kpi-monthlyInvestmentAfter").textContent =
    `${monthlyInvestmentAfter}万`;
  document.getElementById("kpi-monthlyInvestmentAfter").style.color =
    monthlyInvestmentAfter > 0 ? "" : "#f87171";

  const hit = projection.find((p) => p.assets >= 10000);
  document.getElementById("kpi-reachAge").textContent = hit
    ? `${hit.age}歳`
    : "未達";

  // Update Chart
  const chartData = projection.filter((p) => p.age <= PARAMS.targetAge + 5);
  const maxVal = Math.max(...chartData.map((p) => p.assets), 10000) * 1.05;
  const W = 500,
    H = 300;
  const pad = { top: 20, right: 20, bottom: 40, left: 60 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;

  const xScale = (age) =>
    ((age - chartData[0].age) /
      (chartData[chartData.length - 1].age - chartData[0].age)) *
    chartW;
  const yScale = (v) => chartH - (v / maxVal) * chartH;

  const pathD = chartData
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"}${pad.left + xScale(p.age)},${pad.top + yScale(p.assets)}`,
    )
    .join(" ");
  const areaD =
    pathD +
    ` L${pad.left + xScale(chartData[chartData.length - 1].age)},${pad.top + chartH} L${pad.left},${pad.top + chartH} Z`;

  document.getElementById("line-path").setAttribute("d", pathD);
  document.getElementById("area-path").setAttribute("d", areaD);

  const indLine = document.getElementById("independence-line");
  const indX = pad.left + xScale(PARAMS.independenceAge);
  indLine.setAttribute("x1", indX);
  indLine.setAttribute("x2", indX);
  indLine.setAttribute("y1", pad.top);
  indLine.setAttribute("y2", pad.top + chartH);
  const indLabel = document.getElementById("independence-label");
  indLabel.setAttribute("x", indX + 4);
  indLabel.setAttribute("y", pad.top + 10);

  const targetLine = document.getElementById("target-100m-line");
  const targetLabel = document.getElementById("target-100m-label");
  const targetY = pad.top + yScale(10000);

  if (targetY >= pad.top && targetY <= pad.top + chartH) {
    targetLine.setAttribute("x1", pad.left);
    targetLine.setAttribute("x2", pad.left + chartW);
    targetLine.setAttribute("y1", targetY);
    targetLine.setAttribute("y2", targetY);
    targetLine.style.display = "";
    targetLabel.setAttribute("y", targetY - 4);
    targetLabel.style.display = "";
  } else {
    targetLine.style.display = "none";
    targetLabel.style.display = "none";
  }

  // Grid and labels
  const gridLines = document.getElementById("grid-lines");
  gridLines.innerHTML = "";
  [2500, 5000, 7500, 10000]
    .filter((v) => v <= maxVal)
    .forEach((v) => {
      const y = pad.top + yScale(v);
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const line = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "line",
      );
      line.setAttribute("x1", pad.left);
      line.setAttribute("x2", pad.left + chartW);
      line.setAttribute("y1", y);
      line.setAttribute("y2", y);
      line.setAttribute("stroke", "rgba(255,255,255,0.05)");
      line.setAttribute("stroke-width", "1");
      g.appendChild(line);

      const text = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "text",
      );
      text.setAttribute("x", pad.left - 8);
      text.setAttribute("y", y + 4);
      text.setAttribute("text-anchor", "end");
      text.setAttribute("fill", "#64748b");
      text.setAttribute("font-size", "10");
      text.setAttribute("font-family", "DM Mono");
      text.textContent = v === 10000 ? "1億" : `${v / 10000}億`;
      g.appendChild(text);
      gridLines.appendChild(g);
    });

  const ageLabels = document.getElementById("age-labels");
  ageLabels.innerHTML = "";
  chartData
    .filter((_, i) => i % 2 === 0)
    .forEach((p) => {
      const text = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "text",
      );
      text.setAttribute("x", pad.left + xScale(p.age));
      text.setAttribute("y", pad.top + chartH + 20);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("fill", "#64748b");
      text.setAttribute("font-size", "10");
      text.setAttribute("font-family", "DM Mono");
      text.textContent = p.age;
      ageLabels.appendChild(text);
    });

  // Advisory
  const advisoryText = document.getElementById("advisory-text");
  if (reachesGoal) {
    advisoryText.textContent = `現在のパラメータでは40歳時点で${(atTarget / 10000).toFixed(2)}億円に到達する見込みです。独立後は月${monthlyInvestmentAfter}万円を継続投資できる収支構造で、目標達成は現実的です。`;
    document.getElementById("advisory-card").style.borderColor =
      "rgba(74,222,128,0.15)";
  } else if (monthlyBalance <= 0) {
    advisoryText.textContent = `生活費が収入を上回っており（月${Math.abs(monthlyBalance)}万円の赤字）、投資の継続が困難です。独立後の収入増加または生活費の圧縮が必要です。`;
    document.getElementById("advisory-card").style.borderColor =
      "rgba(248,113,113,0.15)";
  } else {
    advisoryText.textContent = `40歳時点で${(atTarget / 10000).toFixed(2)}億円にとどまり、目標に${((10000 - atTarget) / 10000).toFixed(2)}億円不足します。収入増加か独立時期を遅らせることで改善できます。`;
    document.getElementById("advisory-card").style.borderColor =
      "rgba(248,113,113,0.15)";
  }
}

export function initSimulator() {
  const app = document.getElementById("sim-app");
  if (!app) return;

  PARAMS.currentAssets = parseInt(app.dataset.currentAssets || "3920");
  document.getElementById("footer-current-assets").textContent =
    PARAMS.currentAssets.toLocaleString();

  const inputs = [
    "independenceAge",
    "salaryMonthlyInvestment",
    "freelanceIncome",
    "monthlyExpense",
    "monthlyReturn",
  ];

  const updateScenarioStatus = (scenarioLabel) => {
    const btns = document.querySelectorAll(".scenario-btn");
    btns.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.scenario === scenarioLabel);
    });
    document.getElementById("custom-label").style.display = scenarioLabel
      ? "none"
      : "flex";
  };

  inputs.forEach((key) => {
    const input = document.getElementById(`input-${key}`);
    if (input) {
      input.addEventListener("input", (e) => {
        PARAMS[key] = Number(e.target.value);
        updateScenarioStatus(null);
        updateUI();
      });
    }
  });

  const scenarioBtns = document.getElementById("scenario-buttons");
  if (scenarioBtns) {
    scenarioBtns.addEventListener("click", (e) => {
      const btn = e.target.closest(".scenario-btn");
      if (!btn) return;

      const label = btn.dataset.scenario;
      const scenario = SCENARIOS.find((s) => s.label === label);
      if (scenario) {
        PARAMS.freelanceIncome = scenario.freelanceIncome;
        PARAMS.monthlyExpense = scenario.monthlyExpense;

        document.getElementById("input-freelanceIncome").value =
          scenario.freelanceIncome;
        document.getElementById("input-monthlyExpense").value =
          scenario.monthlyExpense;

        updateScenarioStatus(label);
        updateUI();
      }
    });
  }

  updateUI();
}
