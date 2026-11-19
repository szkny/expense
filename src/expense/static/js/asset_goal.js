const GOAL_STORAGE_KEY = "expense.assetGoal";
const SIMULATION_STORAGE_KEY = "simParams";
const MAX_PROJECTION_MONTHS = 100 * 12;

export function initAssetGoal() {
  const goalInput = document.getElementById("asset-goal-amount");
  const currentAmountElement = document.getElementById("total-asset-amount");
  const percentElement = document.getElementById("asset-goal-percent");
  const progressElement = document.getElementById("asset-goal-progress");
  const estimateElement = document.getElementById("asset-goal-estimate");
  const incomeElement = document.getElementById("asset-goal-income");
  const yieldInput = document.getElementById("sim-yield");
  const investmentInput = document.getElementById("sim-investment");
  if (
    !goalInput ||
    !currentAmountElement ||
    !percentElement ||
    !progressElement ||
    !estimateElement ||
    !incomeElement
  ) {
    return;
  }

  try {
    const savedGoal = localStorage.getItem(GOAL_STORAGE_KEY);
    if (savedGoal) goalInput.value = savedGoal;

    const savedSimulation = JSON.parse(
      localStorage.getItem(SIMULATION_STORAGE_KEY) || "{}",
    );
    if (savedSimulation.annual_yield && yieldInput && !yieldInput.value) {
      yieldInput.value = savedSimulation.annual_yield;
    }
    if (
      savedSimulation.monthly_investment &&
      investmentInput &&
      !investmentInput.value
    ) {
      investmentInput.value = savedSimulation.monthly_investment;
    }
  } catch {
    // The goal card remains usable when browser storage is unavailable.
  }

  const render = () => {
    const goal = Number(goalInput.value);
    incomeElement.textContent = "";
    const currentAmountText =
      currentAmountElement.dataset.originalValue?.replace(/[^\d.-]/g, "") || "";
    const currentAmount = currentAmountText
      ? Number(currentAmountText)
      : Number.NaN;
    if (!Number.isFinite(goal) || goal <= 0) {
      percentElement.textContent = "目標額を入力してください";
      progressElement.value = 0;
      estimateElement.textContent =
        "資産チャートの年利・月次積立の設定値を使って到達時期を試算します。";
      return;
    }
    if (!Number.isFinite(currentAmount)) {
      percentElement.textContent = "現在額を取得できません";
      progressElement.value = 0;
      estimateElement.textContent = "資産データを取得後に表示されます。";
      return;
    }

    const annualYield = Number(yieldInput?.value);
    if (
      yieldInput?.value &&
      Number.isFinite(annualYield) &&
      annualYield >= 0 &&
      annualYield <= 1000
    ) {
      const currentAnnualIncome = Math.round(
        (currentAmount * annualYield) / 100,
      );
      const goalAnnualIncome = Math.round((goal * annualYield) / 100);
      const formatIncome = (annualIncome) =>
        `約 ¥${(annualIncome / 10000).toLocaleString("ja-JP", {
          maximumFractionDigits: 1,
        })}万/年（¥${(annualIncome / 12 / 10000).toLocaleString("ja-JP", {
          maximumFractionDigits: 1,
        })}万/月）`;
      incomeElement.textContent =
        `現在の資産: ${formatIncome(currentAnnualIncome)}\n` +
        `目標到達後: ${formatIncome(goalAnnualIncome)}\nの不労所得が得られます。`;
    }

    const percent = (currentAmount / goal) * 100;
    percentElement.textContent = `${percent.toLocaleString("ja-JP", {
      maximumFractionDigits: 1,
    })}%`;
    progressElement.value = Math.min(percent, 100);

    if (currentAmount >= goal) {
      estimateElement.textContent = "目標額に到達しています。";
      return;
    }
    if (!yieldInput?.value || !investmentInput?.value) {
      estimateElement.textContent =
        "到達見込みは資産チャートの年利・月次積立を設定すると表示されます。";
      return;
    }

    const monthlyInvestment = Number(investmentInput.value);
    if (
      !Number.isFinite(annualYield) ||
      annualYield < -100 ||
      !Number.isFinite(monthlyInvestment) ||
      monthlyInvestment < 0
    ) {
      estimateElement.textContent = "年利・月次積立の設定を確認してください。";
      return;
    }

    const monthlyYield = (1 + annualYield / 100) ** (1 / 12) - 1;
    let projectedAmount = currentAmount;
    let months = 0;
    while (projectedAmount < goal && months < MAX_PROJECTION_MONTHS) {
      projectedAmount = Math.max(
        projectedAmount * (1 + monthlyYield) + monthlyInvestment,
        0,
      );
      months += 1;
    }
    if (projectedAmount < goal) {
      estimateElement.textContent =
        "現在の設定では100年以内の到達見込みはありません。";
      return;
    }

    const targetDate = new Date();
    targetDate.setDate(1);
    targetDate.setMonth(targetDate.getMonth() + months);
    estimateElement.textContent =
      `年利 ${annualYield}%・月次積立 ¥${monthlyInvestment.toLocaleString("ja-JP")} の試算: ` +
      `${targetDate.getFullYear()}年${targetDate.getMonth() + 1}月頃に到達見込みです。`;
  };

  goalInput.addEventListener("input", () => {
    try {
      localStorage.setItem(GOAL_STORAGE_KEY, goalInput.value);
    } catch {
      // Rendering does not depend on persistence.
    }
    render();
  });
  yieldInput?.addEventListener("input", render);
  investmentInput?.addEventListener("input", render);
  render();
}
