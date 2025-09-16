import os
import logging
import unittest
import datetime
import pandas as pd
from unittest.mock import patch
from src.expense.core.expense import get_fiscal_year, Expense
from src.expense.core.ocr import get_latest_screenshot, Ocr

log: logging.Logger = logging.getLogger("expense")


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

    def test_ocr_main(self, n: int = 3, offset: int = 0) -> None:
        ocr = Ocr()
        ocr.toast_enabled = False
        ocr.notify_enabled = False
        result = []
        for i in range(n):
            try:
                screenshot_name = get_latest_screenshot(offset + i)
                expense_data = ocr.main(offset + i)
                log.info(f"OCR result (No.{i}): {expense_data}")
                expense_amount = expense_data.get("expense_amount", "")
                expense_memo = expense_data.get("expense_memo", "")
                expense_type = expense_data.get("expense_type", "")
                expense_date = expense_data.get("expense_date", "")
                result.append(
                    {
                        "screenshot_name": os.path.basename(screenshot_name),
                        "expense_date": expense_date,
                        "expense_type": expense_type,
                        "expense_amount": expense_amount,
                        "expense_memo": expense_memo,
                    }
                )
            except Exception:
                log.exception(f"Error processing screenshot (No.{i})")
        df_result = pd.DataFrame(result)
        log.info(f"OCR results:\n{df_result}")


if __name__ == "__main__":
    unittest.main()
