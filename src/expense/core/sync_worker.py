import asyncio
import datetime as dt
import fcntl
import logging
from pathlib import Path
from typing import Any, Callable, Protocol, TextIO


log: logging.Logger = logging.getLogger("expense")


class SyncStore(Protocol):
    database_path: Path

    def claim_next_sync_event(self) -> dict[str, Any] | None: ...

    def recover_interrupted_sync_events(self) -> int: ...

    def renew_sync_event_lease(self, event_id: str) -> bool: ...

    def complete_sync_event(self, event_id: str) -> bool: ...

    def retry_sync_event(self, event_id: str, error_code: str) -> None: ...


class SheetsSyncHandler(Protocol):
    def sync_expense_event(self, event: dict[str, Any]) -> None: ...


class SheetsSyncRouter:
    def __init__(
        self,
        handler_factory: Callable[[str], SheetsSyncHandler],
    ) -> None:
        log.info("start 'SheetsSyncRouter.__init__' method")
        self.handler_factory = handler_factory
        self.handlers: dict[str, SheetsSyncHandler] = {}
        log.info("end 'SheetsSyncRouter.__init__' method")

    def sync_expense_event(self, event: dict[str, Any]) -> None:
        log.info("start 'SheetsSyncRouter.sync_expense_event' method")
        try:
            operation = str(event["operation"])
            payload = event["payload"]
            if operation in ("add", "delete"):
                date_value = str(payload["expense_date"])
                self._handler_for(date_value).sync_expense_event(event)
                return
            if operation != "edit":
                raise ValueError(f"Unsupported sync operation: {operation}")

            before = payload["before"]
            after = payload["after"]
            before_date = str(before["expense_date"])
            after_date = str(after["expense_date"])
            before_book = self._book_name(before_date)
            after_book = self._book_name(after_date)
            if before_book == after_book:
                self._handler_for(before_date).sync_expense_event(event)
                return

            event_id = str(event["event_id"])
            self._handler_for(before_date).sync_expense_event(
                {
                    **event,
                    "event_id": f"{event_id}:delete",
                    "operation": "delete",
                    "payload": before,
                }
            )
            self._handler_for(after_date).sync_expense_event(
                {
                    **event,
                    "event_id": f"{event_id}:add",
                    "operation": "add",
                    "payload": after,
                }
            )
        finally:
            log.info("end 'SheetsSyncRouter.sync_expense_event' method")

    def _handler_for(self, expense_date: str) -> SheetsSyncHandler:
        log.debug("start 'SheetsSyncRouter._handler_for' method")
        try:
            book_name = self._book_name(expense_date)
            handler = self.handlers.get(book_name)
            if handler is None:
                handler = self.handler_factory(book_name)
                self.handlers[book_name] = handler
            return handler
        finally:
            log.debug("end 'SheetsSyncRouter._handler_for' method")

    @staticmethod
    def _book_name(expense_date: str) -> str:
        log.debug("start 'SheetsSyncRouter._book_name' method")
        try:
            date = dt.date.fromisoformat(expense_date[:10])
            fiscal_year = date.year if date.month >= 4 else date.year - 1
            return f"CF ({fiscal_year}年度)"
        finally:
            log.debug("end 'SheetsSyncRouter._book_name' method")


class SheetsSyncWorker:
    def __init__(
        self,
        store: SyncStore,
        handler: SheetsSyncHandler,
        poll_interval: float = 2.0,
    ) -> None:
        log.info("start 'SheetsSyncWorker.__init__' method")
        self.store = store
        self.handler = handler
        self.poll_interval = poll_interval
        self._stop_event = asyncio.Event()
        self._lock_path = store.database_path.with_name(
            ".expense-sheets-sync.lock"
        )
        log.info("end 'SheetsSyncWorker.__init__' method")

    async def run(self) -> None:
        log.info("start 'SheetsSyncWorker.run' method")
        lock_file: TextIO | None = None
        try:
            waiting_for_lock = False
            while lock_file is None and not self._stop_event.is_set():
                try:
                    lock_file = self._acquire_process_lock()
                except OSError as exc:
                    if not waiting_for_lock:
                        log.error(
                            "Sheets sync lock unavailable (%s).",
                            type(exc).__name__,
                        )
                    waiting_for_lock = True
                    lock_file = None
                if lock_file is None:
                    if not waiting_for_lock:
                        log.info(
                            "Another Sheets sync worker owns the data directory; waiting."
                        )
                        waiting_for_lock = True
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self.poll_interval,
                        )
                    except asyncio.TimeoutError:
                        pass
            if lock_file is None:
                return
            if waiting_for_lock:
                log.info("Sheets sync worker acquired the data directory lock.")
            recovery_complete = False
            while not self._stop_event.is_set():
                if not recovery_complete:
                    try:
                        await asyncio.to_thread(
                            self.store.recover_interrupted_sync_events
                        )
                        recovery_complete = True
                    except Exception as exc:
                        log.error(
                            "Sheets sync recovery failed (%s).",
                            type(exc).__name__,
                        )
                        try:
                            await asyncio.wait_for(
                                self._stop_event.wait(),
                                timeout=self.poll_interval,
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue
                try:
                    processed = await self.process_once()
                except Exception as exc:
                    log.error(
                        "Sheets sync worker failed (%s).",
                        type(exc).__name__,
                    )
                    processed = False
                if not processed:
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self.poll_interval,
                        )
                    except asyncio.TimeoutError:
                        pass
        finally:
            try:
                if lock_file is not None:
                    lock_file.close()
            finally:
                log.info("end 'SheetsSyncWorker.run' method")

    def _acquire_process_lock(self) -> TextIO | None:
        log.debug("start 'SheetsSyncWorker._acquire_process_lock' method")
        try:
            lock_file = self._lock_path.open("a")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lock_file.close()
                return None
            return lock_file
        finally:
            log.debug("end 'SheetsSyncWorker._acquire_process_lock' method")

    def stop(self) -> None:
        log.debug("start 'SheetsSyncWorker.stop' method")
        try:
            self._stop_event.set()
        finally:
            log.debug("end 'SheetsSyncWorker.stop' method")

    async def process_once(self) -> bool:
        log.info("start 'SheetsSyncWorker.process_once' method")
        try:
            event = await asyncio.to_thread(self.store.claim_next_sync_event)
            if event is None:
                return False

            event_id = str(event["event_id"])
            lease_task = asyncio.create_task(self._renew_lease(event_id))
            try:
                await asyncio.to_thread(self.handler.sync_expense_event, event)
            except Exception as exc:
                await asyncio.to_thread(
                    self.store.retry_sync_event,
                    event_id,
                    type(exc).__name__,
                )
                log.warning(
                    "Sheets sync event will retry (%s).", type(exc).__name__
                )
                return True
            finally:
                lease_task.cancel()
                try:
                    await lease_task
                except asyncio.CancelledError:
                    pass

            await asyncio.to_thread(self.store.complete_sync_event, event_id)
            log.info("Sheets sync event completed.")
            return True
        finally:
            log.info("end 'SheetsSyncWorker.process_once' method")

    async def _renew_lease(self, event_id: str) -> None:
        log.debug("start 'SheetsSyncWorker._renew_lease' method")
        try:
            while True:
                await asyncio.sleep(60)
                try:
                    renewed = await asyncio.to_thread(
                        self.store.renew_sync_event_lease, event_id
                    )
                except Exception as exc:
                    log.warning(
                        "Failed to renew Sheets sync lease (%s).",
                        type(exc).__name__,
                    )
                    continue
                if not renewed:
                    log.warning(
                        "Sheets sync lease is no longer owned by this worker."
                    )
                    return
        finally:
            log.debug("end 'SheetsSyncWorker._renew_lease' method")
