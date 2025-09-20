import datetime as dt
from typing import Any

import pandas as pd
from plotly import express as px
from plotly import graph_objects as go


class GraphGenerator:
    def __init__(
        self,
        expense_types: list[str],
        exclude_types: list[str],
        graph_color: dict[str, str],
        log: Any,
    ):
        self.expense_types = expense_types
        self.exclude_types = exclude_types
        self.graph_color = graph_color
        self.log = log

    def generate_monthly_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        月別のDataFrameを生成
        """
        self.log.info("start 'generate_monthly_df' method")
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
        self.log.info("end 'generate_monthly_df' method")
        return df_new

    def _add_expense_memo_summary(
        self,
        df: pd.DataFrame,
        df_ref: pd.DataFrame,
        date_or_month: str,
        len_memo_text: int = 50,
    ) -> pd.DataFrame:
        for i, r in df.iterrows():
            key = r[date_or_month]
            expense_type = r["expense_type"]
            condition = f"expense_type=='{expense_type}' and "
            condition += (
                f"date==@pd.Timestamp('{key}')"
                if date_or_month == "date"
                else f"month=='{key}'"
            )
            _data = df_ref.query(condition)
            n_memo = _data["expense_memo"].value_counts()
            _data = (
                _data.groupby(["expense_memo"])["expense_amount"]
                .sum()
                .reset_index()
            ).sort_values("expense_amount")
            _add_memo = ""
            for memo in _data["expense_memo"].iloc[::-1]:
                if memo in _add_memo:
                    continue
                n = n_memo[memo]
                if n > 1:
                    memo += f" ×{n}"
                if len(_add_memo + memo) > len_memo_text:
                    _add_memo += ", ⋯"
                    break
                if len(memo) > 0:
                    _add_memo += ",<br>" + memo if len(_add_memo) else memo
            df.loc[i, "expense_memo"] = _add_memo
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
        df_graph = df_graph.query("expense_type not in @self.exclude_types")
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
                pd.Timestamp(month_start),
                pd.Timestamp(month_end),
            ],
            range_y=[
                0,
                max(
                    min_yrange,
                    df_graph["cumsum"].max() * 1.2,
                    df_predict["predict"].max() * 1.2,
                ),
            ],
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
        fontsize: int = 14,
        label_steps: int = 3,
        label_threshold: int = 2000,
        label_offset: int = 3000,
    ) -> None:
        totals = df_bar.groupby(key, as_index=False)["expense_amount"].sum()
        totals["label"] = totals["expense_amount"].map(
            lambda x: f"¥{x:,}" if x >= label_threshold else ""
        )
        y = [
            j + ((i + 1) % label_steps) * label_offset
            for i, j in enumerate(totals["expense_amount"])
        ]
        fig.add_trace(
            go.Scatter(
                x=totals[key],
                y=y,
                text=totals["label"],
                mode="text",
                textposition="top center",
                textfont=dict(
                    size=fontsize,
                    weight="bold",
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    def _update_traces(
        self, fig_bar: px.bar, fig_line: px.line, fig_predict: px.line
    ) -> None:
        fig_bar.update_traces(
            hovertemplate="%{x|%-m月%-d日} ¥%{y:,.0f}<br>%{customdata[0]}",
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
        )

    def generate_daily_chart(
        self,
        df_org: pd.DataFrame,
        theme: str = "light",
        min_yrange: int = 50000,
        include_plotlyjs: bool = True,
    ) -> str:
        """
        累積折れ線グラフを生成
        """
        self.log.info("start 'generate_daily_chart' method")
        df = df_org.copy()
        if df.empty:
            self.log.info("DataFrame is empty, skipping graph generation.")
            return ""

        today = pd.Timestamp(dt.date.today())
        df["date"] = pd.to_datetime(df["date"])
        unique_months = sorted(
            df["date"].dt.to_period("M").unique(), reverse=True
        )

        fig = go.Figure()
        trace_collections = []
        y_ranges = []
        processed_months = []
        for month in unique_months:
            t = month.to_timestamp()
            month_start, month_end = self._get_month_boundaries(t)
            df_graph = self._prepare_graph_dataframe(df, month_start, month_end)
            if df_graph.empty:
                continue
            df_bar = self._prepare_bar_dataframe(df_graph)
            df_graph = self._add_month_start_point(df_graph, month_start)
            df_graph, df_predict = self._handle_predictions(
                df_graph, t, month_start, month_end
            )
            fig_bar = self._create_bar_figure(
                df_bar, month_start, month_end, min_yrange, df_graph, df_predict
            )
            fig_line = self._create_line_figure(df_graph, theme)
            fig_predict = self._create_prediction_figure(df_predict, theme)
            self._update_traces(fig_bar, fig_line, fig_predict)
            temp_fig = go.Figure()
            temp_fig.add_traces(fig_bar.data)
            temp_fig.add_traces(fig_line.data)
            if today.to_period("M") == month:
                temp_fig.add_traces(fig_predict.data)
            self._add_bar_chart_labels(
                temp_fig,
                df_bar,
                "date",
                theme,
                fontsize=10,
                label_steps=3,
                label_threshold=max(fig_bar.layout.yaxis.range[1] * 0.02, 2000),
                label_offset=max(fig_bar.layout.yaxis.range[1] * 0.05, 3000),
            )

            trace_collections.append(temp_fig.data)
            y_ranges.append(fig_bar.layout.yaxis.range)
            processed_months.append(month)

        if not trace_collections:
            return ""

        # Add all traces to the main figure, making only the first month visible
        for i, traces in enumerate(trace_collections):
            for trace in traces:
                fig.add_trace(trace.update(visible=(i == 0)))

        # Create dropdown buttons
        buttons = []
        cumulative_trace_count = 0
        for i, traces in enumerate(trace_collections):
            visibility = [False] * len(fig.data)
            for j in range(len(traces)):
                visibility[cumulative_trace_count + j] = True

            month_str = processed_months[i].strftime("%Y年%-m月")
            buttons.append(
                dict(
                    label=month_str,
                    method="update",
                    args=[
                        {"visible": visibility},
                        {"yaxis.range": y_ranges[i]},
                    ],
                )
            )
            cumulative_trace_count += len(traces)

        self._update_layout(fig, theme)
        fig.update_layout(
            barmode="stack",
            updatemenus=[
                dict(
                    active=0,
                    buttons=buttons,
                    direction="down",
                    pad={"r": 0, "t": 0},
                    showactive=False,
                    x=1,
                    xanchor="right",
                    y=1.15,
                    yanchor="top",
                )
            ],
            yaxis=dict(fixedrange=True),
        )
        if processed_months and y_ranges:
            fig.update_layout(
                title_text="支出内訳 日別",
                yaxis_range=y_ranges[0],
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
        self.log.info("end 'generate_daily_chart' method")
        return graph_html

    def generate_pie_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        include_plotlyjs: bool = True,
    ) -> str:
        """
        円グラフを生成
        """
        self.log.info("start 'generate_pie_chart' method")
        if df.empty:
            self.log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_pie = df.copy()
        df_pie = df_pie.loc[
            df_pie.loc[:, "month"] == dt.datetime.today().strftime("%Y-%m")
        ]
        month_str = pd.Timestamp(df_pie.iloc[-1]["month"]).strftime("%Y年%-m月")
        total_amount = df_pie["expense_amount"].sum()
        fig = px.pie(
            df_pie,
            names="expense_type",
            values="expense_amount",
            color="expense_type",
            title=f"支出内訳（{month_str}）",
            hover_data=["expense_memo"],
            category_orders={"expense_type": self.expense_types},
            color_discrete_map=self.graph_color,
            hole=0.4,
        )
        fig.update_traces(
            texttemplate="¥%{value:,} (%{percent})",
            hovertemplate="%{label}<br>¥%{value:,.0f}<br>%{customdata[0]}",
            textfont=dict(size=14),
        )
        fig.add_annotation(
            text=f"合計<br>¥{total_amount: ,.0f}",
            x=0.5,
            y=0.5,
            font_size=20,
            showarrow=False,
            font=dict(
                color="#ffffff" if theme == "dark" else "#000000", size=20
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
        self.log.info("end 'generate_pie_chart' method")
        return graph_html

    def generate_bar_chart(
        self,
        df: pd.DataFrame,
        theme: str = "light",
        max_monthes: int = 12,
        include_plotlyjs: bool = True,
    ) -> str:
        """
        月別の棒グラフを生成
        """
        self.log.info("start 'generate_bar_chart' method")
        if df.empty:
            self.log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_graph = df.copy()
        df_graph.loc[:, "label"] = df_graph.loc[:, "expense_amount"].map(
            lambda x: f"¥{x:,}" if 10000 <= x else ""
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
            title="支出内訳（月別）",
            hover_data=["expense_memo"],
            range_y=[0, None],
            category_orders={"expense_type": self.expense_types},
            color_discrete_map=self.graph_color,
        )
        fig.update_traces(
            hovertemplate="%{x|%-Y年%-m月}<br>¥%{value:,.0f}<br>%{customdata[0]}",
            textfont=dict(size=14),
        )
        self._update_layout(fig, theme)
        self._add_bar_chart_labels(fig, df_graph, "month", theme, fontsize=14)
        graph_html = fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config=dict(
                responsive=True,
                displayModeBar=False,
            ),
        )
        self.log.info("end 'generate_bar_chart' method")
        return graph_html
