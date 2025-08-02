import os
import unittest
import datetime
import pandas as pd
from unittest.mock import patch
from main import (
    normalize_capture_text,
    get_fiscal_year,
    filter_duplicates,
    get_favorite_expenses,
    get_frequent_expenses,
    get_recent_expenses,
    store_expense,
    ocr_main,
    get_latest_screenshot,
)


class TestMain(unittest.TestCase):

    def test_normalize_capture_text(self) -> None:
        self.assertEqual(normalize_capture_text("①②③"), "123")
        self.assertEqual(
            normalize_capture_text("０１２３４５６７８９"), "0123456789"
        )
        self.assertEqual(normalize_capture_text("あ い う え お"), "あいうえお")
        self.assertEqual(normalize_capture_text("①０ あ い"), "10 あい")

    def test_get_fiscal_year(self) -> None:
        with patch("main.datetime") as mock_datetime:
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
        list1 = [{"a": 1}, {"b": 2}]
        list2 = [{"b": 2}, {"c": 3}]
        list3 = [{"a": 1}, {"d": 4}]
        result = filter_duplicates([list1, list2, list3])
        self.assertEqual(result, [[{"a": 1}, {"b": 2}], [{"c": 3}], [{"d": 4}]])

    def test_get_favorite_expenses(self) -> None:
        with (
            patch("main.os.path.exists") as mock_exists,
            patch(
                "builtins.open",
                unittest.mock.mock_open(
                    read_data='[{"expense_type": "食費", "expense_memo": "", "expense_amount": 1000}]'
                ),
            ),
        ):
            mock_exists.return_value = True
            self.assertEqual(
                get_favorite_expenses(),
                [
                    {
                        "expense_type": "食費",
                        "expense_memo": "",
                        "expense_amount": 1000,
                    }
                ],
            )

            mock_exists.return_value = False
            self.assertEqual(get_favorite_expenses(), [])

    def test_get_frequent_expenses(self) -> None:
        with (
            patch("main.os.path.exists") as mock_exists,
            patch(
                "builtins.open",
                unittest.mock.mock_open(
                    read_data="2023-01-01,食費,,1000\n2023-01-01,食費,,1000\n2023-01-02,交通費,,500"
                ),
            ),
        ):
            mock_exists.return_value = True
            self.assertEqual(
                get_frequent_expenses(1),
                [
                    {
                        "expense_type": "食費",
                        "expense_memo": "",
                        "expense_amount": 1000,
                    }
                ],
            )

            mock_exists.return_value = False
            self.assertEqual(get_frequent_expenses(1), [])

    def test_get_recent_expenses(self) -> None:
        with (
            patch("main.os.path.exists") as mock_exists,
            patch(
                "builtins.open",
                unittest.mock.mock_open(
                    read_data="2023-01-01,食費,,1000\n2023-01-02,交通費,,500\n2023-01-03,遊興費,,2000"
                ),
            ),
        ):
            mock_exists.return_value = True
            self.assertEqual(
                get_recent_expenses(2),
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

            mock_exists.return_value = False
            self.assertEqual(get_recent_expenses(2), [])

    def test_store_expense(self) -> None:
        with patch("builtins.open", unittest.mock.mock_open()) as mock_open:
            store_expense("食費", "メモ", 1000)
            mock_open.assert_called_once_with(unittest.mock.ANY, "a")
            mock_open().write.assert_called_once()

    def test_ocr_main(self, n: int = 5, offset: int = 0) -> None:
        result = []
        for i in range(n):
            screenshot_name = get_latest_screenshot(offset + i)
            expense_data = ocr_main(offset + i)
            expense_amount = expense_data.get("expense_amount", "")
            expense_memo = expense_data.get("expense_memo", "")
            expense_type = expense_data.get("expense_type", "")
            result.append(
                {
                    "screenshot_name": os.path.basename(screenshot_name),
                    "expense_type": expense_type,
                    "expense_amount": expense_amount,
                    "expense_memo": expense_memo,
                }
            )
        df_result = pd.DataFrame(result)
        print(f"OCR results:\n{df_result}")


if __name__ == "__main__":
    unittest.main()
