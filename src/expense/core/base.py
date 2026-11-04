import os
import json
import shutil
import pathlib
import logging
from contextlib import closing
from typing import Any
from importlib import resources
from platformdirs import user_data_dir, user_cache_dir, user_config_dir

HOME: pathlib.Path = pathlib.Path(os.getenv("HOME") or "~")
log: logging.Logger = logging.getLogger("expense")


def check_sqlite3() -> None:
    """Ensure Python has a working SQLite module."""
    log.info("start 'check_sqlite3' function")
    try:
        try:
            import sqlite3
        except ImportError as exc:
            raise RuntimeError(
                "Pythonのsqlite3モジュールが利用できません。"
                "SQLite対応のPythonを使用してください。"
            ) from exc

        try:
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.execute("SELECT sqlite_version()")
        except sqlite3.Error as exc:
            raise RuntimeError("SQLiteを初期化できません。") from exc
    finally:
        log.info("end 'check_sqlite3' function")


class Base:
    def __init__(self) -> None:
        check_sqlite3()
        self.app_name: str = "expense"
        self.log: logging.Logger = logging.getLogger(self.app_name)
        self.data_path: pathlib.Path = pathlib.Path(
            user_data_dir(self.app_name)
        )
        self.cache_path: pathlib.Path = pathlib.Path(
            user_cache_dir(self.app_name)
        )
        self.config_path: pathlib.Path = pathlib.Path(
            user_config_dir(self.app_name)
        )
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.config_path.mkdir(parents=True, exist_ok=True)
        self.expense_history: pathlib.Path = (
            self.data_path / f"{self.app_name}_history.log"
        )
        self.generate_config()
        self.load_config()
        self.setup_logging()

    def generate_config(self) -> None:
        """generate configuration file if not exists"""
        config_file = self.config_path / "config.json"
        if not config_file.exists():
            self.log.info(
                f"'{config_file}' not found. Generating default config."
            )
            try:
                with resources.path(
                    "expense.config", "config.json"
                ) as default_config:
                    shutil.copy(default_config, config_file)
                    self.log.info(f"Generated default config at: {config_file}")
            except Exception:
                self.log.exception("Failed to generate default config file.")

    def load_config(self) -> None:
        """load configuration file"""
        try:
            with open(self.config_path / "config.json", "r") as f:
                self.config: dict[str, Any] = json.load(f)
        except FileNotFoundError:
            self.config = {}
        except Exception:
            self.log.exception(
                f"Failed to load config: {self.config_path / 'config.json'}"
            )

    def setup_logging(self) -> None:
        """setup log config"""
        if not self.log.handlers:
            log_level: str = self.config.get("log_level", "INFO")
            self.log.setLevel(log_level)
            stream_handler = logging.StreamHandler()
            file_handler = logging.FileHandler(
                self.cache_path / f"{self.app_name}.log"
            )
            formatter = logging.Formatter(
                "%(asctime)s - [%(levelname)s] %(message)s"
            )
            stream_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)
            self.log.addHandler(stream_handler)
            self.log.addHandler(file_handler)
