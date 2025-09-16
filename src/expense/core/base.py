import os
import json
import pathlib
import logging
from typing import Any
from platformdirs import user_cache_dir, user_config_dir

HOME: pathlib.Path = pathlib.Path(os.getenv("HOME") or "~")


class Base:
    def __init__(self) -> None:
        self.app_name: str = "expense"
        self.log: logging.Logger = logging.getLogger(self.app_name)
        self.cache_path: pathlib.Path = pathlib.Path(
            user_cache_dir(self.app_name)
        )
        self.config_path: pathlib.Path = pathlib.Path(
            user_config_dir(self.app_name)
        )
        self.cache_path.mkdir(parents=True, exist_ok=True)
        self.config_path.mkdir(parents=True, exist_ok=True)
        self.expense_history: pathlib.Path = (
            self.cache_path / f"{self.app_name}_history.log"
        )
        self.load_config()
        self.setup_logging()

    def load_config(self) -> None:
        """load configuration file"""
        try:
            with open(self.config_path / "config.json", "r") as f:
                self.config: dict[str, Any] = json.load(f)
        except FileNotFoundError:
            self.config = {}
        except Exception:
            self.log.exception(
                f"Failed to load config: {self.config_path / "config.json"}"
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
