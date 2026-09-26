// src/expense/static/js/plotly_yaxis_autoscale.js

function getNumericValue(value) {
  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function getAxisTickSettings(ymin, ymax) {
  if (ymax < 10000) {
    return { "yaxis.tickvals": null, "yaxis.ticktext": null };
  }

  const unit = ymax >= 100000000 ? 100000000 : 10000;
  const suffix = ymax >= 100000000 ? "億" : "万";
  const rawStep = (ymax - ymin) / 5;
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const ratio = rawStep / power;
  const tickStep =
    ratio < 1.5
      ? power
      : ratio < 3
        ? 2 * power
        : ratio < 7
          ? 5 * power
          : 10 * power;
  const tickvals = [];

  for (
    let value = Math.floor(ymin / tickStep) * tickStep;
    value <= ymax * 1.01;
    value += tickStep
  ) {
    tickvals.push(value);
    if (tickvals.length > 100) break;
  }

  const ticktext = tickvals.map((value) => {
    if (Math.abs(value) < 1) return "¥0";
    const prefix = value >= 0 ? "" : "-";
    const valueUnit = Math.abs(value) < 100000000 ? 10000 : unit;
    const valueSuffix = Math.abs(value) < 100000000 ? "万" : suffix;
    const formatted = Math.abs(value / valueUnit);
    const text = Number.isInteger(formatted)
      ? formatted.toLocaleString("en-US")
      : formatted.toLocaleString("en-US", { maximumFractionDigits: 1 });
    return `${prefix}¥${text}${valueSuffix}`;
  });

  return {
    "yaxis.tickvals": tickvals,
    "yaxis.ticktext": ticktext,
    "yaxis.tickprefix": null,
    "yaxis.tickformat": null,
  };
}

function getVisibleYRange(graphDiv, xRangeOverride) {
  const xaxis = graphDiv._fullLayout?.xaxis || graphDiv.layout?.xaxis;
  const yaxis = graphDiv._fullLayout?.yaxis || graphDiv.layout?.yaxis;
  const isLog = yaxis?.type === "log";
  const rawXRange = xRangeOverride || xaxis?.range;
  const xRange = rawXRange?.map((value) => new Date(value).getTime());
  const hasXRange = xRange?.length === 2 && xRange.every(Number.isFinite);
  let ymin = isLog ? Infinity : 0;
  let ymax = 0;
  let hasValue = false;

  for (const trace of graphDiv._fullData || graphDiv.data || []) {
    if (
      trace.visible === false ||
      trace.visible === "legendonly" ||
      trace.name === "値ラベル"
    ) {
      continue;
    }

    const xValues = trace.x || [];
    const yValues = trace.y || [];
    for (let index = 0; index < yValues.length; index += 1) {
      if (hasXRange) {
        const xValue = new Date(xValues[index]).getTime();
        if (
          !Number.isFinite(xValue) ||
          xValue < xRange[0] ||
          xValue > xRange[1]
        ) {
          continue;
        }
      }

      const value = getNumericValue(yValues[index]);
      if (value === null) continue;
      const base = Array.isArray(trace.base)
        ? getNumericValue(trace.base[index])
        : getNumericValue(trace.base);
      const endpoint = base === null ? value : base + value;
      if (isLog) {
        const positiveValues = [value, base, endpoint].filter(
          (item) => item !== null && item > 0,
        );
        if (positiveValues.length === 0) continue;
        ymin = Math.min(ymin, ...positiveValues);
        ymax = Math.max(ymax, ...positiveValues);
        hasValue = true;
        continue;
      }
      ymin = Math.min(ymin, base ?? 0, endpoint);
      ymax = Math.max(ymax, base ?? 0, endpoint);
      hasValue = true;
    }
  }

  if (!hasValue) return null;
  if (isLog) {
    return [Math.log10(ymin / 1.2), Math.log10(ymax * 1.2)];
  }
  const margin = Math.max(Math.abs(ymin), Math.abs(ymax), 1) * 0.2;
  return [ymin - (ymin < 0 ? margin : 0), ymax + margin];
}

function updateYaxis(graphDiv, xRange) {
  const range = getVisibleYRange(graphDiv, xRange);
  if (!range) return;
  const [ymin, ymax] = range;
  const isLog =
    (graphDiv._fullLayout?.yaxis || graphDiv.layout?.yaxis)?.type === "log";
  const tickYmin = isLog ? 10 ** ymin : ymin;
  const tickYmax = isLog ? 10 ** ymax : ymax;
  Plotly.relayout(graphDiv, {
    "yaxis.range": range,
    "yaxis.autorange": false,
    ...getAxisTickSettings(tickYmin, tickYmax),
  });
}

window.attachPlotlyYAxisAutoscale = function attachPlotlyYAxisAutoscale(
  graphDiv,
) {
  if (
    !graphDiv ||
    graphDiv.__expenseYAxisAutoscaleAttached ||
    typeof graphDiv.on !== "function"
  ) {
    return;
  }
  graphDiv.__expenseYAxisAutoscaleAttached = true;

  let isHovering = false;
  const scheduleUpdate = (xRange) =>
    window.requestAnimationFrame(() => updateYaxis(graphDiv, xRange));
  graphDiv.on("plotly_beforehover", () => {
    isHovering = true;
  });
  graphDiv.on("plotly_hover", () => {
    isHovering = true;
  });
  graphDiv.on("plotly_unhover", () => {
    isHovering = false;
  });
  graphDiv.on("plotly_restyle", () => {
    window.setTimeout(() => scheduleUpdate(), 0);
  });
  graphDiv.on("plotly_legendclick", () => {
    window.setTimeout(() => scheduleUpdate(), 0);
  });
  graphDiv.on("plotly_legenddoubleclick", () => {
    window.setTimeout(() => scheduleUpdate(), 0);
  });
  graphDiv.on("plotly_relayout", (event) => {
    if (isHovering) return;
    const xRange =
      event["xaxis.range"] ||
      ("xaxis.range[0]" in event && "xaxis.range[1]" in event
        ? [event["xaxis.range[0]"], event["xaxis.range[1]"]]
        : null);
    if (xRange || "xaxis.autorange" in event) {
      scheduleUpdate(xRange);
    }
  });
  scheduleUpdate();
};

function attachToPlotlyGraphs() {
  document.querySelectorAll(".js-plotly-plot").forEach((graphDiv) => {
    window.attachPlotlyYAxisAutoscale(graphDiv);
  });
}

attachToPlotlyGraphs();
new MutationObserver(attachToPlotlyGraphs).observe(document.documentElement, {
  childList: true,
  subtree: true,
});
