import csv
import datetime as dt
import logging
import os
import pathlib
import sqlite3
import tempfile
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Iterator, ParamSpec, TypeVar


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
                    expense_amount INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
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
    def add(
        self,
        expense_type: str,
        expense_memo: str,
        expense_amount: int,
        expense_date: str,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO expenses (
                    expense_date,
                    expense_type,
                    expense_memo,
                    expense_amount
                ) VALUES (?, ?, ?, ?)
                """,
                (expense_date, expense_type, expense_memo, expense_amount),
            )
            self._increment_revision(connection)
        self._sync_csv_if_needed()

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
            connection.execute(
                """
                UPDATE expenses
                SET expense_date = ?, expense_type = ?, expense_memo = ?,
                    expense_amount = ?
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
            self._increment_revision(connection)
        self._sync_csv_if_needed()
        return True

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
            and (not target_type or row[2] == target_type)
            and (not target_memo or row[3] == target_memo)
            and (not target_amount or row[4] == target_amount)
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
