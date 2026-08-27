import re
import math
import logging
import numpy as np
import pandas as pd
import datetime as dt
from typing import Any

import plotly.io as pio
from plotly import express as px
from plotly import graph_objects as go

from ..core.base import Base
from .fitting import FittingModel

log: logging.Logger = logging.getLogger("expense")


class GraphGenerator(Base):
    _FORECAST_HALF_LIFE_DAYS = 90

    def __init__(
        self,
        expense_types: list[str],
        fixed_types: list[str],
        variable_types: list[str],
        income_types: list[str],
        exclude_types: list[str],
        graph_config: dict[str, dict[str, str]],
    ):
        super().__init__()
        self.expense_types = expense_types
        self.fixed_types = fixed_types
        self.variable_types = variable_types
        self.exclude_types = exclude_types
        self.income_types = income_types
        self.graph_color = graph_config.get("color", {})
        self.asset_management_config = self.config.get("asset_management", {})
        self.fitting_duration_multiplier = self.asset_management_config.get(
            "fitting_duration_multiplier", 1.0
        )
        # NOTE: サーバー起動の初回アクセス時に、plotlyのテンプレート関連の処理でエラーが発生することがあるため
        #       デフォルトのテンプレートを明示的に指定しておく
        pio.templates.default = "plotly_white"

    def get_plotlyjs(self) -> str:
        log.info("start 'get_plotlyjs' method")
        dummy_fig: dict = dict(data=[], layout={})
        html: str = pio.to_html(
            dummy_fig, include_plotlyjs=True, full_html=False
        )
        scripts = re.findall(
            r'(<script type="text/javascript">.*?</script>)', html, re.DOTALL
        )
        script_html: str = scripts[0] + scripts[1] if len(scripts) >= 2 else ""
        log.info("end 'get_plotlyjs' method")
        return script_html

    @staticmethod
    def _calculate_monthly_returns(df: pd.DataFrame) -> pd.Series:
        """月初の積立額を除いた月次リターンを計算する。"""
        df_returns = df.copy()
        df_returns["date"] = pd.to_datetime(df_returns["date"])
        df_returns = df_returns.sort_values("date")
        valuation = pd.to_numeric(df_returns["valuation"], errors="coerce")
        invested = pd.to_numeric(df_returns["invest_amount"], errors="coerce")
        contribution = invested.diff()
        monthly_returns = valuation / (valuation.shift(1) + contribution) - 1
        return monthly_returns.replace([np.inf, -np.inf], np.nan).dropna()

    @classmethod
    def _calculate_weighted_daily_rates(
        cls, df: pd.DataFrame, end_date: pd.Timestamp
    ) -> tuple[float, float]:
        """全履歴から直近ほど重くした収入・支出の日平均を計算する。"""
        history = df.loc[df["date"] <= end_date]
        if history.empty:
            return 0.0, 0.0
        daily = (
            history.groupby("date")[["income", "expense"]]
            .sum()
            .reindex(
                pd.date_range(history["date"].min(), end_date), fill_value=0
            )
        )
        age_days = (end_date - daily.index).days.to_numpy()
        weights = np.exp(-np.log(2) * age_days / cls._FORECAST_HALF_LIFE_DAYS)
        return tuple(
            float(np.average(daily[column], weights=weights))
            for column in ["income", "expense"]
        )

    def generate_monthly_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        月別のDataFrameを生成
        """
        log.info("start 'generate_monthly_df' method")
        df_new = df.copy()
        df_new.loc[:, "date"] = pd.to_datetime(df_new.loc[:, "date"])
        df_new.loc[:, "month"] = pd.to_datetime(
            df_new.loc[:, "date"]
        ).dt.strftime("%Y-%m")
        df_ref = df_new.copy()
        df_new = (
            df_new.groupby(["month", "expense_type"])["expense_amount"]
            .sum()
            .reset_index()
        )
        # extract memos for hover text of monthly chart
        df_new = self._add_expense_memo_summary(df_new, df_ref, "month")
        log.info("end 'generate_monthly_df' method")
        return df_new

    def _add_expense_memo_summary(
        self,
        df: pd.DataFrame,
        df_ref: pd.DataFrame,
        date_or_month: str,
        len_memo_text: int = 50,
    ) -> pd.DataFrame:
        # Make sure the grouping key column exists in the reference dataframe
        df_ref_copy = df_ref.copy()
        if date_or_month == "month" and "month" not in df_ref_copy.columns:
            df_ref_copy["month"] = pd.to_datetime(
                df_ref_copy["date"]
            ).dt.strftime("%Y-%m")

        # Filter out rows with no memo, as they don't contribute to the summary
        df_ref_copy = df_ref_copy[
            df_ref_copy["expense_memo"].str.len() > 0
        ].copy()
        if df_ref_copy.empty:
            df["expense_memo"] = "<br>"
            return df

        # Pre-calculate counts and sums for each memo within the main grouping keys
        memo_stats = (
            df_ref_copy.groupby([date_or_month, "expense_type", "expense_memo"])
            .agg(
                total_amount=("expense_amount", "sum"),
                count=("expense_memo", "size"),
            )
            .reset_index()
        )

        # Sort by amount to prioritize important memos when building the summary string
        memo_stats.sort_values("total_amount", ascending=False, inplace=True)

        # Create the display memo string (e.g., "Lunch ×3")
        memo_stats["display_memo"] = memo_stats.apply(
            lambda r: (
                f"{r['expense_memo']} ×{r['count']}"
                if r["count"] > 1
                else r["expense_memo"]
            ),
            axis=1,
        )

        # Use groupby().apply() to build the truncated summary string for each group.
        # This is significantly faster than iterating over the main dataframe.
        def create_summary_string(group: pd.DataFrame) -> str:
            memos: list[str] = []
            char_count = 0
            for memo in group["display_memo"]:
                # Length check includes the separator ",<br>"
                if memos and char_count + len(memo) + 5 > len_memo_text:
                    memos.append("⋯")
                    break
                memos.append(memo)
                char_count += len(memo)
            result = ",<br>".join(memos)
            result = "<br>" + result if len(memos) else ""
            return result

        summaries = (
            memo_stats.groupby([date_or_month, "expense_type"])
            .apply(create_summary_string, include_groups=False)
            .rename("expense_memo")
            .reset_index()
        )

        # Merge the generated summaries back into the original aggregated dataframe
        if "expense_memo" in df.columns:
            df.drop(columns=["expense_memo"], inplace=True)
        df = df.merge(summaries, on=[date_or_month, "expense_type"], how="left")

        # Set default value for groups that had no memos
        df.fillna({"expense_memo": "<br>"}, inplace=True)

        return df

    def _get_month_boundaries(self, t: dt.datetime) -> tuple[str, str]:
        month_start = dt.date(t.year, t.month, 1).isoformat()
        month_end = (
            dt.date(
                t.year if t.month < 12 else t.year + 1,
                t.month + 1 if t.month < 12 else 1,
                1,
            )
            - dt.timedelta(days=1)
        ).isoformat()
        return month_start, month_end

    def _prepare_graph_dataframe(
        self, df: pd.DataFrame, month_start: str, month_end: str
    ) -> pd.DataFrame:
        df_graph = df.copy()
        df_graph["date"] = pd.to_datetime(df_graph["date"])
        df_graph = df_graph.query(
            f"date >= @pd.Timestamp('{month_start}') and date <= @pd.Timestamp('{month_end}')"
        )
        df_graph = df_graph.sort_values("date")
        df_graph["cumsum"] = df_graph["expense_amount"].cumsum()
        return df_graph

    def _prepare_bar_dataframe(self, df_graph: pd.DataFrame) -> pd.DataFrame:
        df_graph = df_graph.sort_values(
            ["date", "expense_type", "expense_amount"]
        )
        df_bar = (
            df_graph.groupby(["date", "expense_type"])["expense_amount"]
            .sum()
            .reset_index()
        )
        df_bar.index = pd.Index(range(len(df_bar)))
        # extract memos for hover text of bar chart
        df_bar = self._add_expense_memo_summary(df_bar, df_graph, "date")
        # add offset to `date` column
        df_bar["date"] = pd.to_datetime(df_bar["date"]) + pd.Timedelta(hours=12)
        return df_bar

    def _add_month_start_point(
        self, df_graph: pd.DataFrame, month_start: str
    ) -> pd.DataFrame:
        if pd.to_datetime(month_start) < df_graph["date"].iloc[0]:
            df_graph = pd.concat(
                [
                    pd.DataFrame(
                        {
                            "date": [pd.to_datetime(month_start)],
                            "cumsum": [0],
                        }
                    ),
                    df_graph,
                ],
                ignore_index=True,
            )
        return df_graph

    def _handle_predictions(
        self,
        df_graph: pd.DataFrame,
        t: dt.datetime,
        month_start: str,
        month_end: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        latest_date = df_graph.iloc[-1]["date"]
        latest_date = t if t > latest_date else latest_date
        if latest_date < pd.to_datetime(month_end):
            df_graph = pd.concat(
                [
                    df_graph,
                    pd.DataFrame(
                        {
                            "date": [pd.to_datetime(month_end)],
                            "cumsum": [df_graph["cumsum"].iloc[-1]],
                        }
                    ),
                ],
                ignore_index=True,
            )
            total_monthly_expense = df_graph["expense_amount"].sum()
            days_passed = (
                pd.to_datetime(latest_date.date()) - pd.to_datetime(month_start)
            ).days + 1
            df_predict = pd.DataFrame(
                {
                    "date": [
                        pd.to_datetime(month_start),
                        pd.to_datetime(month_end),
                    ],
                    "predict": [
                        0,
                        df_graph["cumsum"].iloc[-1]
                        + (
                            pd.to_datetime(month_end)
                            - pd.to_datetime(latest_date.date())
                        ).days
                        * total_monthly_expense
                        / days_passed,
                    ],
                }
            )
        else:
            df_predict = pd.DataFrame(columns=["date", "predict"])
        return df_graph, df_predict

    def _create_bar_figure(
        self,
        df_bar: pd.DataFrame,
        month_start: str,
        month_end: str,
        min_yrange: int,
        df_graph: pd.DataFrame,
        df_predict: pd.DataFrame,
        theme: str,
    ) -> go.Figure:
        month_str = pd.Timestamp(month_start).strftime("%Y年%-m月")
        return px.bar(
            df_bar,
            x="date",
            y="expense_amount",
            color="expense_type",
            title=f"支出内訳 日別（{month_str}）",
            hover_data=["expense_memo"],
            category_orders={"expense_type": self.expense_types},
            color_discrete_map=self.graph_color,
            opacity=0.8,
            barmode="stack",
            range_x=[
                pd.Timestamp(month_start) - pd.Timedelta(days=2),
                pd.Timestamp(month_end) + pd.Timedelta(days=2),
            ],
            range_y=[
                0,
                max(
                    min_yrange,
                    df_graph["cumsum"].max() * 1.2,
                    df_predict["predict"].max() * 1.2,
                ),
            ],
            # NOTE: テンプレートを明示的に指定しないと、稀に無限ループ→Invalid valueエラーが発生することがある
            template="plotly_dark" if theme == "dark" else "plotly_white",
        )

    def _create_line_figure(
        self, df_graph: pd.DataFrame, theme: str
    ) -> go.Figure:
        return px.line(
            df_graph,
            x="date",
            y="cumsum",
            line_shape="hv",
            color_discrete_sequence=[
                "#3b82f6" if theme == "dark" else "#223377"
            ],
        )

    def _create_prediction_figure(
        self, df_predict: pd.DataFrame, theme: str
    ) -> go.Figure:
        return px.line(
            df_predict,
            x="date",
            y="predict",
            color_discrete_sequence=[
                "#dd4433" if theme == "dark" else "#ff5544"
            ],
        )

    def _add_bar_chart_labels(
        self,
        fig: go.Figure,
        df_bar: pd.DataFrame,
        key: str,
        theme: str,
        fontsize: int = 10,
        label_nlags: int = 3,
        label_threshold: int = 1000,
        label_offset: int = 2000,
        offsetgroup: str | None = None,
    ) -> None:
        totals = df_bar.groupby(key, as_index=False)["expense_amount"].sum()
        label = totals["expense_amount"].map(
            lambda x: f"¥{x:,}" if x >= label_threshold else ""
        )
        y = totals["expense_amount"].to_list()
        for _ in range(label_nlags):
            for i, v in enumerate(y):
                if label.iloc[i] and any(
                    [
                        abs(y[i] - y[i - j - 1]) < label_threshold
                        and label.iloc[i - j - 1]
                        for j in range(min(i, label_nlags))
                    ]
                ):
                    y[i] = y[i] + label_offset
        label_trace_kwargs = dict(
            x=totals[key],
            y=y,
            text=label,
            textfont=dict(
                size=fontsize,
                weight="bold",
                color="#ffffff" if theme == "dark" else "#000000",
            ),
            name="値ラベル",
            showlegend=True,
            hoverinfo="skip",
        )
        if offsetgroup is None:
            fig.add_trace(
                go.Scatter(
                    mode="text",
                    textposition="top center",
                    **label_trace_kwargs,
                )
            )
        else:
            # 透明な棒を同じ offsetgroup に置き、ラベルも支出バーに揃える。
            fig.add_trace(
                go.Bar(
                    marker=dict(
                        color="rgba(0, 0, 0, 0)",
                        line=dict(color="rgba(0, 0, 0, 0)"),
                    ),
                    offsetgroup=offsetgroup,
                    cliponaxis=False,
                    textposition="outside",
                    constraintext="none",
                    **{
                        **label_trace_kwargs,
                        "y": [0] * len(y),
                        "base": y,
                    },
                )
            )

    def _update_traces(
        self, fig_bar: go.Figure, fig_line: go.Figure, fig_predict: go.Figure
    ) -> None:
        fig_bar.update_traces(
            hovertemplate="%{x|%-m月%-d日} ¥%{y:,.0f}%{customdata[0]}",
            textfont=dict(size=14),
        )
        fig_line.update_traces(
            line=dict(dash="solid", width=1.5),
            hovertemplate="¥%{y:,.0f}",
            name="累積合計",
            showlegend=True,
        )
        fig_predict.update_traces(
            line=dict(dash="dot", width=1.5),
            hovertemplate="¥%{y:,.0f}",
            name="予測",
            showlegend=True,
        )

    def _get_yaxis_range(
        self, fig: go.Figure, ymax_override: float | None
    ) -> tuple[float, float] | None:
        """Get y-axis range from override or figure layout."""
        if ymax_override is not None:
            ymax = ymax_override
            ymin = 0.0
            if (
                fig.layout.yaxis
                and fig.layout.yaxis.range
                and fig.layout.yaxis.range[0] is not None
            ):
                ymin = fig.layout.yaxis.range[0]
            return ymin, ymax
        elif (
            fig.layout.yaxis
            and fig.layout.yaxis.range
            and fig.layout.yaxis.range[1] is not None
        ):
            yrange: tuple[float, float] = fig.layout.yaxis.range
            return yrange
        return None

    def _calculate_tick_step(
        self, ymin: float, ymax: float, num_ticks: int = 5
    ) -> int:
        """Calculate a 'nice' tick step for the y-axis."""
        if ymax <= ymin:
            return 0
        tick_step = (ymax - ymin) / num_ticks
        if tick_step <= 0:
            return 0
        power: int = 10 ** math.floor(math.log10(tick_step))
        if tick_step / power < 1.5:
            return power
        elif tick_step / power < 3:
            return 2 * power
        elif tick_step / power < 7:
            return 5 * power
        else:
            return 10 * power

    def _format_tick_label(self, value: float, unit: float, suffix: str) -> str:
        """Formats a single tick label with the appropriate unit and prefix."""
        if abs(value) < 1:
            return "¥0"

        opr = "" if value >= 0 else "-"
        val_in_unit = abs(value / unit)
        if val_in_unit == int(val_in_unit):
            return f"{opr}¥{int(val_in_unit):,}{suffix}"
        else:
            return f"{opr}¥{val_in_unit:,.1f}{suffix}"

    def _format_yaxis_ticks(
        self, fig: go.Figure, ymax_override: float | None = None
    ) -> dict[str, Any]:
        """
        Format y-axis ticks to use '万' or '億' units.
        """
        try:
            range_val = self._get_yaxis_range(fig, ymax_override)
            if not range_val:
                return {}
            ymin, ymax = range_val

            if ymax < 10000:
                return {}

            unit, suffix = (
                (100_000_000, "億") if ymax >= 100_000_000 else (10_000, "万")
            )

            tick_step = self._calculate_tick_step(ymin, ymax)
            if tick_step <= 0:
                return {}

            import math

            start = math.floor(ymin / tick_step) * tick_step

            tickvals = []
            val = start
            while val <= ymax * 1.01:
                tickvals.append(val)
                val += tick_step

            if not tickvals:
                return {}

            ticktext = [
                self._format_tick_label(
                    v,
                    10_000 if abs(v) < 100_000_000 else unit,
                    "万" if abs(v) < 100_000_000 else suffix,
                )
                for v in tickvals
            ]

            return {
                "tickvals": tickvals,
                "ticktext": ticktext,
                "tickprefix": None,
                "tickformat": None,
            }

        except Exception as e:
            log.warning(f"Failed to apply custom y-axis formatting: {e}")
            return {}

    def _update_layout(
        self,
        fig: go.Figure,
        theme: str,
        ymax_for_format: float | None = None,
        yaxis_type: str = "linear",
        uniformtext: dict = dict(minsize=10, mode="hide"),
    ) -> None:
        yaxis_settings = {
            "autorange": True,
            "fixedrange": False,
            "tickprefix": "¥",
            "tickformat": ",",
            "type": yaxis_type,
        }
        yaxis_settings.update(**self._format_yaxis_ticks(fig, ymax_for_format))
        fig.update_layout(
            height=500,
            xaxis_title="",
            yaxis_title="",
            title_y=0.98,
            legend_title="",
            xaxis=dict(fixedrange=True),
            yaxis=yaxis_settings,
            dragmode=False,
            legend=dict(orientation="h"),
            margin=dict(l=10, r=10, t=50, b=0),
            paper_bgcolor="#1f2937" if theme == "dark" else "#ffffff",
            plot_bgcolor="#1f2937" if theme == "dark" else "#ffffff",
            template="plotly_dark" if theme == "dark" else "plotly_white",
            uniformtext=uniformtext,
        )

    def generate_daily_chart(
        self,
        df_org: pd.DataFrame,
        target_month: str | None = None,
        theme: str = "light",
        min_yrange: int = 50000,
        include_plotlyjs: bool | str = True,
    ) -> tuple[str, list[str]]:
        """
        累積折れ線グラフを生成
        """
        log.info("start 'generate_daily_chart' method")
        df = df_org.copy()
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return "", []

        today = pd.Timestamp(dt.date.today())
        df.query("expense_type in @self.variable_types", inplace=True)
        df["date"] = pd.to_datetime(df["date"])
        unique_months = sorted(
            df["date"].dt.to_period("M").unique(), reverse=True
        )
        available_months = [m.strftime("%Y-%m") for m in unique_months]

        if not unique_months:
            return "", []

        log.debug(f"target_month: {target_month}")
        target_period = (
            pd.Period(target_month, "M") if target_month else unique_months[0]
        )

        t = target_period.to_timestamp()
        month_start, month_end = self._get_month_boundaries(t)
        df_graph = self._prepare_graph_dataframe(df, month_start, month_end)

        if df_graph.empty:
            # Return empty graph but with available months for dropdown
            return "", available_months

        df_bar = self._prepare_bar_dataframe(df_graph)
        df_graph = self._add_month_start_point(df_graph, month_start)
        df_graph, df_predict = self._handle_predictions(
            df_graph, today, month_start, month_end
        )
        fig = self._create_bar_figure(
            df_bar,
            month_start,
            month_end,
            min_yrange,
            df_graph,
            df_predict,
            theme,
        )
        fig_line = self._create_line_figure(df_graph, theme)
        fig_predict = self._create_prediction_figure(df_predict, theme)
        self._update_traces(fig, fig_line, fig_predict)

        fig.add_traces(fig_line.data)
        if today.to_period("M") == target_period:
            fig.add_traces(fig_predict.data)

        self._add_bar_chart_labels(
            fig,
            df_bar,
            "date",
            theme,
            fontsize=10,
            label_nlags=3,
            label_threshold=max(fig.layout.yaxis.range[1] * 0.02, 1000),
            label_offset=max(fig.layout.yaxis.range[1] * 0.04, 2000),
        )

        self._update_layout(fig, theme)
        fig.update_layout(
            barmode="stack",
            yaxis=dict(fixedrange=True),
        )

        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        graph_html = f'<div style="-webkit-tap-highlight-color: transparent;">{graph_html}</div>'
        log.info("end 'generate_daily_chart' method")
        return graph_html, available_months

    def generate_pie_chart(
        self,
        df: pd.DataFrame,
        df_records: pd.DataFrame,
        target_month: str | None = None,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
    ) -> tuple[str, list[str]]:
        """
        円グラフを生成
        """
        log.info("start 'generate_pie_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return "", []

        df_pie = df.copy()
        _df_records = df_records.copy()
        df_pie.query(
            "expense_type in @self.fixed_types or expense_type in @self.variable_types",
            inplace=True,
        )
        _df_records.query(
            "expense_type in @self.fixed_types or expense_type in @self.variable_types",
            inplace=True,
        )
        date_index = pd.to_datetime(_df_records["date"])
        _, t_month_end = self._get_month_boundaries(dt.datetime.today())
        date_index = date_index[date_index <= t_month_end]
        unique_months = sorted(
            date_index.dt.to_period("M").unique(),
            reverse=True,
        )
        available_months = [m.strftime("%Y-%m") for m in unique_months]

        if not unique_months:
            return "", []

        target_month_str = target_month if target_month else available_months[0]
        log.debug(f"target_month_str: {target_month_str}")
        target_period = pd.Period(target_month_str, "M")

        t = target_period.to_timestamp()
        df_pie_this_month = df_pie.loc[
            df_pie.loc[:, "month"] == t.strftime("%Y-%m")
        ]

        if df_pie_this_month.empty:
            log.info(
                f"DataFrame (df_pie_this_month of {target_period}) is empty, skipping graph generation."
            )
            return "", available_months

        month_start, month_end = self._get_month_boundaries(t)
        df_records_this_month = self._prepare_graph_dataframe(
            _df_records, month_start, month_end
        )
        n_records = df_records_this_month.shape[0]
        total_amount = df_pie_this_month["expense_amount"].sum()

        fig = px.pie(
            df_pie_this_month,
            names="expense_type",
            values="expense_amount",
            color="expense_type",
            custom_data=["expense_type", "expense_memo"],
            category_orders={"expense_type": self.expense_types},
            color_discrete_map=self.graph_color,
            opacity=0.8,
            hole=0.4,
            template="plotly_dark" if theme == "dark" else "plotly_white",
        )
        fig.update_traces(
            texttemplate="%{label}<br>¥%{value:,.0f}<br>(%{percent})",
            hovertemplate="¥%{value:,.0f} (%{percent}), %{customdata[0]}",
            textfont=dict(size=14),
            textposition="inside",
            insidetextorientation="horizontal",
            showlegend=False,
        )
        fig.add_trace(
            go.Scatter(
                x=[0.5],
                y=[0.5],
                text=[f"合計<br>¥{total_amount: ,.0f}<br>({int(n_records)}件)"],
                mode="text",
                textposition="middle center",
                textfont=dict(
                    size=20,
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                showlegend=False,
                hoverinfo="skip",
            )
        )

        self._update_layout(fig, theme)
        fig.update_layout(
            title_text=f"支出内訳（{target_period.strftime('%Y年%-m月')}）",
            uniformtext=dict(minsize=14, mode="hide"),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_pie_chart' method")
        return graph_html, available_months

    def generate_monthly_bar_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        max_monthes: int = 6,
        include_plotlyjs: bool | str = True,
    ) -> str:
        """
        月別の棒グラフを生成
        """
        log.info("start 'generate_monthly_bar_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_graph = df.copy()
        df_graph.query(
            "expense_type in @self.fixed_types or expense_type in @self.variable_types",
            inplace=True,
        )
        for i, r in df_graph.iterrows():
            df_graph.at[i, "label"] = (
                f"{r['expense_type']}<br>¥{r['expense_amount']:,.0f}"
            )
        df_graph["month"] = pd.to_datetime(df_graph["month"], format="%Y-%m")

        # 収入を月ごとに集計
        df_income = df.query("expense_type in @self.income_types").copy()
        df_income["month"] = pd.to_datetime(df_income["month"], format="%Y-%m")
        df_income = (
            df_income.groupby("month", as_index=False)["expense_amount"]
            .sum()
            .rename(columns={"expense_amount": "income_amount"})
        )
        df_income["label"] = df_income["income_amount"].map(
            lambda x: f"収入<br>¥{x:,.0f}"
        )

        # 支出を月ごとに集計
        df_expense = (
            df_graph.groupby("month", as_index=False)["expense_amount"]
            .sum()
            .rename(columns={"expense_amount": "expense_amount"})
        )

        # CF = 収入 - 支出
        df_cf = (
            df_income.merge(df_expense, on="month", how="left")
            .fillna({"expense_amount": 0})
            .sort_values("month")
        )
        df_cf["cf"] = df_cf["income_amount"] - df_cf["expense_amount"]
        df_cf["cf_positive"] = df_cf["cf"].clip(lower=0)
        df_cf["cf_negative"] = (-df_cf["cf"]).clip(lower=0)

        df_cf["expense_base"] = df_cf["expense_amount"]
        df_cf["income_base"] = df_cf["income_amount"]

        df_cf["cf_positive_label"] = df_cf["cf_positive"].apply(
            lambda x: f"ｷｬｯｼｭﾌﾛｰ<br>¥{x:,.0f}" if x > 0 else ""
        )
        df_cf["cf_negative_label"] = df_cf["cf_negative"].apply(
            lambda x: f"ｷｬｯｼｭﾌﾛｰ<br>-¥{x:,.0f}" if x > 0 else ""
        )
        df_cf["cf_text"] = df_cf["cf"].apply(
            lambda x: f"-¥{abs(x):,.0f}" if x < 0 else f"+¥{x:,.0f}"
        )

        ymax = 0
        if not df_graph.empty:
            ymax = df_graph.groupby("month")["expense_amount"].sum().max()
        if not df_income.empty:
            _ymax = df_income.groupby("month")["income_amount"].sum().max()
            ymax = _ymax if _ymax > ymax else ymax
        ymax *= 1.2

        fig = px.bar(
            df_graph,
            x="month",
            y="expense_amount",
            color="expense_type",
            text="label",
            title="月別収支",
            hover_data=["expense_memo"],
            range_y=[0, None],
            category_orders={"expense_type": self.expense_types},
            color_discrete_map=self.graph_color,
            opacity=0.5,
            # NOTE: テンプレートを明示的に指定しないと、稀に無限ループ→Invalid valueエラーが発生することがある
            template="plotly_dark" if theme == "dark" else "plotly_white",
        )
        fig.update_traces(
            texttemplate="%{text}",
            hovertemplate="%{x|%-Y年%-m月}<br>¥%{value:,.0f}%{customdata[0]}",
            textfont=dict(size=14),
            textposition="inside",
            textangle=0,
        )
        # 支出を左側の棒にする
        for trace in fig.data:
            trace.offsetgroup = "expense"

        # 収入を右側の棒として追加
        fig.add_trace(
            go.Bar(
                x=df_income["month"],
                y=df_income["income_amount"],
                name="収入",
                offsetgroup="income",
                marker_color="#4466bb" if theme == "dark" else "#6699ee",
                text=df_income["label"],
                texttemplate="%{text}",
                textposition="inside",
                textangle=0,
                hovertemplate="%{x|%-Y年%-m月}<br>税引後収入: ¥%{y:,.0f}<extra></extra>",
            )
        )

        # キャッシュフローを追加
        # CF(プラス): 支出の上に積み上げ
        fig.add_trace(
            go.Bar(
                x=df_cf["month"],
                y=df_cf["cf_positive"],
                offsetgroup="expense",
                name="ｷｬｯｼｭﾌﾛｰ",
                marker_color="#baa44b" if theme == "dark" else "#eecc55",
                customdata=df_cf["cf_text"],
                hovertemplate="%{x|%-Y年%-m月}<br>ｷｬｯｼｭﾌﾛｰ: %{customdata}<extra></extra>",
                text=df_cf["cf_positive_label"],
                texttemplate="%{text}",
                textposition="inside",
                textangle=0,
                legendgroup="CF",
            )
        )
        # CF(マイナス): 収入の上に積み上げ
        fig.add_trace(
            go.Bar(
                x=df_cf["month"],
                y=df_cf["cf_negative"],
                offsetgroup="income",
                name="ｷｬｯｼｭﾌﾛｰ",
                marker_color="#bb3333" if theme == "dark" else "#ee5555",
                customdata=df_cf["cf_text"],
                hovertemplate="%{x|%-Y年%-m月}<br>ｷｬｯｼｭﾌﾛｰ: %{customdata}<extra></extra>",
                text=df_cf["cf_negative_label"],
                texttemplate="%{text}",
                textposition="inside",
                textangle=0,
                showlegend=False,
                legendgroup="CF",
            )
        )

        # 支出の合計を折れ線として追加
        fig.add_trace(
            go.Scatter(
                x=df_expense["month"],
                y=df_expense["expense_amount"],
                mode="lines+markers",
                name="支出",
                line=dict(
                    color="#999999" if theme == "dark" else "#666666",
                    dash="solid",
                    width=0.5,
                ),
                marker=dict(size=4),
                hovertemplate="%{x|%-Y年%-m月}<br>支出: ¥%{y:,.0f}<extra></extra>",
            )
        )

        self._add_bar_chart_labels(
            fig,
            df_graph,
            "month",
            theme,
            fontsize=12,
            label_threshold=10_000,
            label_offset=30_000,
            offsetgroup="expense",
        )

        self._update_layout(fig, theme, ymax_for_format=ymax)
        fig.update_layout(
            dragmode="pan",
        )

        cutoff_date = dt.datetime.today() - dt.timedelta(
            days=30 * (max_monthes - 1)
        )
        cutoff_date_str: str = cutoff_date.strftime("%Y-%m-01")
        fig.update_xaxes(
            fixedrange=False,
            range=[cutoff_date_str, df_graph["month"].iloc[-1]],
        )
        fig.update_yaxes(
            fixedrange=True,
        )
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_monthly_bar_chart' method")
        return graph_html

    def generate_annual_fiscal_report_chart(
        self,
        df_records: pd.DataFrame,
        target_year: str | None = None,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
    ) -> tuple[str, list[str]]:
        """
        年度の収支サマリのレポートグラフを生成
        """
        log.info("start 'generate_annual_fiscal_report_chart' method")
        if df_records.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return "", []

        today = pd.Timestamp(dt.date.today())
        df_annual = df_records.copy()
        df_annual["date"] = pd.to_datetime(df_annual["date"], errors="coerce")
        df_annual["expense_amount"] = pd.to_numeric(
            df_annual["expense_amount"], errors="coerce"
        )
        df_annual.dropna(subset=["date", "expense_amount"], inplace=True)
        df_annual["date"] = df_annual["date"].dt.normalize()
        df_annual = df_annual.loc[
            df_annual["expense_type"].isin(
                self.income_types + self.fixed_types + self.variable_types
            )
        ].copy()
        if df_annual.empty:
            return "", []

        df_annual["income"] = df_annual["expense_amount"].where(
            df_annual["expense_type"].isin(self.income_types), 0
        )
        df_annual["expense"] = df_annual["expense_amount"].where(
            df_annual["expense_type"].isin(
                self.fixed_types + self.variable_types
            ),
            0,
        )
        df_history = df_annual.copy()
        fiscal_years = df_annual["date"].dt.year - (
            df_annual["date"].dt.month < 4
        ).astype(int)
        current_fiscal_year = today.year - int(today.month < 4)
        available_years = sorted(
            set(fiscal_years.unique()) | {current_fiscal_year}, reverse=True
        )
        available_year_strings = [str(year) for year in available_years]
        fiscal_year = (
            int(target_year)
            if target_year in available_year_strings
            else available_years[0]
        )
        fiscal_start = pd.Timestamp(fiscal_year, 4, 1)
        fiscal_end = (
            today
            if fiscal_year == current_fiscal_year
            else pd.Timestamp(fiscal_year + 1, 3, 31)
        )
        df_annual = df_annual.loc[
            (df_annual["date"] >= fiscal_start)
            & (df_annual["date"] <= fiscal_end)
        ]
        if fiscal_year == current_fiscal_year:
            df_completed = df_annual
            elapsed_days = max(1, (today - fiscal_start).days + 1)
            fiscal_days = (
                pd.Timestamp(fiscal_year + 1, 4, 1) - fiscal_start
            ).days
        else:
            df_completed = df_annual
            fiscal_days = (
                pd.Timestamp(fiscal_year + 1, 4, 1) - fiscal_start
            ).days
            elapsed_days = fiscal_days

        income = int(
            df_completed.loc[
                df_completed["expense_type"].isin(self.income_types),
                "expense_amount",
            ].sum()
        )
        expense = -int(
            df_completed.loc[
                df_completed["expense_type"].isin(
                    self.fixed_types + self.variable_types
                ),
                "expense_amount",
            ].sum()
        )
        actual = [
            income,
            expense,
        ]
        actual.append(actual[0] + actual[1])
        labels = ["収入", "支出", "ｷｬｯｼｭﾌﾛｰ"]

        # 全履歴から算出した加重日平均で、明日以降を予測する。
        weighted_income, weighted_expense = (
            self._calculate_weighted_daily_rates(df_history, today)
        )
        remaining_days = fiscal_days - elapsed_days
        forecast_total = [
            int(actual[0] + weighted_income * remaining_days),
            int(actual[1] - weighted_expense * remaining_days),
            int(
                actual[0]
                + actual[1]
                + (weighted_income - weighted_expense) * remaining_days
            ),
        ]
        forecast = [
            total - amount for total, amount in zip(forecast_total, actual)
        ]

        income, expense, cash_flow = actual
        forecast_bases = [income, expense, cash_flow]
        actual_bases = [0, 0, 0]
        actual_colors = [
            "#4466bb" if theme == "dark" else "#6699ee",
            "#bb3333" if theme == "dark" else "#ee5555",
            "#baa44b" if theme == "dark" else "#eecc55",
        ]
        forecast_colors = [
            (
                "rgba(68, 102, 187, 0.35)"
                if theme == "dark"
                else "rgba(102, 153, 238, 0.45)"
            ),
            (
                "rgba(187, 51, 51, 0.35)"
                if theme == "dark"
                else "rgba(238, 85, 85, 0.45)"
            ),
            (
                "rgba(186, 164, 75, 0.35)"
                if theme == "dark"
                else "rgba(238, 204, 85, 0.45)"
            ),
        ]

        def signed_amount(amount: int) -> str:
            operator = "+" if amount >= 0 else "-"
            return f"{operator}¥{abs(amount):,.0f}"

        def amount_label(label: str, amount: int, prefix: str = "") -> str:
            return f"{prefix}{label}<br>{signed_amount(amount)}"

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=labels,
                y=actual,
                base=actual_bases,
                marker_color=actual_colors,
                text=[
                    amount_label(label, amount)
                    for label, amount in zip(labels, actual)
                ],
                textposition="inside",
                insidetextanchor="middle",
                textangle=0,
                textfont=dict(
                    size=14,
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                constraintext="none",
                hovertemplate=[
                    f"{label}<br>実績: {signed_amount(amount)}<extra></extra>"
                    for label, amount in zip(labels, actual)
                ],
                name="実績",
                showlegend=True,
            )
        )
        fig.add_trace(
            go.Bar(
                x=labels,
                y=forecast,
                base=forecast_bases,
                marker_color=forecast_colors,
                text=[
                    amount_label("年間予測", total)
                    for label, total in zip(labels, forecast_total)
                ],
                textposition="inside",
                insidetextanchor="middle",
                textangle=0,
                textfont=dict(
                    size=14,
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                constraintext="none",
                hovertemplate=[
                    f"{label}<br>年間予測: {signed_amount(total)}"
                    f"<br>残り予測: {signed_amount(amount)}<extra></extra>"
                    for label, total, amount in zip(
                        labels, forecast_total, forecast
                    )
                ],
                name="年間予測",
                showlegend=True,
            )
        )
        endpoints = (
            actual_bases
            + forecast_bases
            + [actual_bases[i] + actual[i] for i in range(len(actual))]
            + [forecast_bases[i] + forecast[i] for i in range(len(forecast))]
        )
        ymin = min(0, min(endpoints)) * 1.1
        ymax = max(0, max(endpoints)) * 1.1
        fig.update_xaxes(showline=False, showticklabels=False, showgrid=False)
        fig.update_yaxes(range=(ymin, ymax))
        self._update_layout(fig, theme, ymax_for_format=ymax)
        fig.update_layout(
            title=f"{fiscal_year}年度の収支サマリ",
            barmode="overlay",
            bargap=0.4,
            height=400,
            showlegend=False,
            legend=dict(
                orientation="h",
                y=0.0,
                x=0.5,
                xanchor="center",
            ),
            margin=dict(b=0),
        )
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_annual_fiscal_report_chart' method")
        return graph_html, available_year_strings

    def generate_fiscal_asset_history_chart(
        self,
        df: pd.DataFrame,
        target_year: str | None = None,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
    ) -> tuple[str, list[str]]:
        """今年度の収入・支出・収支の累積推移を生成する。"""
        log.info("start 'generate_fiscal_asset_history_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return "", []

        today = pd.Timestamp(dt.date.today())
        df_graph = df.copy()
        df_graph["date"] = pd.to_datetime(df_graph["date"], errors="coerce")
        df_graph["expense_amount"] = pd.to_numeric(
            df_graph["expense_amount"], errors="coerce"
        )
        df_graph.dropna(subset=["date", "expense_amount"], inplace=True)
        df_graph = df_graph.loc[
            df_graph["expense_type"].isin(
                self.income_types + self.fixed_types + self.variable_types
            )
        ].copy()
        if df_graph.empty:
            log.info("No records for the fiscal asset history graph.")
            return "", []

        df_graph["date"] = df_graph["date"].dt.normalize()
        df_graph["income"] = df_graph["expense_amount"].where(
            df_graph["expense_type"].isin(self.income_types), 0
        )
        df_graph["expense"] = df_graph["expense_amount"].where(
            df_graph["expense_type"].isin(
                self.fixed_types + self.variable_types
            ),
            0,
        )
        # 予測には、選択年度に限らず過去の記録も周期性の学習に使う。
        df_history = df_graph.copy()
        fiscal_years = df_graph["date"].dt.year - (
            df_graph["date"].dt.month < 4
        ).astype(int)
        current_fiscal_year = today.year - int(today.month < 4)
        available_years = sorted(
            set(fiscal_years.unique()) | {current_fiscal_year}, reverse=True
        )
        available_year_strings = [str(year) for year in available_years]
        fiscal_year = (
            int(target_year)
            if target_year in available_year_strings
            else available_years[0]
        )
        fiscal_start = pd.Timestamp(fiscal_year, 4, 1)
        fiscal_end = pd.Timestamp(fiscal_year + 1, 3, 31)
        actual_end = today if fiscal_year == current_fiscal_year else fiscal_end
        df_history = df_history.loc[df_history["date"] <= actual_end]
        df_graph = df_graph.loc[
            (df_graph["date"] >= fiscal_start)
            & (df_graph["date"] <= actual_end)
        ]
        if df_graph.empty:
            log.info("No records in the selected fiscal year.")
            return "", available_year_strings

        daily = (
            df_graph.groupby("date")[["income", "expense"]]
            .sum()
            .reindex(pd.date_range(fiscal_start, actual_end), fill_value=0)
        )
        daily["income_cumulative"] = daily["income"].cumsum()
        daily["expense_cumulative"] = daily["expense"].cumsum()
        daily["balance"] = (
            daily["income_cumulative"] - daily["expense_cumulative"]
        )
        daily["cash_flow"] = daily["income"] - daily["expense"]

        colors = (
            ["#6699ee", "#ee5555", "#eecc55"]
            if theme != "dark"
            else ["#4466bb", "#bb3333", "#baa44b"]
        )
        fig = go.Figure()
        forecast_y_values: list[np.ndarray] = []
        for column, name, color in zip(
            ["income_cumulative", "expense_cumulative", "balance"],
            ["収入", "支出", "ｷｬｯｼｭﾌﾛｰ"],
            colors,
        ):
            fig.add_trace(
                go.Scatter(
                    x=daily.index,
                    y=daily[column],
                    mode="lines",
                    name=name,
                    line=dict(color=color, shape="hv", width=2),
                    hovertemplate=(
                        "%{x|%-Y年%-m月%-d日}<br>"
                        f"{name}: ¥%{{y:,.0f}}<extra></extra>"
                    ),
                )
            )

        if fiscal_year == current_fiscal_year and actual_end < fiscal_end:
            forecast_dates = pd.date_range(
                actual_end + pd.Timedelta(days=1), fiscal_end
            )
            history_daily = (
                df_history.groupby("date")[["income", "expense"]]
                .sum()
                .reindex(
                    pd.date_range(
                        df_history["date"].min(), actual_end, freq="D"
                    ),
                    fill_value=0,
                )
            )
            # 月による季節変動は使わず、直近ほど重くした日番号ごとの
            # 典型的な1か月を作る。
            age_days = (actual_end - history_daily.index).days.to_numpy()
            pattern_weights = np.exp(
                -np.log(2) * age_days / self._FORECAST_HALF_LIFE_DAYS
            )
            weighted_values = history_daily[["income", "expense"]].mul(
                pattern_weights, axis=0
            )
            pattern_days = history_daily.index.day
            weight_totals = (
                pd.Series(pattern_weights, index=history_daily.index)
                .groupby(pattern_days)
                .sum()
            )
            daily_pattern = (
                weighted_values.groupby(pattern_days)
                .sum()
                .div(
                    weight_totals,
                    axis=0,
                )
            )
            overall_pattern = history_daily[["income", "expense"]].mean()
            weighted_income, weighted_expense = (
                self._calculate_weighted_daily_rates(df_history, actual_end)
            )

            # 周期パターンの合計を従来の線形予測の合計へ合わせ、年度末を固定する。
            forecast_increments: dict[str, np.ndarray] = {}
            pattern_index = forecast_dates.day
            for daily_column in ["income", "expense"]:
                pattern_values = daily_pattern.reindex(pattern_index)[
                    daily_column
                ].to_numpy(dtype=float)
                pattern_values = np.nan_to_num(
                    pattern_values, nan=float(overall_pattern[daily_column])
                )
                weighted_rate = (
                    weighted_income
                    if daily_column == "income"
                    else weighted_expense
                )
                target_total = weighted_rate * len(forecast_dates)
                pattern_total = pattern_values.sum()
                if pattern_total:
                    pattern_values *= target_total / pattern_total
                else:
                    pattern_values.fill(target_total / len(forecast_dates))
                forecast_increments[daily_column] = pattern_values

            for column, daily_column, name, color in zip(
                ["income_cumulative", "expense_cumulative", "balance"],
                ["income", "expense", "cash_flow"],
                ["収入", "支出", "ｷｬｯｼｭﾌﾛｰ"],
                colors,
            ):
                if daily_column == "cash_flow":
                    increments = (
                        forecast_increments["income"]
                        - forecast_increments["expense"]
                    )
                else:
                    increments = forecast_increments[daily_column]
                forecast_values = daily[column].iloc[-1] + np.cumsum(increments)
                forecast_y_values.append(forecast_values)
                fig.add_trace(
                    go.Scatter(
                        x=forecast_dates,
                        y=forecast_values,
                        mode="lines",
                        name=f"{name}（予測）",
                        line=dict(
                            color=color,
                            dash="dot",
                            shape="hv",
                            width=1.5,
                        ),
                        hovertemplate=(
                            "%{x|%-Y年%-m月%-d日}<br>"
                            f"{name}（予測）: ¥%{{y:,.0f}}<extra></extra>"
                        ),
                    )
                )

        y_values = daily[
            [
                "income_cumulative",
                "expense_cumulative",
                "balance",
            ]
        ].to_numpy()
        if fiscal_year == current_fiscal_year and actual_end < fiscal_end:
            y_values = np.concatenate([y_values, np.array(forecast_y_values).T])
        y_min = float(y_values.min())
        y_max = float(y_values.max())
        y_margin = max((y_max - y_min) * 0.1, 1)
        fig.update_layout(
            title=f"{target_year if target_year else '今'}年度の収支推移",
            hovermode="x unified",
            xaxis=dict(
                range=[fiscal_start, fiscal_end],
                fixedrange=True,
                showspikes=True,
                spikemode="across",
                spikecolor="#ffffff" if theme == "dark" else "#000000",
                spikethickness=1,
                spikedash="dot",
            ),
            yaxis=dict(range=[y_min - y_margin, y_max + y_margin]),
        )
        self._update_layout(fig, theme, ymax_for_format=max(abs(y_min), y_max))
        fig.update_xaxes(range=[fiscal_start, fiscal_end], fixedrange=True)
        fig.update_yaxes(
            range=[y_min - y_margin, y_max + y_margin], fixedrange=True
        )
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(responsive=True, displayModeBar=False),
        )
        log.info("end 'generate_fiscal_asset_history_chart' method")
        return graph_html, available_year_strings

    def generate_asset_pie_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
    ) -> str:
        """
        ポートフォリオの円グラフを生成
        """
        log.info("start 'generate_asset_pie_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_pie = df.copy()
        df_pie["ticker"] = [s.replace("(", "<br>(") for s in df_pie["ticker"]]
        graph_color = {
            k.replace("(", "<br>("): self.graph_color[k]
            for k in self.graph_color
        }
        total = int(df_pie["valuation"].sum())
        fig = px.pie(
            df_pie,
            names="ticker",
            values="valuation",
            color="ticker",
            title="ポートフォリオ",
            category_orders={"ticker": df_pie["ticker"].to_list()},
            color_discrete_map=graph_color,
            opacity=0.8,
            hole=0.5,
            # NOTE: テンプレートを明示的に指定しないと、稀に無限ループ→Invalid valueエラーが発生することがある
            template="plotly_dark" if theme == "dark" else "plotly_white",
        )
        fig.update_traces(
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="%{label}<br>¥%{value:,.0f}<br>(%{percent})",
            textfont=dict(size=12),
            textposition="inside",
            insidetextorientation="horizontal",
            showlegend=False,
        )
        fig.add_annotation(
            text=f"合計<br>¥{total: ,}",
            x=0.5,
            y=0.5,
            font_size=16,
            showarrow=False,
            font=dict(
                color="#ffffff" if theme == "dark" else "#000000",
                size=20,
                weight="bold",
            ),
        )
        self._update_layout(fig, theme)
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_asset_pie_chart' method")
        return graph_html

    def generate_asset_heatmap_chart(
        self,
        df: pd.DataFrame,
        total_value: int | None = None,
        total_change_pct: float | None = None,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
    ) -> str:
        log.info("start 'generate_asset_heatmap_chart' method")
        df_graph = df.copy()
        df_graph["change_pct"] = pd.to_numeric(
            df_graph["change_pct_yen"], errors="coerce"
        )
        df_graph["label_text"] = df_graph.apply(
            lambda r: f"{r['ticker']}<br>{r['change_pct']:+.2f}%", axis=1
        )
        df_graph["hover_text"] = df_graph.apply(
            lambda r: f"{r['ticker']}<br>¥{r['valuation']:,.0f} (前日比 {r['change_pct']:+.2f}%)",
            axis=1,
        )
        if not total_value:
            total_value = int(df_graph["valuation"].sum())
        root_label = f"合計資産<br>{total_change_pct:+,.2f}%"
        df_graph["total"] = root_label
        df_root = pd.DataFrame(
            {
                "ticker": [root_label],
                "total": [""],
                "valuation": [0],
                "change_pct": [total_change_pct],
                "label_text": [""],
                "hover_text": [
                    f"合計資産<br>¥{total_value:,.0f} (前日比 {total_change_pct:+,.2f}%)"
                ],
            }
        )
        df_graph = pd.concat([df_root, df_graph], ignore_index=True)
        colorscale_light = [
            [0.0, "#e74c3c"],
            [0.2, "#e74c3c"],
            [0.2, "#ef9a9a"],
            [0.4, "#ef9a9a"],
            [0.4, "#e0e0e0"],
            [0.6, "#e0e0e0"],
            [0.6, "#a5d6a7"],
            [0.8, "#a5d6a7"],
            [0.8, "#2ecc71"],
            [1.0, "#2ecc71"],
        ]
        colorscale_dark = [
            [0.0, "#aa3342"],
            [0.2, "#aa3342"],
            [0.2, "#663342"],
            [0.4, "#663342"],
            [0.4, "#2f3342"],
            [0.6, "#2f3342"],
            [0.6, "#2f5042"],
            [0.8, "#2f5042"],
            [0.8, "#2f7742"],
            [1.0, "#2f7742"],
        ]
        fig = go.Figure(
            go.Treemap(
                labels=df_graph["ticker"],
                parents=df_graph["total"],
                values=df_graph["valuation"],
                marker=dict(
                    colors=df_graph["change_pct"],
                    coloraxis="coloraxis",
                    line=dict(width=1),
                ),
                customdata=df_graph[["label_text", "hover_text"]].values,
                texttemplate="%{customdata[0]}",
                hovertemplate="%{customdata[1]}<extra></extra>",
                textfont=dict(
                    color="white" if theme == "dark" else "black",
                    size=18,
                ),
                textposition="middle center",
                maxdepth=2,
                tiling=dict(pad=0),
                pathbar=dict(visible=False),
            )
        )
        self._update_layout(fig, theme, uniformtext={})
        fig.update_layout(
            title="資産ヒートマップ",
            coloraxis=dict(
                colorscale=(
                    colorscale_dark if theme == "dark" else colorscale_light
                ),
                cmin=-1.25,
                cmax=1.25,
                cmid=0,
                colorbar=dict(
                    title="前日比",
                    x=0.5,
                    y=-0.1,
                    len=1.0,
                    thickness=5,
                    orientation="h",
                    tickformat=".1f",
                    ticksuffix="%",
                ),
            ),
        )
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_asset_heatmap_chart' method")
        return graph_html

    def generate_asset_waterfall_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
    ) -> str:
        """
        銘柄別の含み益を表すウォーターフォールチャートを生成
        """
        log.info("start 'generate_asset_waterfall_chart' method")
        df_graph = df.copy()
        invest_amount_total = df_graph["invest_amount"].sum()
        idx = df_graph[df_graph["ticker"].str.contains("現金")].index.to_list()
        df_graph.drop(idx, inplace=True)
        x = df_graph["ticker"].to_list() + ["合計"]
        x = [s.replace("(", "<br>(") for s in x]
        y = df_graph["profit"].to_list() + [df_graph["profit"].sum()]
        opr = ["+" if v >= 0 else "-" for i, v in enumerate(y)]
        roi_total = (
            y[-1] / invest_amount_total * 100 if invest_amount_total > 0 else 0
        )
        roi = [r["roi"] for _, r in df_graph.iterrows()] + [roi_total]

        profits = df_graph["profit"]
        cum_profits = profits.cumsum()
        total_profit = profits.sum()
        ymax = max(
            0, cum_profits.max() if not cum_profits.empty else 0, total_profit
        )

        fig = go.Figure(
            go.Waterfall(
                orientation="v",
                x=x,
                y=y,
                measure=["relative"] * len(df_graph) + ["total"],
                increasing=dict(
                    marker=dict(
                        color="#4466bb" if theme == "dark" else "#6699ee"
                    )
                ),
                decreasing=dict(
                    marker=dict(
                        color="#bb3333" if theme == "dark" else "#ee5555"
                    )
                ),
                totals=dict(
                    marker=dict(
                        color="#666666" if theme == "dark" else "#bbbbbb"
                    )
                ),
                connector=dict(
                    line=dict(
                        color="#ffffff" if theme == "dark" else "#000000",
                        width=0.2,
                        dash="dot",
                    )
                ),
                text=[
                    f"{x[i]}<br>{opr[i]}¥{abs(v):,.0f}<br>({opr[i]}{abs(roi[i]):.2f}%)"
                    for i, v in enumerate(y)
                ],
                textposition="none",
                hoverinfo="text",
            )
        )
        for i, v in enumerate(y):
            if i < len(y) - 1:
                _y = sum(y[:i]) + y[i] // 2
            else:
                _y = y[-1] // 2
            fig.add_annotation(
                x=x[i],
                y=_y,
                text=f"{x[i]}<br>{opr[i]}¥{abs(v):,.0f}",
                showarrow=False,
                font=dict(
                    size=10, color="#ffffff" if theme == "dark" else "#000000"
                ),
            )
        fig.update_xaxes(showline=False, showticklabels=False, showgrid=False)
        self._update_layout(fig, theme, ymax_for_format=ymax)
        fig.update_layout(title="含み益 内訳", waterfallgap=0.4, height=400)
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_asset_waterfall_chart' method")
        return graph_html

    def generate_asset_monthly_history_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        include_plotlyjs: bool | str = True,
        simulation_annual_yield: float = 0.0,
        simulation_monthly_investment: float = 0.0,
        simulation_years: float = 0,
    ) -> str:
        """
        月単位の資産推移チャートを生成
        """
        log.info("start 'generate_asset_monthly_history_chart' method")
        df_graph = df.copy()
        opr = ["+" if r["profit"] >= 0 else "-" for _, r in df_graph.iterrows()]
        roi = [r["roi"] for _, r in df_graph.iterrows()]

        ymax = 0
        if not df_graph.empty:
            ymax = df_graph["valuation"].max()

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df_graph["date"],
                y=df_graph["valuation"],
                name="評価額",
                hovertext=[
                    (
                        f"{x.strftime('%Y年%-m月%-d日')}<br>"
                        f"<b>評価額 ¥{y:,.0f}</b>"
                        f"<br>  (含み益 {o}¥{abs(p):,.0f} ／ 損益率 {r:+.2f}%)"
                    )
                    for x, y, p, o, r in zip(
                        df_graph["date"],
                        df_graph["valuation"],
                        df_graph["profit"],
                        opr,
                        roi,
                    )
                ],
                hoverinfo="text",
                mode="lines",
                line=dict(
                    width=1.5, color="#3355bb" if theme == "dark" else "#4466cc"
                ),
                fill="tozeroy",
                fillcolor=(
                    "rgba(120, 160, 255, 0.6)"
                    if theme == "dark"
                    else "rgba(50, 80, 200, 0.6)"
                ),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_graph["date"],
                y=df_graph["invest_amount"],
                name="投資額",
                hovertext=[
                    f"投資額 ¥{y:,.0f}" for y in df_graph["invest_amount"]
                ],
                hoverinfo="text",
                mode="lines",
                line=dict(
                    width=3, color="#bb4433" if theme == "dark" else "#dd6644"
                ),
            )
        )

        # Add simulation line
        if simulation_years > 0 and not df_graph.empty:
            latest_row = df_graph.iloc[-1]
            latest_date = pd.to_datetime(latest_row["date"])
            latest_valuation = latest_row["valuation"]

            n_simulation_months = int(simulation_years * 12)
            sim_dates = [
                latest_date + pd.DateOffset(months=i)
                for i in range(n_simulation_months + 1)
            ]

            def project_values(annual_yield: float) -> list[float]:
                monthly_yield = (1 + annual_yield / 100) ** (1 / 12) - 1
                values = [latest_valuation]
                current_valuation = latest_valuation
                for i in range(1, n_simulation_months + 1):
                    current_valuation = (
                        current_valuation * (1 + monthly_yield)
                        + simulation_monthly_investment
                    )
                    values.append(max(current_valuation, 0))
                return values

            sim_values = project_values(simulation_annual_yield)

            # Assume contributions are made at the beginning of each month.
            # invest_amount is cumulative, so its difference is the contribution.
            monthly_returns = self._calculate_monthly_returns(df_graph)
            if len(monthly_returns) >= 2:
                annual_volatility = float(
                    monthly_returns.std(ddof=1) * np.sqrt(12) * 100
                )
            else:
                annual_volatility = 0.0
            lower_values = project_values(
                max(-99.9, simulation_annual_yield - annual_volatility)
            )
            upper_values = project_values(
                simulation_annual_yield + annual_volatility
            )
            ymax = max(ymax, max(upper_values))

            if annual_volatility > 0:
                fig.add_trace(
                    go.Scatter(
                        x=sim_dates,
                        y=lower_values,
                        mode="lines",
                        line=dict(width=0, color="rgba(16, 185, 129, 0)"),
                        hoverinfo="skip",
                        showlegend=False,
                        legendgroup="simulation",
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=sim_dates,
                        y=upper_values,
                        mode="lines",
                        name="シミュレーションのリスク範囲（±1σ）",
                        line=dict(width=0, color="rgba(16, 185, 129, 0)"),
                        fill="tonexty",
                        fillcolor=(
                            "rgba(16, 185, 129, 0.18)"
                            if theme == "dark"
                            else "rgba(16, 185, 129, 0.12)"
                        ),
                        hoverinfo="skip",
                        showlegend=False,
                        legendgroup="simulation",
                    )
                )
            fig.add_trace(
                go.Scatter(
                    x=sim_dates,
                    y=sim_values,
                    mode="lines",
                    name="シミュレーション（±1σ）",
                    legendgroup="simulation",
                    line=dict(
                        width=2,
                        dash="dash",
                        color="#10b981",
                    ),
                    hovertext=[
                        f"シミュレーション<br>  ({x.strftime('%Y年%-m月%-d日')} ¥{y:,.0f})"
                        for x, y in zip(sim_dates, sim_values)
                    ],
                    hoverinfo="text",
                )
            )

        # Add exponential fitting line
        if len(df_graph) > 1:
            base_date = pd.to_datetime(df_graph["date"].iloc[0])
            x_data = np.array(
                [
                    (pd.to_datetime(d) - base_date).total_seconds()
                    for d in df_graph["date"]
                ]
            )
            y_data = df_graph["valuation"].values
            norm_factor = 3600 * 24 * 365 / 12
            x_data_normalized = x_data / norm_factor
            sigma = np.ones_like(y_data, dtype=float)
            sigma[-1] = 1e-1
            try:
                model = FittingModel()
                model.fit(x_data_normalized, y_data, sigma=sigma)
                x_fit = np.concatenate(
                    [
                        x_data_normalized,
                        np.linspace(
                            x_data_normalized.max(),
                            x_data_normalized.max()
                            * self.fitting_duration_multiplier,
                            100,
                        )[1:],
                    ]
                )
                y_fit = model.predict(x_fit)
                dates_fit = [
                    base_date + pd.Timedelta(seconds=round(ts * norm_factor))
                    for ts in x_fit
                ]

                if y_fit.max() > ymax:
                    ymax = y_fit.max()
                hovertext = str(model.get_hovertext())
                fig.add_trace(
                    go.Scatter(
                        x=dates_fit,
                        y=y_fit,
                        mode="lines",
                        name="指数近似",
                        line=dict(
                            width=1.5,
                            dash="dot",
                            color="#d1d5db" if theme == "dark" else "#374151",
                        ),
                        hovertext=[
                            hovertext
                            + f"<br>  ({x.strftime('%Y年%-m月%-d日')} ¥{y:,.0f})"
                            for x, y in zip(dates_fit, y_fit)
                        ],
                        hoverinfo="text",
                    )
                )
            except RuntimeError as e:
                log.warning(f"Could not fit exponential function: {e}")

        fig.add_trace(
            go.Scatter(
                x=[df_graph.iloc[-1]["date"]],
                y=[df_graph.iloc[-1]["valuation"]],
                text=[f"¥{df_graph.iloc[-1]['valuation']:,.0f}"],
                mode="text",
                name="値ラベル",
                textposition="top left",
                textfont=dict(
                    size=14,
                    weight="bold",
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                showlegend=True,
                hoverinfo="skip",
            )
        )

        self._update_layout(
            fig,
            theme,
            ymax_for_format=ymax,
            yaxis_type="linear",
        )

        updatemenu = dict(
            type="buttons",
            direction="right",
            active=0,
            x=1.00,
            xanchor="right",
            y=1.15,
            yanchor="top",
            buttons=list(
                [
                    dict(
                        label="Linear",
                        method="relayout",
                        args=[{"yaxis.type": "linear"}],
                    ),
                    dict(
                        label="Log",
                        method="relayout",
                        args=[{"yaxis.type": "log"}],
                    ),
                ]
            ),
        )
        if theme == "dark":
            updatemenu.update(
                bgcolor="#8791a1",
                font=dict(color="#000000"),
            )

        fig.update_layout(
            title="資産推移",
            hovermode="x unified",
            xaxis=dict(
                showspikes=True,
                spikemode="across",
                spikecolor="#ffffff" if theme == "dark" else "#000000",
                spikethickness=1,
                spikedash="dot",
            ),
            updatemenus=[updatemenu],
        )
        graph_html: str = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_asset_monthly_history_chart' method")
        return graph_html
