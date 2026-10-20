import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock, patch

import pandas as pd
import plotly.graph_objects as go

from expense.core.graph_generator import GraphGenerator


def capture_chart_figure(
    generator: GraphGenerator,
    create_chart: Callable[..., str],
    data: pd.DataFrame,
) -> tuple[go.Figure, str, Mock]:
    figures: list[go.Figure] = []

    def render_figure(figure: go.Figure, *_args: Any, **_kwargs: Any) -> str:
        figures.append(figure)
        return "<div>chart</div>"

    with patch.object(
        generator, "_figure_to_html", side_effect=render_figure
    ) as render:
        chart_html = create_chart(data, include_plotlyjs=False)

    return figures[0], chart_html, render


class GraphGeneratorYAxisTicksTest(unittest.TestCase):
    def test_values_below_one_hundred_million_use_man_unit(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        figure = go.Figure()
        figure.update_layout(yaxis=dict(range=[0, 100_000_000]))

        settings = generator._format_yaxis_ticks(figure)

        self.assertIn("¥8,000万", settings["ticktext"])
        self.assertIn("¥1億", settings["ticktext"])
        self.assertNotIn("¥0.8億", settings["ticktext"])


class GraphGeneratorMonthlyReturnsTest(unittest.TestCase):
    def test_month_start_contributions_are_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2024-01-31", "2024-02-29", "2024-03-31"]
                ),
                "invest_amount": [100, 110, 120],
                "valuation": [100, 121, 144.1],
            }
        )

        returns = GraphGenerator._calculate_monthly_returns(df)

        self.assertAlmostEqual(returns.iloc[0], 0.1)
        self.assertAlmostEqual(returns.iloc[1], 0.1)


class GraphGeneratorAssetProfitHistoryTest(unittest.TestCase):
    def test_generates_profit_history_with_positive_and_negative_values(
        self,
    ) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-31", "2026-02-28"]),
                "profit": [-100, 250],
                "invest_amount": [2_000, 2_000],
            }
        )

        figure, graph_html, render = capture_chart_figure(
            generator, generator.generate_asset_profit_history_chart, df
        )

        trace = figure.data[0]
        self.assertEqual(list(trace.y), [-100, 250])
        self.assertIn("含み益 +¥250", trace.hovertext[1])
        self.assertIn("損益率 +12.50%", trace.hovertext[1])
        self.assertIn("損益率 -5.00%", trace.hovertext[0])
        self.assertEqual(figure.layout.annotations[0].text, "+¥250")
        self.assertEqual(figure.layout.annotations[0].yshift, 8)
        self.assertEqual(list(figure.layout.yaxis.range), [-150, 300])
        self.assertTrue(figure.layout.yaxis.fixedrange)
        self.assertEqual(graph_html, "<div>chart</div>")
        self.assertTrue(render.call_args.kwargs["autoscale_yaxis"])

    def test_html_renderer_wraps_a_plotly_figure(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        figure = go.Figure(go.Scatter(x=[1], y=[2]))

        graph_html = generator._figure_to_html(figure, include_plotlyjs=False)

        self.assertIn("plotly-graph-div", graph_html)
        self.assertIn("user-select: none", graph_html)

    def test_returns_empty_html_for_empty_data(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)

        self.assertEqual(
            generator.generate_asset_profit_history_chart(pd.DataFrame()), ""
        )


class GraphGeneratorAssetRecentlyHistoryTest(unittest.TestCase):
    def test_loads_all_records_with_one_month_initial_range(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        today = pd.Timestamp.today().normalize()
        start_date = today - pd.DateOffset(months=1)
        df = pd.DataFrame(
            {
                "date": [
                    today - pd.Timedelta(days=60),
                    start_date - pd.Timedelta(days=1),
                    start_date,
                    today - pd.Timedelta(days=1),
                    today,
                    today,
                    today + pd.Timedelta(days=1),
                ],
                "valuation": [50, 100, 200, 300, 350, 400, 500],
            }
        )

        figure, graph_html, render = capture_chart_figure(
            generator, generator.generate_asset_recently_history_chart, df
        )

        trace = figure.data[0]
        self.assertEqual(list(trace.y), [50, 100, 200, 300, 400])
        self.assertEqual(trace.mode, "lines+markers")
        self.assertEqual(
            trace.hovertemplate, "評価額 ¥%{y:,.0f}<extra></extra>"
        )
        self.assertEqual(
            pd.Timestamp(figure.layout.xaxis.range[0]),
            start_date,
        )
        self.assertEqual(pd.Timestamp(figure.layout.xaxis.range[1]), today)
        self.assertEqual(figure.layout.xaxis.type, "date")
        self.assertIsNone(figure.layout.xaxis.tickformat)
        self.assertEqual(figure.layout.title.text, "直近の資産推移")
        self.assertEqual(list(figure.layout.yaxis.range), [160, 440])
        self.assertFalse(figure.layout.yaxis.autorange)
        self.assertFalse(figure.layout.xaxis.fixedrange)
        self.assertEqual(figure.layout.dragmode, "pan")
        self.assertTrue(render.call_args.kwargs["autoscale_yaxis"])
        self.assertTrue(render.call_args.kwargs["clear_hover_on_leave"])
        self.assertEqual(graph_html, "<div>chart</div>")

    def test_constant_values_get_a_nonzero_y_axis_range(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        today = pd.Timestamp.today().normalize()
        df = pd.DataFrame({"date": [today], "valuation": [100]})

        figure, _, _ = capture_chart_figure(
            generator, generator.generate_asset_recently_history_chart, df
        )

        self.assertEqual(list(figure.layout.yaxis.range), [99, 101])

    def test_returns_empty_html_when_no_recent_records(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        df = pd.DataFrame(
            {
                "date": [
                    pd.Timestamp.today().normalize()
                    - pd.DateOffset(months=1)
                    - pd.Timedelta(days=1)
                ],
                "valuation": [100],
            }
        )

        self.assertEqual(
            generator.generate_asset_recently_history_chart(df), ""
        )


class GraphGeneratorAssetDrawdownTest(unittest.TestCase):
    def test_drawdown_uses_the_highest_profit_point_as_the_peak(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2026-01-01", "2026-01-02", "2026-01-03"]
                ),
                "invest_amount": [100, 100, 120],
                "valuation": [110, 130, 125],
                "profit": [10, 30, 5],
            }
        )

        drawdown = GraphGenerator._calculate_asset_drawdown(df)

        self.assertEqual(drawdown.iloc[0], 0)
        self.assertEqual(drawdown.iloc[1], 0)
        self.assertAlmostEqual(drawdown.iloc[2], -25 / 130)

    def test_generates_drawdown_history_chart(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                "invest_amount": [100, 100],
                "valuation": [110, 100],
                "profit": [10, 0],
            }
        )

        figure, graph_html, render = capture_chart_figure(
            generator, generator.generate_asset_drawdown_history_chart, df
        )

        trace = figure.data[0]
        self.assertEqual(trace.y[0], 0.0)
        self.assertAlmostEqual(trace.y[1], -1 / 11)
        self.assertEqual(list(trace.customdata), ["¥0", "-¥10"])
        self.assertIn("金額 %{customdata}", trace.hovertemplate)
        self.assertEqual(trace.mode, "lines")
        self.assertEqual(figure.layout.annotations[0].text, "-9.09%")
        self.assertEqual(figure.data[1].mode, "text")
        self.assertEqual(list(figure.data[1].text), [])
        self.assertEqual(figure.data[1].textposition, "bottom center")
        self.assertEqual(figure.layout.dragmode, "pan")
        self.assertTrue(render.call_args.kwargs["config"]["scrollZoom"])
        self.assertTrue(render.call_args.kwargs["clear_hover_on_leave"])
        self.assertEqual(graph_html, "<div>chart</div>")

    def test_labels_deepest_drawdown_in_each_significant_decline(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        df = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=8),
                "invest_amount": [100] * 8,
                "valuation": [200, 180, 198, 170, 200, 220, 198, 220],
                "profit": [100, 80, 98, 70, 100, 120, 98, 120],
            }
        )

        figure, _, _ = capture_chart_figure(
            generator, generator.generate_asset_drawdown_history_chart, df
        )

        labels = figure.data[1]
        self.assertEqual(list(labels.text), ["-15.00%", "-10.00%"])
        self.assertEqual(
            pd.to_datetime(list(labels.x)).tolist(),
            [pd.Timestamp("2026-01-04"), pd.Timestamp("2026-01-07")],
        )

    def test_initial_x_axis_range_spans_six_months_before_and_one_after(
        self,
    ) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2023-01-01", "2026-01-01"]),
                "invest_amount": [100, 100],
                "valuation": [110, 100],
                "profit": [10, 0],
            }
        )

        figure, _, _ = capture_chart_figure(
            generator, generator.generate_asset_drawdown_history_chart, df
        )

        self.assertEqual(
            pd.Timestamp(figure.layout.xaxis.range[0]),
            pd.Timestamp("2025-07-01"),
        )
        self.assertEqual(
            pd.Timestamp(figure.layout.xaxis.range[1]),
            pd.Timestamp("2026-02-01"),
        )

    def test_ignores_future_rows_from_sheet_formulas(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        future_date = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
        df = pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-01-01"), future_date],
                "invest_amount": [100, 200],
                "valuation": [110, 150],
                "profit": [10, -50],
            }
        )

        figure, _, _ = capture_chart_figure(
            generator, generator.generate_asset_drawdown_history_chart, df
        )

        plotted_dates = pd.to_datetime(list(figure.data[0].x))
        self.assertNotIn(future_date, plotted_dates)


class GraphGeneratorForecastTest(unittest.TestCase):
    def test_recent_daily_records_have_more_weight(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2026-01-01"]),
                "income": [100, 200],
                "expense": [0, 0],
            }
        )

        income_rate, expense_rate = (
            GraphGenerator._calculate_weighted_daily_rates(
                df, pd.Timestamp("2026-01-01")
            )
        )

        unweighted_rate = 300 / len(pd.date_range("2024-01-01", "2026-01-01"))
        self.assertGreater(income_rate, unweighted_rate)
        self.assertEqual(expense_rate, 0)

    def test_monthly_forecast_ignores_partial_current_month(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2026-01-25", "2026-02-25", "2026-03-01"]
                ),
                "income": [300_000, 310_000, 999_999],
                "expense": [100_000, 110_000, 1],
            }
        )

        income_total, expense_total = (
            GraphGenerator._calculate_weighted_monthly_totals(
                df, pd.Timestamp("2026-03-15")
            )
        )

        self.assertAlmostEqual(income_total, 305_594, delta=1)
        self.assertAlmostEqual(expense_total, 105_594, delta=1)


class GraphGeneratorDailyChartTest(unittest.TestCase):
    def test_months_include_months_with_only_fixed_expenses(self) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        generator.variable_types = ["食費"]
        current_month = pd.Timestamp.today().strftime("%Y-%m")
        df = pd.DataFrame(
            {
                "date": pd.to_datetime([f"{current_month}-01"]),
                "expense_type": ["家賃"],
                "expense_amount": [100_000],
            }
        )

        graph_html, available_months = generator.generate_daily_chart(
            df, target_month=current_month, include_plotlyjs=False
        )

        self.assertEqual(graph_html, "")
        self.assertEqual(available_months, [current_month])

    def test_defaults_to_current_month_when_latest_records_are_older(
        self,
    ) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        generator.variable_types = ["食費"]
        generator.expense_types = ["食費"]
        generator.graph_color = {}
        today = pd.Timestamp.today().normalize()
        current_month = today.strftime("%Y-%m")
        previous_month = today.to_period("M") - 1
        df = pd.DataFrame(
            {
                "date": [previous_month.start_time + pd.Timedelta(days=5)],
                "expense_type": ["食費"],
                "expense_amount": [1_000],
                "expense_memo": [""],
            }
        )

        graph_html, available_months = generator.generate_daily_chart(
            df, include_plotlyjs=False
        )

        self.assertEqual(graph_html, "")
        self.assertEqual(available_months[0], current_month)
        self.assertIn(previous_month.strftime("%Y-%m"), available_months)


class GraphGeneratorSavingsRateTest(unittest.TestCase):
    def test_savings_rate_is_cash_flow_as_percentage_of_income(self) -> None:
        self.assertEqual(GraphGenerator._format_savings_rate(30, 100), "30.0%")
        self.assertEqual(
            GraphGenerator._format_savings_rate(-30, 100), "-30.0%"
        )

    def test_savings_rate_is_dash_when_income_is_zero(self) -> None:
        self.assertEqual(GraphGenerator._format_savings_rate(30, 0), "-")


class GraphGeneratorIncomeHoverTest(unittest.TestCase):
    def test_income_hover_summary_contains_type_amount_and_memo(self) -> None:
        df_income = pd.DataFrame(
            {
                "month": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "expense_type": ["給与", "副業"],
                "expense_amount": [300_000, 50_000],
                "expense_memo": ["<br>本業", "<br>記事"],
            }
        )

        summary = GraphGenerator._create_income_hover_summary(df_income)
        mapped_summary = pd.Series(pd.to_datetime(["2026-01-01"])).map(summary)

        self.assertEqual(
            summary.iloc[0],
            "<br>-----<br>■ 給与: ¥300,000<br>本業"
            "<br>■ 副業: ¥50,000<br>記事",
        )
        self.assertFalse(mapped_summary.isna().any())


class GraphGeneratorFiscalForecastTest(unittest.TestCase):
    def test_forecast_starts_after_irregular_income_in_actual_balance(
        self,
    ) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        daily = pd.DataFrame(
            {
                "income": [1_000_000],
                "expense": [300_000],
                "income_cumulative": [1_000_000],
                "expense_cumulative": [300_000],
                "balance": [700_000],
                "cash_flow": [700_000],
            },
            index=pd.to_datetime(["2026-08-31"]),
        )
        df_history = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-08-01", "2026-08-31"]),
                "income": [300_000, 700_000],
                "forecast_income": [300_000, 0],
                "expense": [0, 300_000],
            }
        )

        figure = go.Figure()
        forecast = generator._add_fiscal_forecast_traces(
            figure,
            daily,
            df_history,
            pd.Timestamp("2026-08-31"),
            pd.Timestamp("2026-09-02"),
            ["#111111", "#222222", "#333333"],
        )

        self.assertEqual(forecast[0][0], 1_000_000 + 300_000)
        self.assertEqual(
            list(figure.data[0].x),
            [
                pd.Timestamp("2026-08-31"),
                pd.Timestamp("2026-09-01"),
                pd.Timestamp("2026-09-02"),
            ],
        )
        self.assertEqual(
            list(figure.data[0].y), [1_000_000, 1_300_000, 1_300_000]
        )

    def test_income_forecast_does_not_decrease_after_large_actual_income(
        self,
    ) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        daily = pd.DataFrame(
            {
                "income": [1_000_000],
                "expense": [0],
                "income_cumulative": [1_000_000],
                "expense_cumulative": [0],
                "balance": [1_000_000],
                "cash_flow": [1_000_000],
            },
            index=pd.to_datetime(["2026-08-15"]),
        )
        df_history = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2026-07-15", "2026-08-01", "2026-08-15"]
                ),
                "income": [100, 300_000, 700_000],
                "forecast_income": [100, 300_000, 700_000],
                "expense": [0, 0, 0],
            }
        )

        figure = go.Figure()
        forecast = generator._add_fiscal_forecast_traces(
            figure,
            daily,
            df_history,
            pd.Timestamp("2026-08-15"),
            pd.Timestamp("2026-08-17"),
            ["#111111", "#222222", "#333333"],
        )

        self.assertEqual(list(forecast[0]), [1_000_000, 1_000_000])

    def test_expense_forecast_does_not_decrease_after_large_actual_expense(
        self,
    ) -> None:
        generator = GraphGenerator.__new__(GraphGenerator)
        daily = pd.DataFrame(
            {
                "income": [0],
                "expense": [1_000_000],
                "income_cumulative": [0],
                "expense_cumulative": [1_000_000],
                "balance": [-1_000_000],
                "cash_flow": [-1_000_000],
            },
            index=pd.to_datetime(["2026-08-15"]),
        )
        df_history = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    ["2026-07-15", "2026-08-01", "2026-08-15"]
                ),
                "income": [0, 0, 0],
                "forecast_income": [0, 0, 0],
                "expense": [100, 300_000, 700_000],
            }
        )

        forecast = generator._add_fiscal_forecast_traces(
            go.Figure(),
            daily,
            df_history,
            pd.Timestamp("2026-08-15"),
            pd.Timestamp("2026-08-17"),
            ["#111111", "#222222", "#333333"],
        )

        self.assertEqual(list(forecast[1]), [1_000_000, 1_000_000])
