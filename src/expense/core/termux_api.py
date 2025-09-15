import json
import logging
import subprocess
from typing import Any

from .base import Base

log: logging.Logger = logging.getLogger("expense")


class TermuxAPI(Base):

    def __init__(self):
        super().__init__()
        expense_config: dict[str, Any] = self.config.get("expense", {})
        expense_types_all: dict[str, list] = expense_config.get(
            "expense_types", {}
        )
        income_types: list[str] = expense_types_all.get("income", [])
        fixed_types: list[str] = expense_types_all.get("fixed", [])
        variable_types: list[str] = expense_types_all.get("variable", [])
        self.expense_types: list[str] = (
            variable_types + fixed_types + income_types
        )

    def exec_command(
        self, command: list, timeout: int = 60, env: dict = {}
    ) -> Any:
        """
        utility method for shell command execution
        """
        # funcname = inspect.currentframe()
        log.info("start 'exec_command' method")
        log.debug(f"execute command: {command}")
        res = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env if env else None,
        )
        json_str = res.stdout.decode("utf-8")
        log.debug(f"command output: {json_str}")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise e
        if data.get("code", 0) == -2:
            log.debug(f"data: {data}")
            raise Exception("入力がキャンセルされました。")
        elif ("-n" in command) and data.get("text", "yes") in (
            "",
            "no",
        ):
            log.debug(f"data: {data}")
            raise Exception("入力がキャンセルされました。")
        log.info("end 'exec_command' method")
        return data

    def select_expense_type(
        self,
        item_list: list[dict[str, Any]] = [],
    ) -> str:
        """
        select expense type
        """
        log.info("start 'select_expense_type' method")
        items_list_str = ",".join(self.expense_types)
        additional_items = ""
        for item_data in item_list:
            items: list[dict] = item_data.get("items", [])
            icon: str = item_data.get("icon", "")
            if len(items):
                items_str = ",".join(
                    [
                        f'{icon} {i["expense_type"]}/{i["expense_memo"]}/¥{i["expense_amount"]}'
                        for i in items
                    ]
                )
                if len(additional_items):
                    items_str = "," + items_str
                additional_items += items_str
        if additional_items:
            additional_items = additional_items.replace("//", "/")
            items_list_str = additional_items + "," + items_list_str
        data = self.exec_command(
            [
                "termux-dialog",
                "sheet",
                "-t",
                self.app_name,
                "-v",
                items_list_str,
            ]
        )
        expense_type = str(data["text"])
        log.debug(f"expense_type: {expense_type}")
        log.info("end 'select_expense_type' method")
        return expense_type

    def enter_expense_amount(self, expense_type: str) -> int:
        """
        enter expense amount
        """
        log.info("start 'enter_expense_amount' method")
        data = self.exec_command(
            [
                "termux-dialog",
                "text",
                "-t",
                self.app_name,
                "-i",
                f"{expense_type}の金額を入力",
                "-n",
            ]
        )
        expense_amount = int(data["text"])
        log.debug(f"expense_amount: {expense_amount}")
        log.info("end 'enter_expense_amount' method")
        return expense_amount

    def enter_expense_memo(self, expense_type: str) -> str:
        """
        enter expense memo
        """
        log.info("start 'enter_expense_memo' method")
        data = self.exec_command(
            [
                "termux-dialog",
                "text",
                "-t",
                self.app_name,
                "-i",
                f"{expense_type}のメモを入力",
            ]
        )
        expense_memo = str(data["text"])
        log.debug(f"expense_memo: {expense_memo}")
        log.info("end 'enter_expense_memo' method")
        return expense_memo

    def confirmation(self, content: str) -> bool:
        """
        confirmation
        """
        log.info("start 'confirmation' method")
        data = self.exec_command(
            [
                "termux-dialog",
                "confirm",
                "-t",
                self.app_name,
                "-i",
                content,
            ]
        )
        choice = str(data["text"])
        log.debug("choice: " + choice)
        log.info("end 'confirmation' method")
        return choice == "yes"

    def toast(self, content: str, timeout: int = 5) -> None:
        """
        toast popup message
        """
        log.info("start 'toast' method")
        notify_command = [
            "termux-toast",
            "-b",
            "black",
            "-g",
            "top",
            content,
        ]
        log.debug(f"execute command: {notify_command}")
        subprocess.run(
            notify_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        log.info("end 'toast' method")

    def notify(self, title: str, content: str, timeout: int = 30) -> None:
        """
        notification
        """
        log.info("start 'notify' method")
        notify_command = [
            "termux-notification",
            "--title",
            title,
            "--content",
            content,
        ]
        log.debug(f"execute command: {notify_command}")
        subprocess.run(
            notify_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        log.info("end 'notify' method")
