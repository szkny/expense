import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from typing import TextIO
from unittest.mock import Mock

from expense.core.sync_worker import SheetsSyncRouter, SheetsSyncWorker


class TestSheetsSyncWorker(unittest.IsolatedAsyncioTestCase):
    async def test_success_marks_event_complete(self) -> None:
        event = {"event_id": "event-1", "operation": "add"}
        store = Mock(claim_next_sync_event=Mock(return_value=event))
        handler = Mock(sync_expense_event=Mock())
        worker = SheetsSyncWorker(store, handler)

        self.assertTrue(await worker.process_once())

        handler.sync_expense_event.assert_called_once_with(event)
        store.complete_sync_event.assert_called_once_with("event-1")
        store.retry_sync_event.assert_not_called()

    async def test_failure_is_persisted_for_retry_without_losing_event(
        self,
    ) -> None:
        event = {
            "event_id": "event-2",
            "operation": "edit",
            "attempts": 3,
        }
        store = Mock(claim_next_sync_event=Mock(return_value=event))
        handler = Mock(
            sync_expense_event=Mock(side_effect=TimeoutError("private details"))
        )
        worker = SheetsSyncWorker(store, handler)

        with self.assertLogs("expense", level="WARNING") as captured:
            self.assertTrue(await worker.process_once())

        store.retry_sync_event.assert_called_once_with(
            "event-2", "TimeoutError"
        )
        store.complete_sync_event.assert_not_called()
        message = "\n".join(captured.output)
        self.assertIn("event_id=event-2", message)
        self.assertIn("operation=edit", message)
        self.assertIn("attempt=3", message)
        self.assertIn("error=TimeoutError", message)
        self.assertIn("detail=omitted", message)
        self.assertNotIn("private details", message)

    async def test_failure_logs_safe_known_value_error_detail(self) -> None:
        event = {"event_id": "event-3", "operation": "delete", "attempts": 1}
        store = Mock(claim_next_sync_event=Mock(return_value=event))
        handler = Mock(
            sync_expense_event=Mock(
                side_effect=ValueError(
                    "Expense amount was not found in its sheet formula."
                )
            )
        )
        worker = SheetsSyncWorker(store, handler)

        with self.assertLogs("expense", level="WARNING") as captured:
            self.assertTrue(await worker.process_once())

        message = "\n".join(captured.output)
        self.assertIn(
            "detail=Expense amount was not found in its sheet formula.",
            message,
        )
        self.assertIn(" at=", message)

    async def test_empty_queue_does_not_call_sheets(self) -> None:
        store = Mock(claim_next_sync_event=Mock(return_value=None))
        handler = Mock()
        worker = SheetsSyncWorker(store, handler)

        self.assertFalse(await worker.process_once())

        handler.sync_expense_event.assert_not_called()

    async def test_worker_stops_gracefully_without_cancelling_a_sync(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Mock(
                database_path=Path(directory) / "expense_history.sqlite3",
                claim_next_sync_event=Mock(return_value=None),
            )
            worker = SheetsSyncWorker(store, Mock(), poll_interval=1)
            task = asyncio.create_task(worker.run())
            await asyncio.sleep(0)
            worker.stop()

            await asyncio.wait_for(task, timeout=1)

    def test_only_one_worker_owns_a_database_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Mock(database_path=Path(directory) / "history.sqlite3")
            first = SheetsSyncWorker(store, Mock())
            second = SheetsSyncWorker(store, Mock())
            lock_file = first._acquire_process_lock()
            self.assertIsNotNone(lock_file)
            self.assertIsNone(second._acquire_process_lock())
            assert lock_file is not None
            lock_file.close()
            lock_file = second._acquire_process_lock()
            self.assertIsNotNone(lock_file)
            assert lock_file is not None
            lock_file.close()

    async def test_worker_waits_for_process_lock_then_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "history.sqlite3"
            owner = SheetsSyncWorker(Mock(database_path=database_path), Mock())
            owner_lock = owner._acquire_process_lock()
            self.assertIsNotNone(owner_lock)
            assert owner_lock is not None

            store = Mock(
                database_path=database_path,
                claim_next_sync_event=Mock(return_value=None),
                recover_interrupted_sync_events=Mock(return_value=0),
            )
            claimed = threading.Event()
            store.claim_next_sync_event.side_effect = lambda: (
                claimed.set(),
                None,
            )[1]
            waiting_worker = SheetsSyncWorker(store, Mock(), poll_interval=0.01)
            task = asyncio.create_task(waiting_worker.run())
            await asyncio.sleep(0.03)
            store.claim_next_sync_event.assert_not_called()

            owner_lock.close()
            self.assertTrue(await asyncio.to_thread(claimed.wait, 1))
            store.claim_next_sync_event.assert_called()
            waiting_worker.stop()
            await asyncio.wait_for(task, timeout=1)

    async def test_startup_recovery_retries_transient_database_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recovered = threading.Event()
            attempts = 0

            def recover() -> int:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("temporary database error")
                recovered.set()
                return 0

            store = Mock(
                database_path=Path(directory) / "history.sqlite3",
                recover_interrupted_sync_events=Mock(side_effect=recover),
                claim_next_sync_event=Mock(return_value=None),
            )
            worker = SheetsSyncWorker(store, Mock(), poll_interval=0.01)
            task = asyncio.create_task(worker.run())
            self.assertTrue(await asyncio.to_thread(recovered.wait, 1))
            worker.stop()
            await asyncio.wait_for(task, timeout=1)

            self.assertEqual(
                store.recover_interrupted_sync_events.call_count, 2
            )

    async def test_transient_lock_file_error_does_not_end_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "history.sqlite3"
            store = Mock(
                database_path=database_path,
                recover_interrupted_sync_events=Mock(return_value=0),
                claim_next_sync_event=Mock(return_value=None),
            )
            worker = SheetsSyncWorker(store, Mock(), poll_interval=0.01)
            acquire_lock = worker._acquire_process_lock
            acquired = threading.Event()
            attempts = 0

            def acquire_with_transient_error() -> TextIO | None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError("temporary lock file error")
                lock_file = acquire_lock()
                acquired.set()
                return lock_file

            worker._acquire_process_lock = Mock(
                side_effect=acquire_with_transient_error
            )
            task = asyncio.create_task(worker.run())
            self.assertTrue(await asyncio.to_thread(acquired.wait, 1))
            worker.stop()
            await asyncio.wait_for(task, timeout=1)


class TestSheetsSyncRouter(unittest.TestCase):
    def test_routes_records_to_their_april_based_fiscal_year_book(self) -> None:
        old_book = Mock()
        new_book = Mock()
        handlers = {
            "CF (2025年度)": old_book,
            "CF (2026年度)": new_book,
        }
        router = SheetsSyncRouter(handlers.__getitem__)

        router.sync_expense_event(
            {
                "event_id": "event-1",
                "operation": "add",
                "payload": {
                    "expense_date": "2026-03-31T23:00:00.000000",
                    "expense_type": "食費",
                    "expense_memo": "",
                    "expense_amount": 1000,
                },
            }
        )
        router.sync_expense_event(
            {
                "event_id": "event-2",
                "operation": "add",
                "payload": {
                    "expense_date": "2026-04-01T00:00:00.000000",
                    "expense_type": "食費",
                    "expense_memo": "",
                    "expense_amount": 1500,
                },
            }
        )

        old_book.sync_expense_event.assert_called_once()
        new_book.sync_expense_event.assert_called_once()

    def test_cross_fiscal_year_edit_uses_retryable_delete_then_add_events(
        self,
    ) -> None:
        old_book = Mock()
        new_book = Mock()
        handlers = {
            "CF (2025年度)": old_book,
            "CF (2026年度)": new_book,
        }
        router = SheetsSyncRouter(handlers.__getitem__)
        event = {
            "event_id": "edit-1",
            "operation": "edit",
            "payload": {
                "before": {
                    "expense_date": "2026-03-31T10:00:00.000000",
                    "expense_type": "食費",
                    "expense_memo": "旧",
                    "expense_amount": 1000,
                },
                "after": {
                    "expense_date": "2026-04-01T10:00:00.000000",
                    "expense_type": "外食",
                    "expense_memo": "新",
                    "expense_amount": 1500,
                },
            },
        }

        router.sync_expense_event(event)

        delete_event = old_book.sync_expense_event.call_args.args[0]
        add_event = new_book.sync_expense_event.call_args.args[0]
        self.assertEqual(
            (delete_event["event_id"], delete_event["operation"]),
            ("edit-1:delete", "delete"),
        )
        self.assertEqual(
            (add_event["event_id"], add_event["operation"]),
            ("edit-1:add", "add"),
        )
        self.assertEqual(delete_event["payload"], event["payload"]["before"])
        self.assertEqual(add_event["payload"], event["payload"]["after"])

    def test_cross_year_retry_reuses_stable_sub_event_ids(self) -> None:
        old_book = Mock()
        new_book = Mock()
        new_book.sync_expense_event.side_effect = [
            RuntimeError("temporary Sheets failure"),
            None,
        ]
        handlers = {
            "CF (2025年度)": old_book,
            "CF (2026年度)": new_book,
        }
        router = SheetsSyncRouter(handlers.__getitem__)
        event = {
            "event_id": "edit-retry",
            "operation": "edit",
            "payload": {
                "before": {
                    "expense_date": "2026-03-31",
                    "expense_type": "食費",
                    "expense_memo": "旧",
                    "expense_amount": 1000,
                },
                "after": {
                    "expense_date": "2026-04-01",
                    "expense_type": "外食",
                    "expense_memo": "新",
                    "expense_amount": 1500,
                },
            },
        }

        with self.assertRaisesRegex(RuntimeError, "temporary Sheets failure"):
            router.sync_expense_event(event)
        router.sync_expense_event(event)

        delete_event_ids = [
            call.args[0]["event_id"]
            for call in old_book.sync_expense_event.call_args_list
        ]
        add_event_ids = [
            call.args[0]["event_id"]
            for call in new_book.sync_expense_event.call_args_list
        ]
        self.assertEqual(delete_event_ids, ["edit-retry:delete"] * 2)
        self.assertEqual(add_event_ids, ["edit-retry:add"] * 2)


if __name__ == "__main__":
    unittest.main()
