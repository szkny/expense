import csv
import datetime as dt
import json
import logging
import os
import pathlib
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Iterator, ParamSpec, TypeVar


log: logging.Logger = logging.getLogger("expense")
P = ParamSpec("P")
R = TypeVar("R")


def _log_method(
    level: int = logging.INFO,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            log.log(level, "start '%s' method", func.__name__)
            try:
                return func(*args, **kwargs)
            finally:
                log.log(level, "end '%s' method", func.__name__)

        return wrapped

    return decorate


class ExpenseHistoryStore:
    """SQLite-backed expense history with a headerless CSV mirror."""

    @_log_method()
    def __init__(self, csv_path: pathlib.Path) -> None:
        self.csv_path = pathlib.Path(csv_path)
        self.database_path = self.csv_path.with_suffix(".sqlite3")
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _transaction(
        self, immediate: bool = True
    ) -> Iterator[sqlite3.Connection]:
        log.debug("start '_transaction' method")
        try:
            connection = sqlite3.connect(self.database_path, timeout=5)
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
        finally:
            log.debug("end '_transaction' method")

    @_log_method()
    def _initialize(self) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY,
                    expense_date TEXT NOT NULL,
                    expense_type TEXT NOT NULL,
                    expense_memo TEXT NOT NULL,
                    expense_amount INTEGER NOT NULL,
                    sync_status TEXT NOT NULL DEFAULT 'synced',
                    sync_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            expense_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(expenses)")
            }
            if "sync_status" not in expense_columns:
                connection.execute(
                    "ALTER TABLE expenses ADD COLUMN sync_status "
                    "TEXT NOT NULL DEFAULT 'synced'"
                )
            if "sync_error" not in expense_columns:
                connection.execute(
                    "ALTER TABLE expenses ADD COLUMN sync_error "
                    "TEXT NOT NULL DEFAULT ''"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    record_id INTEGER,
                    operation TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL,
                    lease_until TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            migrated = connection.execute(
                "SELECT value FROM metadata WHERE key = 'legacy_csv_imported'"
            ).fetchone()
            if migrated is None:
                records = self._read_legacy_csv()
                connection.executemany(
                    """
                    INSERT INTO expenses (
                        expense_date,
                        expense_type,
                        expense_memo,
                        expense_amount
                    ) VALUES (?, ?, ?, ?)
                    """,
                    records,
                )
                self._set_metadata(connection, "legacy_csv_imported", "1")
                self._set_metadata(
                    connection, "revision", "1" if records else "0"
                )
                self._set_metadata(connection, "csv_revision", "-1")
            else:
                self._set_metadata_if_missing(connection, "revision", "0")
                self._set_metadata_if_missing(connection, "csv_revision", "-1")

        self._sync_csv_if_needed()

    @_log_method(logging.DEBUG)
    def _read_legacy_csv(self) -> list[tuple[str, str, str, int]]:
        if not self.csv_path.exists():
            return []

        records: list[tuple[str, str, str, int]] = []
        with self.csv_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as csv_file:
            for line_number, row in enumerate(csv.reader(csv_file), start=1):
                if not row:
                    continue
                if len(row) < 4:
                    raise ValueError(
                        f"Invalid expense history CSV row: {line_number}"
                    )
                try:
                    amount = int(row[-1])
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid expense amount in CSV row: {line_number}"
                    ) from exc
                records.append((row[0], row[1], ",".join(row[2:-1]), amount))
        return records

    @staticmethod
    @_log_method(logging.DEBUG)
    def _set_metadata(
        connection: sqlite3.Connection, key: str, value: str
    ) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )

    @staticmethod
    @_log_method(logging.DEBUG)
    def _set_metadata_if_missing(
        connection: sqlite3.Connection, key: str, value: str
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO metadata (key, value) VALUES (?, ?)",
            (key, value),
        )

    @_log_method()
    def _sync_csv_if_needed(self) -> None:
        try:
            self._write_csv_mirror()
        except Exception:
            log.exception("Failed to update the expense history CSV mirror.")

    @_log_method(logging.DEBUG)
    def _write_csv_mirror(self) -> None:
        temporary_path: pathlib.Path | None = None
        with self._transaction() as connection:
            revision = int(
                connection.execute(
                    "SELECT value FROM metadata WHERE key = 'revision'"
                ).fetchone()[0]
            )
            csv_revision = int(
                connection.execute(
                    "SELECT value FROM metadata WHERE key = 'csv_revision'"
                ).fetchone()[0]
            )
            if revision == csv_revision and self.csv_path.exists():
                return

            records = connection.execute(
                """
                SELECT expense_date, expense_type, expense_memo, expense_amount
                FROM expenses
                ORDER BY expense_date, id
                """
            ).fetchall()
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    dir=self.csv_path.parent,
                    prefix=f".{self.csv_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary_file:
                    temporary_path = pathlib.Path(temporary_file.name)
                    csv.writer(temporary_file, lineterminator="\n").writerows(
                        records
                    )
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary_path, self.csv_path)
                self._set_metadata(connection, "csv_revision", str(revision))
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    @_log_method()
    def records(self) -> list[tuple[str, str, str, int]]:
        with self._transaction(immediate=False) as connection:
            rows = connection.execute(
                """
                SELECT expense_date, expense_type, expense_memo, expense_amount
                FROM expenses
                ORDER BY expense_date, id
                """
            ).fetchall()
        return [
            (str(row[0]), str(row[1]), str(row[2]), int(row[3])) for row in rows
        ]

    @_log_method()
    def records_with_sync_status(
        self,
    ) -> list[tuple[int, str, str, str, int, str]]:
        with self._transaction(immediate=False) as connection:
            rows = connection.execute(
                """
                SELECT id, expense_date, expense_type, expense_memo,
                       expense_amount, sync_status
                FROM expenses
                ORDER BY expense_date DESC, id DESC
                """
            ).fetchall()
        return [
            (
                int(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                int(row[4]),
                str(row[5]),
            )
            for row in rows
        ]

    @_log_method()
    def add(
        self,
        expense_type: str,
        expense_memo: str,
        expense_amount: int,
        expense_date: str,
        enqueue_sync: bool = True,
    ) -> int:
        event_id = uuid.uuid4().hex
        created_at = dt.datetime.now().isoformat(timespec="seconds")
        payload = {
            "expense_date": expense_date,
            "expense_type": expense_type,
            "expense_memo": expense_memo,
            "expense_amount": expense_amount,
        }
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO expenses (
                    expense_date,
                    expense_type,
                    expense_memo,
                    expense_amount,
                    sync_status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    expense_date,
                    expense_type,
                    expense_memo,
                    expense_amount,
                    "pending" if enqueue_sync else "synced",
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to create an expense record ID.")
            record_id = int(cursor.lastrowid)
            if enqueue_sync:
                self._enqueue_sync_event(
                    connection,
                    event_id,
                    record_id,
                    "add",
                    payload,
                    created_at,
                )
            self._increment_revision(connection)
        self._sync_csv_if_needed()
        return record_id

    @_log_method()
    def delete(
        self,
        target_date: str,
        target_type: str,
        target_amount: int,
        target_memo: str,
    ) -> bool:
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT id, expense_date, expense_type, expense_memo,
                       expense_amount
                FROM expenses ORDER BY expense_date DESC, id DESC
                """
            ).fetchall()
            target = next(
                (
                    row
                    for row in rows
                    if self._matches(
                        row,
                        target_date,
                        target_type,
                        target_amount,
                        target_memo,
                    )
                ),
                None,
            )
            if target is None:
                return False
            payload = {
                "expense_date": str(target[1]),
                "expense_type": str(target[2]),
                "expense_memo": str(target[3]),
                "expense_amount": int(target[4]),
            }
            self._enqueue_sync_event(
                connection,
                uuid.uuid4().hex,
                int(target[0]),
                "delete",
                payload,
                dt.datetime.now().isoformat(timespec="seconds"),
            )
            connection.execute(
                "DELETE FROM expenses WHERE id = ?", (target[0],)
            )
            self._increment_revision(connection)
        self._sync_csv_if_needed()
        return True

    @_log_method()
    def edit(
        self,
        target_date: str,
        target_type: str,
        target_amount: int,
        target_memo: str,
        new_date: str,
        new_type: str,
        new_amount: int,
        new_memo: str,
    ) -> bool:
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT id, expense_date, expense_type, expense_memo,
                       expense_amount
                FROM expenses ORDER BY expense_date DESC, id DESC
                """
            ).fetchall()
            target = next(
                (
                    row
                    for row in rows
                    if self._matches(
                        row,
                        target_date,
                        target_type,
                        target_amount,
                        target_memo,
                    )
                ),
                None,
            )
            if target is None:
                return False

            old_date = str(target[1])
            edited_date = dt.datetime.fromisoformat(new_date).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )
            if self._normalize_date(old_date) == self._normalize_date(new_date):
                edited_date = old_date
            before = {
                "expense_date": old_date,
                "expense_type": str(target[2]),
                "expense_memo": str(target[3]),
                "expense_amount": int(target[4]),
            }
            after = {
                "expense_date": edited_date,
                "expense_type": new_type,
                "expense_memo": new_memo,
                "expense_amount": new_amount,
            }
            connection.execute(
                """
                UPDATE expenses
                SET expense_date = ?, expense_type = ?, expense_memo = ?,
                    expense_amount = ?, sync_status = 'pending', sync_error = ''
                WHERE id = ?
                """,
                (
                    edited_date,
                    new_type,
                    new_memo,
                    new_amount,
                    target[0],
                ),
            )
            self._enqueue_sync_event(
                connection,
                uuid.uuid4().hex,
                int(target[0]),
                "edit",
                {"before": before, "after": after},
                dt.datetime.now().isoformat(timespec="seconds"),
            )
            self._increment_revision(connection)
        self._sync_csv_if_needed()
        return True

    @staticmethod
    @_log_method(logging.DEBUG)
    def _enqueue_sync_event(
        connection: sqlite3.Connection,
        event_id: str,
        record_id: int,
        operation: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO sync_events (
                event_id, record_id, operation, payload, next_attempt_at,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                record_id,
                operation,
                json.dumps(payload, ensure_ascii=False),
                created_at,
                created_at,
            ),
        )

    @_log_method()
    def claim_next_sync_event(self) -> dict[str, Any] | None:
        now = dt.datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        with self._transaction() as connection:
            event = connection.execute(
                """
                SELECT current.sequence, current.event_id, current.record_id,
                       current.operation, current.payload, current.status,
                       current.attempts, current.next_attempt_at,
                       current.lease_until
                FROM sync_events AS current
                WHERE current.status != 'synced'
                  AND (
                    current.status = 'pending'
                    OR (
                        current.status = 'retrying'
                        AND current.next_attempt_at <= ?
                    )
                    OR (
                        current.status = 'syncing'
                        AND current.lease_until <= ?
                    )
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM sync_events AS prior
                    WHERE prior.record_id = current.record_id
                      AND prior.sequence < current.sequence
                      AND prior.status != 'synced'
                  )
                ORDER BY current.sequence
                LIMIT 1
                """,
                (now_iso, now_iso),
            ).fetchone()
            if event is None:
                return None
            attempts = int(event[6]) + 1
            lease_until = (now + dt.timedelta(minutes=5)).isoformat(
                timespec="seconds"
            )
            connection.execute(
                """
                UPDATE sync_events
                SET status = 'syncing', attempts = ?, lease_until = ?
                WHERE sequence = ?
                """,
                (attempts, lease_until, event[0]),
            )
            if event[2] is not None:
                connection.execute(
                    """
                    UPDATE expenses
                    SET sync_status = 'syncing', sync_error = ''
                    WHERE id = ?
                    """,
                    (event[2],),
                )
            return {
                "sequence": int(event[0]),
                "event_id": str(event[1]),
                "record_id": int(event[2]) if event[2] is not None else None,
                "operation": str(event[3]),
                "payload": json.loads(str(event[4])),
                "attempts": attempts,
            }

    @_log_method()
    def recover_interrupted_sync_events(self) -> int:
        now = dt.datetime.now().isoformat(timespec="seconds")
        with self._transaction() as connection:
            rows = connection.execute(
                """
                SELECT record_id FROM sync_events
                WHERE status = 'syncing' AND lease_until <= ?
                """,
                (now,),
            ).fetchall()
            connection.execute(
                """
                UPDATE sync_events
                SET status = 'pending', lease_until = ''
                WHERE status = 'syncing' AND lease_until <= ?
                """,
                (now,),
            )
            record_ids = [row[0] for row in rows if row[0] is not None]
            connection.executemany(
                "UPDATE expenses SET sync_status = 'pending', sync_error = '' "
                "WHERE id = ?",
                [(record_id,) for record_id in record_ids],
            )
        return len(rows)

    @_log_method()
    def renew_sync_event_lease(self, event_id: str) -> bool:
        now = dt.datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        lease_until = (now + dt.timedelta(minutes=5)).isoformat(
            timespec="seconds"
        )
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE sync_events SET lease_until = ?
                WHERE event_id = ? AND status = 'syncing' AND lease_until > ?
                """,
                (lease_until, event_id, now_iso),
            )
        return cursor.rowcount == 1

    @_log_method()
    def complete_sync_event(self, event_id: str) -> bool:
        with self._transaction() as connection:
            event = connection.execute(
                "SELECT record_id FROM sync_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if event is None:
                return False
            connection.execute(
                """
                UPDATE sync_events
                SET status = 'synced', lease_until = '', last_error = ''
                WHERE event_id = ?
                """,
                (event_id,),
            )
            record_id = event[0]
            if record_id is not None:
                remaining = connection.execute(
                    """
                    SELECT status, last_error FROM sync_events
                    WHERE record_id = ? AND status != 'synced'
                    ORDER BY sequence LIMIT 1
                    """,
                    (record_id,),
                ).fetchone()
                if remaining is None:
                    connection.execute(
                        """
                        UPDATE expenses
                        SET sync_status = 'synced', sync_error = ''
                        WHERE id = ?
                        """,
                        (record_id,),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE expenses
                        SET sync_status = ?, sync_error = ?
                        WHERE id = ?
                        """,
                        (remaining[0], remaining[1], record_id),
                    )
        return True

    @_log_method()
    def retry_sync_event(self, event_id: str, error_code: str) -> None:
        with self._transaction() as connection:
            event = connection.execute(
                "SELECT record_id, attempts FROM sync_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if event is None:
                return
            delay = min(2 ** min(int(event[1]), 10), 3600)
            next_attempt_at = (
                dt.datetime.now() + dt.timedelta(seconds=delay)
            ).isoformat(timespec="seconds")
            connection.execute(
                """
                UPDATE sync_events
                SET status = 'retrying', next_attempt_at = ?, lease_until = '',
                    last_error = ?
                WHERE event_id = ?
                """,
                (next_attempt_at, error_code[:100], event_id),
            )
            if event[0] is not None:
                connection.execute(
                    """
                    UPDATE expenses
                    SET sync_status = 'retrying', sync_error = ?
                    WHERE id = ?
                    """,
                    (error_code[:100], event[0]),
                )

    @_log_method()
    def retry_all_sync_events(self) -> int:
        now = dt.datetime.now().isoformat(timespec="seconds")
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT record_id FROM sync_events WHERE status = 'retrying'"
            ).fetchall()
            connection.execute(
                """
                UPDATE sync_events
                SET status = 'pending', next_attempt_at = ?, lease_until = '',
                    last_error = ''
                WHERE status = 'retrying'
                """,
                (now,),
            )
            record_ids = [row[0] for row in rows if row[0] is not None]
            connection.executemany(
                "UPDATE expenses SET sync_status = 'pending', sync_error = '' "
                "WHERE id = ?",
                [(record_id,) for record_id in record_ids],
            )
        return len(rows)

    @_log_method()
    def get_sync_overview(self, limit: int = 5000) -> dict[str, Any]:
        with self._transaction(immediate=False) as connection:
            counts = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    """
                    SELECT status, COUNT(*) FROM sync_events
                    WHERE status != 'synced' GROUP BY status
                    """
                ).fetchall()
            }
            rows = connection.execute(
                """
                SELECT id, sync_status, sync_error FROM expenses
                ORDER BY expense_date DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return {
            "counts": {
                "pending": counts.get("pending", 0),
                "syncing": counts.get("syncing", 0),
                "retrying": counts.get("retrying", 0),
            },
            "records": {
                str(row[0]): {
                    "status": str(row[1]),
                    "error": str(row[2]),
                }
                for row in rows
            },
        }

    @staticmethod
    @_log_method(logging.DEBUG)
    def _matches(
        row: tuple[object, ...],
        target_date: str,
        target_type: str,
        target_amount: int,
        target_memo: str,
    ) -> bool:
        return (
            ExpenseHistoryStore._normalize_date(str(row[1]))
            == ExpenseHistoryStore._normalize_date(target_date)
            and row[2] == target_type
            and row[3] == target_memo
            and row[4] == target_amount
        )

    @staticmethod
    @_log_method(logging.DEBUG)
    def _normalize_date(value: str) -> str:
        try:
            return dt.datetime.fromisoformat(value).date().isoformat()
        except ValueError:
            return dt.date.fromisoformat(value).isoformat()

    @staticmethod
    @_log_method(logging.DEBUG)
    def _increment_revision(connection: sqlite3.Connection) -> None:
        connection.execute(
            "UPDATE metadata SET value = CAST(value AS INTEGER) + 1 "
            "WHERE key = 'revision'"
        )
