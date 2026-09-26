import unittest

import pandas as pd
import plotly.graph_objects as go

from expense.core.graph_generator import GraphGenerator


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
