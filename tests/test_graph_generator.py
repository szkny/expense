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
