import unittest

from expense.core.asset_manager import AssetManager


class FakeWorkbook:
    def __init__(self, value_ranges: list[dict]) -> None:
        self.value_ranges = value_ranges
        self.requested_ranges: list[str] = []

    def values_batch_get(self, ranges: list[str]) -> dict:
        self.requested_ranges = ranges
        return {"valueRanges": self.value_ranges}


class AssetManagerBatchGetTest(unittest.TestCase):
    def test_get_asset_data_uses_one_batch_request(self) -> None:
        portfolio_header = [
            [
                "total",
                "profit",
                "profit_etf",
                "roi",
                "change_jpy",
                "change_pct",
                "drawdown",
                "usdjpy",
            ],
            ["100", "10", "5", "10", "2", "1", "3", "150"],
        ]
        portfolio_table = [
            [
                "ticker",
                "num",
                "acquisition",
                "price_dollar",
                "price",
                "invest_amount",
                "valuation",
                "profit",
                "weight",
                "roi",
            ],
            [
                "VTI",
                "1",
                "100",
                "110",
                "16000",
                "100",
                "110",
                "10",
                "100",
                "10",
            ],
        ]
        monthly_history = [
            ["date", "invest_amount", "valuation", "profit", "roi"],
            ["2026-04-01", "100", "110", "10", "10"],
        ]
        stock_info = [
            [
                "No",
                "ticker",
                "price",
                "change_pct",
                "change_pct_weekly",
                "change_pct_monthly",
                "drawdown",
                "change_pct_yen",
                "change_yen",
                "valuation",
                "profit",
                "roi",
                "チャート1",
                "チャート2",
            ],
            [
                "1",
                "VTI",
                "110",
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
                "110",
                "10",
                "10",
            ],
        ]
        manager = object.__new__(AssetManager)
        manager.workbook = FakeWorkbook(
            [
                {"values": portfolio_header},
                {"values": portfolio_table},
                {"values": monthly_history},
                {"values": stock_info},
            ]
        )

        dataframes = manager.get_asset_data()

        self.assertEqual(
            manager.workbook.requested_ranges,
            [
                "'ポートフォリオ'!A1:H2",
                "'ポートフォリオ'!A4:J15",
                "'資産推移 月次'!G18:K500",
                "'株価情報'!A2:N15",
            ],
        )
        self.assertEqual(dataframes["df_summary"].iloc[0]["total"], 100.0)
        self.assertEqual(dataframes["df_items"].iloc[0]["ticker"], "VTI")
        self.assertEqual(dataframes["df_records"].iloc[0]["valuation"], 110.0)
        self.assertEqual(dataframes["df_stock"].iloc[0]["ticker"], "VTI")

    def test_get_asset_data_requests_only_selected_ranges(self) -> None:
        manager = object.__new__(AssetManager)
        manager.workbook = FakeWorkbook(
            [
                {
                    "values": [
                        [
                            "total",
                            "profit",
                            "profit_etf",
                            "roi",
                            "change_jpy",
                            "change_pct",
                            "drawdown",
                            "usdjpy",
                        ],
                        ["100", "10", "5", "10", "2", "1", "3", "150"],
                    ]
                }
            ]
        )

        dataframes = manager.get_asset_data({"df_summary"})

        self.assertEqual(
            manager.workbook.requested_ranges,
            ["'ポートフォリオ'!A1:H2"],
        )
        self.assertEqual(dataframes["df_summary"].iloc[0]["total"], 100.0)


if __name__ == "__main__":
    unittest.main()
