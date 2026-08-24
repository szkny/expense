import unittest
import datetime
import pandas as pd
from unittest.mock import patch
from src.expense.core.expense import get_fiscal_year, Expense
from src.expense.core.ocr import Ocr
from src.expense.core.asset_manager import AssetManager


class TestMain(unittest.TestCase):

    def test_normalize_capture_text(self) -> None:
        ocr = Ocr()
        self.assertEqual(ocr.normalize_capture_text("①②③"), "123")
        self.assertEqual(
            ocr.normalize_capture_text("０１２３４５６７８９"), "0123456789"
        )
        self.assertEqual(
            ocr.normalize_capture_text("あ い う え お"), "あいうえお"
        )
        self.assertEqual(ocr.normalize_capture_text("①０ あ い"), "10あい")

    def test_get_fiscal_year(self) -> None:
        with patch("src.expense.core.expense.datetime") as mock_datetime:
            # Test case 1: Month is April (start of fiscal year)
            mock_datetime.date.today.return_value = datetime.date(2023, 4, 1)
            self.assertEqual(get_fiscal_year(), 2023)

            # Test case 2: Month is March (end of fiscal year)
            mock_datetime.date.today.return_value = datetime.date(2024, 3, 31)
            self.assertEqual(get_fiscal_year(), 2023)

            # Test case 3: Month is January (end of fiscal year)
            mock_datetime.date.today.return_value = datetime.date(2024, 1, 1)
            self.assertEqual(get_fiscal_year(), 2023)

            # Test case 4: Month is December (start of fiscal year)
            mock_datetime.date.today.return_value = datetime.date(2023, 12, 31)
            self.assertEqual(get_fiscal_year(), 2023)

    def test_filter_duplicates(self) -> None:
        expense = Expense()
        list1 = [{"a": 1}, {"b": 2}]
        list2 = [{"b": 2}, {"c": 3}]
        list3 = [{"a": 1}, {"d": 4}]
        result = expense.filter_duplicates([list1, list2, list3])
        self.assertEqual(result, [[{"a": 1}, {"b": 2}], [{"c": 3}], [{"d": 4}]])

    def test_get_favorite_expenses(self) -> None:
        expense = Expense()
        expense.config = {
            "expense": {
                "favorites": [
                    {
                        "expense_type": "食費",
                        "expense_memo": "",
                        "expense_amount": 1000,
                    }
                ]
            }
        }
        self.assertEqual(
            expense.get_favorite_expenses(),
            [
                {
                    "expense_type": "食費",
                    "expense_memo": "",
                    "expense_amount": 1000,
                }
            ],
        )

    def test_get_frequent_expenses(self) -> None:
        expense = Expense()
        with (
            patch("src.expense.core.expense.os.path.exists") as mock_exists,
            patch(
                "builtins.open",
                unittest.mock.mock_open(
                    read_data="2023-01-01,食費,,1000\n2023-01-01,食費,,1000\n2023-01-02,交通費,,500"
                ),
            ),
        ):
            mock_exists.return_value = True
            self.assertEqual(
                expense.get_frequent_expenses(1),
                [
                    {
                        "expense_type": "食費",
                        "expense_memo": "",
                        "expense_amount": 1000,
                    }
                ],
            )

            mock_exists.return_value = False
            self.assertEqual(expense.get_frequent_expenses(1), [])

    def test_get_recent_expenses(self) -> None:
        expense = Expense()
        with (
            patch(
                "src.expense.core.expense.pd.read_csv",
                unittest.mock.Mock(
                    return_value=pd.DataFrame(
                        {
                            "date": ["2023-01-01", "2023-01-02", "2023-01-03"],
                            "expense_type": ["食費", "交通費", "遊興費"],
                            "expense_memo": ["", "", ""],
                            "expense_amount": [1000, 500, 2000],
                        }
                    )
                ),
            ) as mock_read_csv,
        ):
            self.assertEqual(
                expense.get_recent_expenses(2),
                [
                    {
                        "expense_type": "遊興費",
                        "expense_memo": "",
                        "expense_amount": 2000,
                    },
                    {
                        "expense_type": "交通費",
                        "expense_memo": "",
                        "expense_amount": 500,
                    },
                ],
            )

            mock_read_csv.side_effect = FileNotFoundError
            self.assertEqual(expense.get_recent_expenses(2), [])

    def test_store_expense(self) -> None:
        expense = Expense()
        with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
            expense.store_expense("食費", "メモ", 1000)
            mock_open.assert_called_once_with(unittest.mock.ANY, "a")
            mock_open().write.assert_called_once()

    def test_build_asset_allocation(self) -> None:
        df_items = pd.DataFrame(
            {
                "ticker": ["AAA", "BBB"],
                "valuation": [60000, 40000],
            }
        )
        result = AssetManager.build_asset_allocation(
            df_items,
            {"AAA": 50, "BBB": 50},
            tolerance_percent=2,
        )
        self.assertEqual(result[0]["action"], "売り")
        self.assertEqual(result[0]["trade_value"], -10000)
        self.assertEqual(result[1]["action"], "買い")
        self.assertEqual(result[1]["trade_value"], 10000)

        within_tolerance = AssetManager.build_asset_allocation(
            df_items, {"AAA": 61, "BBB": 39}, tolerance_percent=2
        )
        self.assertEqual(within_tolerance[0]["action"], "調整不要")
        self.assertEqual(within_tolerance[0]["trade_value"], 0)

        invalid_target = AssetManager.build_asset_allocation(
            df_items, {"AAA": "invalid", "BBB": 50}
        )
        self.assertEqual([item["ticker"] for item in invalid_target], ["BBB"])

        grouped_target = AssetManager.build_asset_allocation(
            df_items,
            {
                "AAA": 30,
                "BBB": 20,
                "米国株": {"tickers": ["AAA", "BBB"], "weight": 50},
            },
        )
        group = grouped_target[2]
        self.assertEqual(group["ticker"], "米国株")
        self.assertEqual(group["tickers"], ["AAA", "BBB"])
        self.assertEqual(group["current_value"], 100000)
        self.assertEqual(group["trade_value"], -50000)

        amount_target = AssetManager.build_asset_allocation(
            df_items,
            {
                "AAA": {"weight": 10, "target_amount": 75000},
                "BBB": 50,
            },
        )
        self.assertEqual(amount_target[0]["target_value"], 75000)
        self.assertEqual(amount_target[0]["target_weight"], 75)
        self.assertEqual(amount_target[0]["trade_value"], 15000)
        self.assertEqual(amount_target[0]["action"], "買い")

        inferred_weight = AssetManager.build_asset_allocation(
            df_items, {"AAA": 60, "BBB": {"weight": None}}
        )
        self.assertEqual(inferred_weight[1]["target_weight"], 40)
        self.assertEqual(inferred_weight[1]["target_value"], 40000)

        inferred_weight_with_amount = AssetManager.build_asset_allocation(
            df_items,
            {
                "AAA": {"weight": 30, "target_amount": 20000},
                "BBB": {"weight": None},
            },
        )
        self.assertEqual(inferred_weight_with_amount[1]["target_weight"], 80)
        self.assertEqual(inferred_weight_with_amount[1]["target_value"], 80000)

        multiple_missing_weights = AssetManager.build_asset_allocation(
            df_items,
            {"AAA": 60, "BBB": {"weight": None}, "CCC": {"weight": None}},
        )
        self.assertEqual(
            [item["ticker"] for item in multiple_missing_weights], ["AAA"]
        )


if __name__ == "__main__":
    unittest.main()
