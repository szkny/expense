import re
import logging
import pandas as pd
import datetime as dt
from typing import Any
import plotly.io as pio

from plotly import express as px
from plotly import graph_objects as go

log: logging.Logger = logging.getLogger("expense")


class GraphGenerator:
    def __init__(
        self,
        expense_types: list[str],
        variable_types: list[str],
        exclude_types: list[str],
        graph_config: dict[str, Any],
    ):
        self.expense_types = expense_types
        self.variable_types = variable_types
        self.exclude_types = exclude_types
        self.graph_color = graph_config.get("color", {})
        # NOTE: サーバー起動の初回アクセス時に、plotlyのテンプレート関連の処理でエラーが発生することがあるため
        #       デフォルトのテンプレートを明示的に指定しておく
        pio.templates.default = "plotly_white"

    def get_plotlyjs(self) -> str:
        log.info("start 'get_plotlyjs' method")
        dummy_fig = dict(data=[], layout={})
        html = pio.to_html(dummy_fig, include_plotlyjs=True, full_html=False)
        scripts = re.findall(
            r'(<script type="text/javascript">.*?</script>)', html, re.DOTALL
        )
        script_html = scripts[0] + scripts[1] if len(scripts) >= 2 else ""
        log.info("end 'get_plotlyjs' method")
        return script_html

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
        def create_summary_string(group):
            memos = []
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
    ) -> px.bar:
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
    ) -> px.line:
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
    ) -> px.line:
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
        fig: px.bar,
        df_bar: pd.DataFrame,
        key: str,
        theme: str,
        fontsize: int = 10,
        label_nlags: int = 3,
        label_threshold: int = 1000,
        label_offset: int = 2000,
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
        fig.add_trace(
            go.Scatter(
                x=totals[key],
                y=y,
                text=label,
                mode="text",
                textposition="top center",
                name="値ラベル",
                textfont=dict(
                    size=fontsize,
                    weight="bold",
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                showlegend=True,
                hoverinfo="skip",
            )
        )

    def _update_traces(
        self, fig_bar: px.bar, fig_line: px.line, fig_predict: px.line
    ) -> None:
        fig_bar.update_traces(
            hovertemplate="%{x|%-m月%-d日} ¥%{y:,.0f}%{customdata[0]}",
            textfont=dict(size=14),
        )
        fig_line.update_traces(
            line=dict(dash="solid", width=1.5),
            hovertemplate="¥%{y:,.0f}",
        )
        fig_predict.update_traces(
            line=dict(dash="dot", width=1.5),
            hovertemplate="¥%{y:,.0f}",
        )

    def _update_layout(self, fig: go.Figure, theme: str) -> None:
        fig.update_layout(
            height=500,
            xaxis_title="",
            yaxis_title="",
            title_y=0.98,
            legend_title="",
            xaxis=dict(fixedrange=True),
            yaxis=dict(
                tickprefix="¥",
                tickformat=",",
                autorange=True,
                fixedrange=False,
            ),
            dragmode=False,
            legend=dict(orientation="h"),
            margin=dict(l=10, r=10, t=50, b=0),
            paper_bgcolor="#1f2937" if theme == "dark" else "#ffffff",
            plot_bgcolor="#1f2937" if theme == "dark" else "#ffffff",
            template="plotly_dark" if theme == "dark" else "plotly_white",
            uniformtext=dict(minsize=10, mode="hide"),
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

        graph_html = fig.to_html(
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
        date_index = pd.to_datetime(df_records["date"])
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
            df_records, month_start, month_end
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
        graph_html = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_pie_chart' method")
        return graph_html, available_months

    def generate_bar_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        max_monthes: int = 12,
        include_plotlyjs: bool | str = True,
    ) -> str:
        """
        月別の棒グラフを生成
        """
        log.info("start 'generate_bar_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_graph = df.copy()
        df_graph.query("expense_type in @self.variable_types", inplace=True)
        for i, r in df_graph.iterrows():
            df_graph.loc[i, "label"] = (
                f"{r['expense_type']}<br>¥{r['expense_amount']:,.0f}"
            )
        df_graph["month"] = pd.to_datetime(df_graph["month"])
        cutoff_date = dt.datetime.today() - dt.timedelta(
            days=30 * (max_monthes - 1)
        )
        cutoff_date = cutoff_date.strftime("%Y-%m-01")
        df_graph = df_graph.query("month >= @pd.Timestamp(@cutoff_date)")
        df_graph["month"] = df_graph["month"].dt.strftime("%Y-%m")
        fig = px.bar(
            df_graph,
            x="month",
            y="expense_amount",
            color="expense_type",
            text="label",
            title="変動費内訳（月別）",
            hover_data=["expense_memo"],
            range_y=[0, None],
            category_orders={"expense_type": self.expense_types},
            color_discrete_map=self.graph_color,
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
        self._update_layout(fig, theme)
        self._add_bar_chart_labels(fig, df_graph, "month", theme, fontsize=12)
        graph_html = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_bar_chart' method")
        return graph_html

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
            title="資産内訳",
            category_orders={"ticker": df_pie["ticker"].to_list()},
            color_discrete_map=graph_color,
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
        graph_html = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_asset_pie_chart' method")
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
                    size=8, color="#ffffff" if theme == "dark" else "#000000"
                ),
            )
        fig.update_xaxes(showline=False, showticklabels=False, showgrid=False)
        self._update_layout(fig, theme)
        fig.update_layout(title="含み益 内訳", waterfallgap=0.4, height=300)
        graph_html = fig.to_html(
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
    ) -> str:
        """
        月単位の資産推移チャートを生成
        """
        log.info("start 'generate_asset_monthly_history_chart' method")
        df_graph = df.copy()
        opr = ["+" if r["profit"] >= 0 else "-" for _, r in df_graph.iterrows()]
        roi = [r["roi"] for _, r in df_graph.iterrows()]
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df_graph["date"],
                y=df_graph["invest_amount"],
                fill="tozeroy",
                mode="none",
                name="投資額",
                fillcolor=(
                    "rgba(120, 160, 255, 0.5)"
                    if theme == "dark"
                    else "rgba(50, 80, 200, 0.5)"
                ),
                hovertext=[
                    f"{x.strftime('%Y年%-m月%-d日')}<br>投資額 ¥{y:,.0f}"
                    for x, y in zip(df_graph["date"], df_graph["invest_amount"])
                ],
                hoverinfo="text",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_graph["date"],
                y=df_graph["valuation"],
                mode="lines",
                name="評価額",
                line=dict(
                    width=2, color="#dd4433" if theme == "dark" else "#ff5544"
                ),
                hovertext=[
                    f"評価額 ¥{y:,.0f}<br>  (含み益 {o}¥{abs(p):,.0f} ／ 損益率 {o}{abs(r):.2f}%)"
                    for y, p, o, r in zip(
                        df_graph["valuation"], df_graph["profit"], opr, roi
                    )
                ],
                hoverinfo="text",
            )
        )
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
        self._update_layout(fig, theme)
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
        )
        graph_html = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        log.info("end 'generate_asset_monthly_history_chart' method")
        return graph_html
