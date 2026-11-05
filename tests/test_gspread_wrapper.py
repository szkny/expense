import unittest
from unittest.mock import Mock, patch

from expense.core.gspread_wrapper import GspreadHandler


class TestGspreadInitialization(unittest.TestCase):
    def test_constructor_sets_timeout_without_connecting_to_google(
        self,
    ) -> None:
        client = Mock()
        with (
            patch(
                "expense.core.gspread_wrapper.service_account.Credentials.from_service_account_file",
                return_value=Mock(),
            ),
            patch(
                "expense.core.gspread_wrapper.gspread.authorize",
                return_value=client,
            ),
            patch("expense.core.gspread_wrapper.GspreadHandler.load_sheet"),
        ):
            GspreadHandler("test-book")

        client.set_timeout.assert_called_once_with(30.0)
        client.open.assert_called_once_with("test-book")


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
        result = self.handler.delete_expense("2026-08-15", "賞与", 1000, "memo")

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


class TestIdempotentExpenseSync(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = GspreadHandler.__new__(GspreadHandler)
        self.handler.workbook = Mock()
        self.handler.sheet = Mock(id=10)
        self.handler.sheetname = "Apr"
        self.handler.sheet.acell.return_value = Mock(value="=1000")
        self.handler.sheet.range.return_value = []
        self.handler.load_sheet = Mock()
        self.handler.get_monthly_income_cell = Mock(return_value=None)
        self.handler.get_column = Mock(return_value="B")
        self.handler.get_row = Mock(return_value=38)
        self.ledger = Mock(id=99)
        self.ledger.col_values.return_value = ["event_id"]
        self.handler.workbook.worksheet.return_value = self.ledger

    def test_amount_removal_expands_multiplication_like_history_import(
        self,
    ) -> None:
        self.assertEqual(self.handler._amount_without("=500*2", 500), "=500")
        self.assertEqual(
            self.handler._amount_without("=500*2+1000", 1000), "=500 + 500"
        )

    def test_add_updates_amount_and_event_id_in_one_atomic_batch(self) -> None:
        self.handler.sync_expense_event(
            {
                "event_id": "event-1",
                "operation": "add",
                "payload": {
                    "expense_date": "2026-04-01T10:00:00.000000",
                    "expense_type": "食費",
                    "expense_memo": "",
                    "expense_amount": 250,
                },
            }
        )

        body = self.handler.workbook.batch_update.call_args.args[0]
        self.assertEqual(len(body["requests"]), 3)
        amount_request = next(
            request["updateCells"]
            for request in body["requests"]
            if "updateCells" in request
        )
        self.assertEqual(
            amount_request["rows"][0]["values"][0]["userEnteredValue"][
                "formulaValue"
            ],
            "=1000+250",
        )
        marker_request = next(
            request["appendCells"]
            for request in body["requests"]
            if "appendCells" in request
        )
        self.assertEqual(
            marker_request["rows"][0]["values"][0]["userEnteredValue"][
                "stringValue"
            ],
            "event-1",
        )

    def test_memo_add_uses_first_empty_cell_without_overwriting(self) -> None:
        self.handler.sheet.range.return_value = [
            Mock(address="B51", value=""),
            Mock(address="B52", value="交通費: 電車"),
            Mock(address="B53", value=""),
            Mock(address="B54", value=""),
        ]

        self.handler.sync_expense_event(
            {
                "event_id": "event-memo",
                "operation": "add",
                "payload": {
                    "expense_date": "2026-04-01T10:00:00.000000",
                    "expense_type": "食費",
                    "expense_memo": "昼食",
                    "expense_amount": 250,
                },
            }
        )

        requests = self.handler.workbook.batch_update.call_args.args[0][
            "requests"
        ]
        memo_update = next(
            request["updateCells"]
            for request in requests
            if request.get("updateCells", {}).get("start", {}).get("rowIndex")
            == 50
        )
        self.assertEqual(memo_update["start"]["columnIndex"], 1)
        self.assertEqual(
            memo_update["rows"][0]["values"][0]["userEnteredValue"][
                "stringValue"
            ],
            "食費: 昼食",
        )
        self.assertFalse(
            any(
                request.get("updateCells", {}).get("start", {}).get("rowIndex")
                == 51
                for request in requests
            )
        )

    def test_memo_add_with_no_empty_cell_does_not_commit_amount(self) -> None:
        self.handler.sheet.range.return_value = [
            Mock(address="B51", value="通信費: 携帯"),
            Mock(address="B52", value="交通費: 電車"),
            Mock(address="B53", value="食費: 昼食"),
            Mock(address="B54", value="医療費: 薬"),
        ]

        with self.assertRaisesRegex(ValueError, "no room"):
            self.handler.sync_expense_event(
                {
                    "event_id": "event-memo-full",
                    "operation": "add",
                    "payload": {
                        "expense_date": "2026-04-01T10:00:00.000000",
                        "expense_type": "書籍費",
                        "expense_memo": "本",
                        "expense_amount": 250,
                    },
                }
            )

        self.handler.workbook.batch_update.assert_not_called()

    def test_already_applied_event_is_not_written_again(self) -> None:
        self.ledger.col_values.return_value = ["event_id", "event-1"]

        self.handler.sync_expense_event(
            {
                "event_id": "event-1",
                "operation": "add",
                "payload": {
                    "expense_date": "2026-04-01T10:00:00.000000",
                    "expense_type": "食費",
                    "expense_memo": "",
                    "expense_amount": 250,
                },
            }
        )

        self.handler.workbook.batch_update.assert_not_called()
        self.handler.sheet.acell.assert_not_called()

    def test_retry_after_lost_response_uses_the_event_marker(self) -> None:
        event = {
            "event_id": "event-timeout",
            "operation": "add",
            "payload": {
                "expense_date": "2026-04-01T10:00:00.000000",
                "expense_type": "食費",
                "expense_memo": "",
                "expense_amount": 250,
            },
        }

        def apply_then_timeout(body: dict) -> None:
            self.ledger.col_values.return_value.append("event-timeout")
            raise TimeoutError("response lost")

        self.handler.workbook.batch_update.side_effect = apply_then_timeout
        with self.assertRaises(TimeoutError):
            self.handler.sync_expense_event(event)

        self.handler.workbook.batch_update.side_effect = None
        self.handler.workbook.batch_update.reset_mock()
        self.handler.sync_expense_event(event)

        self.handler.workbook.batch_update.assert_not_called()

    def test_edit_across_sheets_commits_both_cell_changes_together(
        self,
    ) -> None:
        old_sheet = Mock(id=11)
        new_sheet = Mock(id=12)
        old_sheet.acell.return_value = Mock(value="=1000+500")
        new_sheet.acell.return_value = Mock(value="=2000")
        sheets = {"2026-03-31": old_sheet, "2026-04-01": new_sheet}

        def load_sheet(date_str: str = "") -> None:
            self.handler.sheet = sheets.get(date_str[:10], new_sheet)

        self.handler.load_sheet = Mock(side_effect=load_sheet)
        self.handler.sync_expense_event(
            {
                "event_id": "event-edit",
                "operation": "edit",
                "payload": {
                    "before": {
                        "expense_date": "2026-03-31T10:00:00.000000",
                        "expense_type": "食費",
                        "expense_memo": "",
                        "expense_amount": 1000,
                    },
                    "after": {
                        "expense_date": "2026-04-01T10:00:00.000000",
                        "expense_type": "食費",
                        "expense_memo": "",
                        "expense_amount": 1500,
                    },
                },
            }
        )

        body = self.handler.workbook.batch_update.call_args.args[0]
        updates = [request["updateCells"] for request in body["requests"][:2]]
        self.assertEqual(
            [update["start"]["sheetId"] for update in updates], [11, 12]
        )
        self.assertEqual(
            [
                update["rows"][0]["values"][0]["userEnteredValue"][
                    "formulaValue"
                ]
                for update in updates
            ],
            ["=500", "=2000+1500"],
        )
        self.assertEqual(body["requests"][-1].keys(), {"appendCells"})


if __name__ == "__main__":
    unittest.main()
