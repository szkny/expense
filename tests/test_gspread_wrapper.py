import unittest
from unittest.mock import Mock

from src.expense.core.gspread_wrapper import GspreadHandler


class TestMonthlyIncomeCells(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = GspreadHandler.__new__(GspreadHandler)
        self.handler.monthly_income_cells = {
            "賞与": "E6",
            "譲渡益": "E25",
            "配当": "E26",
        }
        self.handler.sheet = Mock()
        self.handler.sheetname = "Aug"
        self.handler.load_sheet = Mock()

    def test_register_uses_fixed_cell(self) -> None:
        self.handler.add_amount_data = Mock()

        self.handler.register_expense("配当", 12000, "memo", "2026-08-15")

        self.handler.add_amount_data.assert_called_once_with("E26", 12000)

    def test_delete_uses_fixed_cell(self) -> None:
        cell = Mock(value="=1000+2000")
        self.handler.sheet.acell.return_value = cell
        result = self.handler.delete_expense(
            "2026-08-15", "賞与", 1000, "memo"
        )

        self.assertTrue(result)
        self.handler.sheet.update_acell.assert_called_once_with("E6", "=2000")

    def test_edit_moves_amount_between_months(self) -> None:
        self.handler.delete_expense = Mock(return_value=True)
        self.handler.register_expense = Mock()

        result = self.handler.edit_expense(
            {
                "expense_date": "2026-08-15",
                "expense_type": "賞与",
                "expense_amount": 1000,
                "expense_memo": "old",
            },
            {
                "expense_date": "2026-09-01",
                "expense_type": "賞与",
                "expense_amount": 2000,
                "expense_memo": "new",
            },
        )

        self.assertTrue(result)
        self.handler.delete_expense.assert_called_once_with(
            "2026-08-15", "賞与", 1000, ""
        )
        self.handler.register_expense.assert_called_once_with(
            "賞与", 2000, "", "2026-09-01"
        )


if __name__ == "__main__":
    unittest.main()
