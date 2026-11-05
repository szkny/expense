import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from expense.core.expense import Expense
from expense.core.gspread_wrapper import GspreadHandler
from expense.core.history_store import ExpenseHistoryStore


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
    def test_edit_to_unconfigured_type_does_not_change_or_queue_record(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expense = Expense.__new__(Expense)
            expense.expense_history = Path(directory) / "history.log"
            expense.config = {
                "expense": {"expense_types": {"variable": ["食費"]}}
            }
            original = "2026-04-01T10:00:00.000000,食費,昼食,1000\n"
            expense.expense_history.write_text(original, encoding="utf-8")

            result = expense.edit_expense(
                {
                    "expense_date": "2026-04-01",
                    "expense_type": "食費",
                    "expense_memo": "昼食",
                    "expense_amount": 1000,
                },
                {
                    "expense_date": "2026-04-02",
                    "expense_type": "未設定",
                    "expense_memo": "夕食",
                    "expense_amount": 1200,
                },
            )

            self.assertFalse(result)
            self.assertEqual(
                expense.expense_history.read_text(encoding="utf-8"), original
            )
            self.assertFalse(
                expense.expense_history.with_suffix(".sqlite3").exists()
            )

    def test_existing_sqlite_history_schema_is_migrated_for_sync_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "expense_history.log"
            database_path = csv_path.with_suffix(".sqlite3")
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE expenses (
                        id INTEGER PRIMARY KEY,
                        expense_date TEXT NOT NULL,
                        expense_type TEXT NOT NULL,
                        expense_memo TEXT NOT NULL,
                        expense_amount INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO metadata VALUES ('legacy_csv_imported', '1')"
                )
                connection.execute(
                    "INSERT INTO metadata VALUES ('revision', '1')"
                )
                connection.execute(
                    "INSERT INTO metadata VALUES ('csv_revision', '1')"
                )
                connection.execute(
                    """
                    INSERT INTO expenses (
                        expense_date, expense_type, expense_memo,
                        expense_amount
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("2026-04-01T10:00:00.000000", "食費", "昼食", 1000),
                )

            store = ExpenseHistoryStore(csv_path)

            self.assertEqual(store.records_with_sync_status()[0][-1], "synced")
            self.assertEqual(store.get_sync_overview()["counts"]["pending"], 0)
            self.assertTrue(csv_path.is_file())

    def test_legacy_csv_is_imported_once_and_kept_as_csv_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "expense_history.log"
            csv_path.write_text(
                "2026-04-01T10:00:00.000000,食費,昼食,1000\n"
                "2026-04-02T10:00:00.000000,食費,昼,夕食,1200\n",
                encoding="utf-8",
            )

            store = ExpenseHistoryStore(csv_path)
            self.assertEqual(
                store.records(),
                [
                    ("2026-04-01T10:00:00.000000", "食費", "昼食", 1000),
                    (
                        "2026-04-02T10:00:00.000000",
                        "食費",
                        "昼,夕食",
                        1200,
                    ),
                ],
            )
            store.add("外食", "夕食,会食", 2500, "2026-04-03T10:00:00.000000")

            reopened_store = ExpenseHistoryStore(csv_path)
            self.assertEqual(len(reopened_store.records()), 3)
            self.assertEqual(
                csv_path.read_text(encoding="utf-8").splitlines()[-1],
                '2026-04-03T10:00:00.000000,外食,"夕食,会食",2500',
            )

    def test_failed_csv_mirror_is_retried_when_store_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "expense_history.log"
            store = ExpenseHistoryStore(csv_path)
            with (
                self.assertLogs("expense", level="ERROR"),
                patch(
                    "expense.core.history_store.os.replace",
                    side_effect=OSError("mirror unavailable"),
                ),
            ):
                store.add("食費", "昼食", 1000, "2026-04-01T10:00:00.000000")

            reopened_store = ExpenseHistoryStore(csv_path)
            self.assertEqual(len(reopened_store.records()), 1)
            self.assertEqual(
                csv_path.read_text(encoding="utf-8"),
                "2026-04-01T10:00:00.000000,食費,昼食,1000\n",
            )

    def test_history_changes_and_sync_events_share_a_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExpenseHistoryStore(Path(directory) / "history.log")
            record_id = store.add(
                "食費", "昼食", 1000, "2026-04-01T10:00:00.000000"
            )

            added = store.claim_next_sync_event()
            self.assertIsNotNone(added)
            assert added is not None
            self.assertEqual(added["operation"], "add")
            self.assertEqual(added["record_id"], record_id)
            self.assertTrue(store.complete_sync_event(added["event_id"]))
            self.assertEqual(store.records_with_sync_status()[0][-1], "synced")

            self.assertTrue(
                store.edit(
                    "2026-04-01",
                    "食費",
                    1000,
                    "昼食",
                    "2026-04-02",
                    "外食",
                    1500,
                    "夕食",
                )
            )
            edited = store.claim_next_sync_event()
            self.assertIsNotNone(edited)
            assert edited is not None
            self.assertEqual(edited["operation"], "edit")
            self.assertEqual(
                edited["payload"]["before"]["expense_type"], "食費"
            )
            self.assertEqual(edited["payload"]["after"]["expense_type"], "外食")
            self.assertTrue(store.complete_sync_event(edited["event_id"]))

            self.assertTrue(store.delete("2026-04-02", "外食", 1500, "夕食"))
            deleted = store.claim_next_sync_event()
            self.assertIsNotNone(deleted)
            assert deleted is not None
            self.assertEqual(deleted["operation"], "delete")
            self.assertEqual(len(store.records()), 0)

    def test_failed_enqueue_rolls_back_local_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExpenseHistoryStore(Path(directory) / "history.log")
            with patch.object(
                store,
                "_enqueue_sync_event",
                side_effect=RuntimeError("queue unavailable"),
            ):
                with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
                    store.add(
                        "食費", "昼食", 1000, "2026-04-01T10:00:00.000000"
                    )

            self.assertEqual(store.records(), [])
            self.assertEqual(store.get_sync_overview()["counts"]["pending"], 0)

    def test_sync_failure_is_durable_and_can_be_retried_manually(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExpenseHistoryStore(Path(directory) / "history.log")
            record_id = store.add(
                "食費", "昼食", 1000, "2026-04-01T10:00:00.000000"
            )
            event = store.claim_next_sync_event()
            self.assertIsNotNone(event)
            assert event is not None
            store.retry_sync_event(event["event_id"], "TimeoutError")

            overview = store.get_sync_overview()
            self.assertEqual(overview["counts"]["retrying"], 1)
            self.assertEqual(
                next(
                    row
                    for row in store.records_with_sync_status()
                    if row[0] == record_id
                )[-1],
                "retrying",
            )
            self.assertEqual(store.retry_all_sync_events(), 1)
            self.assertEqual(store.get_sync_overview()["counts"]["pending"], 1)

    def test_failed_record_blocks_its_later_events_but_not_other_records(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExpenseHistoryStore(Path(directory) / "history.log")
            first_id = store.add(
                "食費", "昼食", 1000, "2026-04-01T10:00:00.000000"
            )
            second_id = store.add(
                "交通費", "電車", 500, "2026-04-01T11:00:00.000000"
            )
            first = store.claim_next_sync_event()
            self.assertIsNotNone(first)
            assert first is not None
            store.retry_sync_event(first["event_id"], "TimeoutError")
            self.assertTrue(
                store.edit(
                    "2026-04-01",
                    "食費",
                    1000,
                    "昼食",
                    "2026-04-01",
                    "外食",
                    1500,
                    "夕食",
                )
            )

            second = store.claim_next_sync_event()
            self.assertIsNotNone(second)
            assert second is not None
            self.assertEqual(second["record_id"], second_id)
            self.assertNotEqual(second["record_id"], first_id)
            self.assertTrue(store.complete_sync_event(second["event_id"]))
            self.assertIsNone(store.claim_next_sync_event())

    def test_active_sync_lease_can_be_renewed_until_event_completes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExpenseHistoryStore(Path(directory) / "history.log")
            store.add("食費", "昼食", 1000, "2026-04-01T10:00:00.000000")
            event = store.claim_next_sync_event()
            self.assertIsNotNone(event)
            assert event is not None

            self.assertIsNone(store.claim_next_sync_event())
            self.assertTrue(store.renew_sync_event_lease(event["event_id"]))
            self.assertTrue(store.complete_sync_event(event["event_id"]))
            self.assertFalse(store.renew_sync_event_lease(event["event_id"]))

    def test_interrupted_sync_is_requeued_after_worker_lock_is_acquired(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ExpenseHistoryStore(Path(directory) / "history.log")
            store.add("食費", "昼食", 1000, "2026-04-01T10:00:00.000000")
            first_attempt = store.claim_next_sync_event()
            self.assertIsNotNone(first_attempt)
            assert first_attempt is not None

            self.assertEqual(store.recover_interrupted_sync_events(), 0)
            self.assertIsNone(store.claim_next_sync_event())
            with store._transaction() as connection:
                connection.execute(
                    "UPDATE sync_events SET lease_until = '2000-01-01' "
                    "WHERE event_id = ?",
                    (first_attempt["event_id"],),
                )
            self.assertEqual(store.recover_interrupted_sync_events(), 1)
            recovered_attempt = store.claim_next_sync_event()
            self.assertIsNotNone(recovered_attempt)
            assert recovered_attempt is not None
            self.assertEqual(
                recovered_attempt["event_id"], first_attempt["event_id"]
            )
            self.assertEqual(recovered_attempt["attempts"], 2)

    def test_edit_changes_only_last_duplicate_and_keeps_same_day_timestamp(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            expense = Expense.__new__(Expense)
            expense.expense_history = Path(directory) / "history.log"
            expense.config = {
                "expense": {"expense_types": {"variable": ["食費", "外食"]}}
            }
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
