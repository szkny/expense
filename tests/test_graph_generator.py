import unittest

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
