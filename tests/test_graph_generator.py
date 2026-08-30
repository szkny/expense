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
