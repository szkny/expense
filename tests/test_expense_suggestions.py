import argparse
import asyncio
import unittest
from unittest.mock import Mock, patch

from expense.api.server_tools import ServerTools
from expense.core.expense import Expense


def suggestion_records() -> tuple[list[dict], list[dict], list[dict]]:
    favorite_only = {
        "expense_type": "食費",
        "expense_memo": "お気に入り",
        "expense_amount": 100,
    }
    shared = {
        "expense_type": "食費",
        "expense_memo": "重複",
        "expense_amount": 200,
    }
    recent_only = {
        "expense_type": "食費",
        "expense_memo": "最近",
        "expense_amount": 300,
    }
    frequent_only = {
        "expense_type": "食費",
        "expense_memo": "頻出",
        "expense_amount": 400,
    }
    return (
        [favorite_only, shared],
        [shared, recent_only],
        [shared, recent_only, frequent_only],
    )


def make_expense(
    favorites: list[dict], recent: list[dict], frequent: list[dict]
) -> Expense:
    expense = Expense.__new__(Expense)
    expense.get_favorite_expenses = Mock(return_value=favorites)
    expense.get_recent_expenses = Mock(return_value=recent)
    expense.get_frequent_expenses = Mock(return_value=frequent)
    return expense


class TestCliExpenseSuggestions(unittest.TestCase):
    def test_favorites_then_recent_then_frequent_and_apply_limits(self) -> None:
        favorites, recent, frequent = suggestion_records()
        expense = make_expense(favorites, recent, frequent)
        expense.config = {
            "expense": {
                "icons": {
                    "favorite": "★",
                    "frequent": "F",
                    "recent": "R",
                },
                "num_instant_items": {"frequent": 2, "recent": 2},
                "filter_duplicated_items": True,
            }
        }
        expense.termux_api = Mock()
        expense.termux_api.select_expense_type.return_value = "手入力"
        expense.termux_api.enter_expense_amount.return_value = 500
        expense.termux_api.enter_expense_memo.return_value = "手入力メモ"
        expense.notification = Mock()
        expense.store_expense = Mock()

        with patch("expense.core.expense.GspreadHandler"):
            asyncio.run(
                expense.expense_main(
                    argparse.Namespace(
                        check_todays_expenses=False,
                        json_data="",
                        ocr_image=False,
                    )
                )
            )

        item_list = expense.termux_api.select_expense_type.call_args.kwargs[
            "item_list"
        ]
        self.assertEqual(
            item_list,
            [
                {"icon": "★", "items": favorites},
                {"icon": "F", "items": [frequent[-1]]},
                {"icon": "R", "items": [recent[-1]]},
            ],
        )


class TestWebExpenseSuggestions(unittest.TestCase):
    def make_server_tools(self, filter_duplicates: bool) -> ServerTools:
        favorites, recent, frequent = suggestion_records()
        server_tools = ServerTools.__new__(ServerTools)
        server_tools.config = {
            "expense": {
                "num_instant_items": {"frequent": 2, "recent": 2},
                "filter_duplicated_items": filter_duplicates,
            }
        }
        server_tools.icons = {
            "favorite": "★",
            "frequent": "F",
            "recent": "R",
        }
        server_tools.expense_types = ["食費"]
        server_tools.expense_handler = make_expense(favorites, recent, frequent)
        return server_tools

    def test_formats_de_deduplicated_candidates_in_web_display_order(
        self,
    ) -> None:
        server_tools = self.make_server_tools(filter_duplicates=True)

        items = server_tools.generate_items()

        self.assertEqual(
            items,
            [
                "",
                "[HEAD] インスタント登録",
                "★ 食費/お気に入り/¥100",
                "★ 食費/重複/¥200",
                "F 食費/頻出/¥400",
                "R 食費/最近/¥300",
                "[HEAD] 支出タイプ",
                "食費",
            ],
        )

    def test_preserves_duplicates_when_filtering_is_disabled(self) -> None:
        server_tools = self.make_server_tools(filter_duplicates=False)

        items = server_tools.generate_items()

        self.assertEqual(
            items,
            [
                "",
                "[HEAD] インスタント登録",
                "★ 食費/お気に入り/¥100",
                "★ 食費/重複/¥200",
                "F 食費/重複/¥200",
                "F 食費/最近/¥300",
                "R 食費/重複/¥200",
                "R 食費/最近/¥300",
                "[HEAD] 支出タイプ",
                "食費",
            ],
        )


if __name__ == "__main__":
    unittest.main()
