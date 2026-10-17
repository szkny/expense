import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from expense.core.expense import Expense
from expense.core.gspread_wrapper import GspreadHandler


class TestSheetHistoryConversion(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = GspreadHandler.__new__(GspreadHandler)
        self.handler.expense_types = ["食費", "交通費"]

    def test_converts_fixed_sheet_rows_to_history_column_order(self) -> None:
        sheet_rows = pd.DataFrame(
            {
                "食費": ["=1000+500", "0"],
                "交通費": ["=600*2", "=800"],
                "memo": [
                    ["食費: 昼食, 夕食", "交通費: 電車, バス"],
                    [],
                ],
            },
            index=pd.to_datetime(["2026-04-01", "2026-04-02"]),
        )

        records = self.handler.convert_expense_sheet_to_history_records(
            sheet_rows
        )

        self.assertEqual(
            list(records.columns),
            ["date", "expense_type", "expense_memo", "expense_amount"],
        )
        self.assertEqual(
            list(records.itertuples(index=False, name=None)),
            [
                ("2026-04-01T00:00:00.000000", "食費", "昼食", 1000),
                ("2026-04-01T00:00:00.000000", "食費", "夕食", 500),
                ("2026-04-01T00:00:00.000000", "交通費", "電車", 600),
                ("2026-04-01T00:00:00.000000", "交通費", "バス", 600),
                ("2026-04-02T00:00:00.000000", "交通費", "", 800),
            ],
        )

    def test_empty_sheet_rows_return_empty_history_schema(self) -> None:
        sheet_rows = pd.DataFrame(
            columns=["食費", "交通費", "memo"],
            index=pd.DatetimeIndex([]),
        )

        records = self.handler.convert_expense_sheet_to_history_records(
            sheet_rows
        )

        self.assertTrue(records.empty)
        self.assertEqual(
            list(records.columns),
            ["date", "expense_type", "expense_memo", "expense_amount"],
        )


class TestHistoryFiles(unittest.TestCase):
    def test_edit_changes_only_last_duplicate_and_keeps_same_day_timestamp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expense = Expense.__new__(Expense)
            expense.expense_history = Path(directory) / "history.log"
            expense.expense_history.write_text(
                "2026-04-01T09:00:00.000000,食費,昼食,1000\n"
                "2026-04-01T10:00:00.000000,食費,昼食,1000\n",
                encoding="utf-8",
            )

            result = expense.edit_expense(
                {
                    "expense_date": "2026-04-01",
                    "expense_type": "食費",
                    "expense_memo": "昼食",
                    "expense_amount": "¥1,000",
                },
                {
                    "expense_date": "2026-04-01",
                    "expense_type": "食費",
                    "expense_memo": "夕食",
                    "expense_amount": "¥2,500",
                },
            )

            self.assertTrue(result)
            self.assertEqual(
                expense.expense_history.read_text(
                    encoding="utf-8"
                ).splitlines(),
                [
                    "2026-04-01T09:00:00.000000,食費,昼食,1000",
                    "2026-04-01T10:00:00.000000,食費,夕食,2500",
                ],
            )

    def test_merge_deduplicates_across_files_but_preserves_source_duplicates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handler = GspreadHandler.__new__(GspreadHandler)
            handler.data_path = Path(directory)
            original = (
                "2026-04-01T10:00:00.000000,食費,昼食,1000\n"
                "2026-04-01T10:00:00.000000,食費,昼食,1000\n"
            )
            (handler.data_path / "expense_history.log").write_text(
                original, encoding="utf-8"
            )
            (handler.data_path / "expense_history_downloaded.log").write_text(
                original + "2026-04-02T10:00:00.000000,交通費,電車,500\n",
                encoding="utf-8",
            )

            self.assertTrue(handler.merge_expense_history_log())

            merged = handler.data_path / "merged_expense_history.log"
            self.assertEqual(
                merged.read_text(encoding="utf-8").splitlines(),
                [
                    "2026-04-01T10:00:00.000000,食費,昼食,1000",
                    "2026-04-01T10:00:00.000000,食費,昼食,1000",
                    "2026-04-02T10:00:00.000000,交通費,電車,500",
                ],
            )

    def test_merge_with_no_history_files_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handler = GspreadHandler.__new__(GspreadHandler)
            handler.data_path = Path(directory)

            self.assertFalse(handler.merge_expense_history_log())
            self.assertFalse(
                (handler.data_path / "merged_expense_history.log").exists()
            )


class TestSheetEdits(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = GspreadHandler.__new__(GspreadHandler)
        self.handler.sheet = Mock()
        self.handler.sheetname = "Apr"

    def test_edit_replaces_last_matching_amount_in_cell_formula(self) -> None:
        self.handler.sheet.acell.return_value = Mock(value="=1000+1000")

        result = self.handler.edit_amount_at_label("B31", 1000, 1500)

        self.assertTrue(result)
        self.handler.sheet.update_acell.assert_called_once_with(
            "B31", "=1000+1500"
        )

    def test_edit_replaces_last_matching_memo_in_cell_text(self) -> None:
        self.handler.sheet.range.return_value = [
            Mock(value="食費: 昼食, おやつ, おやつ", address="B51")
        ]

        result = self.handler.edit_memo("B", "食費", "おやつ", "夕食")

        self.assertTrue(result)
        self.handler.sheet.update_acell.assert_called_once_with(
            "B51", "食費: 昼食, おやつ, 夕食"
        )


if __name__ == "__main__":
    unittest.main()
