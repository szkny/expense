import datetime as dt
import tempfile
import unittest
from pathlib import Path

from expense.core.expense import Expense


class TestRecurringExpenses(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.history_path = Path(self.temp_dir.name) / "history.log"
        self.expense = Expense.__new__(Expense)
        self.expense.expense_history = self.history_path
        self.expense.config = {
            "expense": {
                "expense_types": {
                    "income": ["給与"],
                    "irregular_income": ["賞与"],
                    "investment_income": ["配当"],
                    "capital_gain": ["譲渡益"],
                    "fixed": ["通信費", "保険料"],
                }
            }
        }

    def write_records(self, records: list[tuple[str, str, str, int]]) -> None:
        self.history_path.write_text(
            "".join(
                f"{date},{expense_type},{memo},{amount}\n"
                for date, expense_type, memo, amount in records
            ),
            encoding="utf-8",
        )

    def test_recommends_expense_repeated_on_same_day_for_three_months(
        self,
    ) -> None:
        self.write_records(
            [
                ("2026-01-15", "通信費", "携帯料金", 3000),
                ("2026-02-15", "通信費", "携帯料金", 3000),
                ("2026-03-15", "通信費", "携帯料金", 3000),
            ]
        )

        recommendations = self.expense.get_recurring_expenses(
            dt.date(2026, 4, 15)
        )

        self.assertEqual(
            recommendations,
            [
                {
                    "expense_type": "通信費",
                    "expense_memo": "携帯料金",
                    "expense_amount": 3000,
                }
            ],
        )

    def test_does_not_recommend_when_a_month_is_missing(self) -> None:
        self.write_records(
            [
                ("2026-01-15", "通信費", "携帯料金", 3000),
                ("2026-03-15", "通信費", "携帯料金", 3000),
            ]
        )

        self.assertEqual(
            self.expense.get_recurring_expenses(dt.date(2026, 4, 15)), []
        )

    def test_does_not_recommend_when_not_due_or_registered_this_month(
        self,
    ) -> None:
        self.write_records(
            [
                ("2026-01-15", "通信費", "携帯料金", 3000),
                ("2026-02-15", "通信費", "携帯料金", 3000),
                ("2026-03-15", "通信費", "携帯料金", 3000),
                ("2026-04-02", "通信費", "携帯料金", 3000),
            ]
        )

        self.assertEqual(
            self.expense.get_recurring_expenses(dt.date(2026, 4, 15)), []
        )
        self.assertEqual(
            self.expense.get_recurring_expenses(dt.date(2026, 4, 16)), []
        )

    def test_matches_type_amount_and_memo_exactly(self) -> None:
        self.write_records(
            [
                ("2026-01-15", "通信費", "携帯料金", 3000),
                ("2026-02-15", "通信費", "携帯料金", 3000),
                ("2026-03-15", "通信費", "携帯料金", 3001),
                ("2026-01-15", "通信費", "別の契約", 3000),
                ("2026-02-15", "通信費", "別の契約", 3000),
                ("2026-03-15", "保険料", "別の契約", 3000),
            ]
        )

        self.assertEqual(
            self.expense.get_recurring_expenses(dt.date(2026, 4, 15)), []
        )

    def test_excludes_income_and_missing_history(self) -> None:
        self.write_records(
            [
                ("2026-01-15", "給与", "給料", 300000),
                ("2026-02-15", "給与", "給料", 300000),
                ("2026-03-15", "給与", "給料", 300000),
            ]
        )
        self.assertEqual(
            self.expense.get_recurring_expenses(dt.date(2026, 4, 15)), []
        )

        self.history_path.unlink()
        self.assertEqual(
            self.expense.get_recurring_expenses(dt.date(2026, 4, 15)), []
        )


if __name__ == "__main__":
    unittest.main()
