#!/usr/bin/env python
"""
家計簿スプレッドシートに自動で書き込みを行うバッチプログラム
"""
import os
import json
import logging as log
import subprocess
from typing import Any

from gspread_wrapper import GspreadHandler

HOME = os.getenv("HOME") or "~"
os.makedirs(HOME + "/tmp/expense", exist_ok=True)

log.basicConfig(
    level=log.DEBUG,
    handlers=[
        log.StreamHandler(),
        log.FileHandler(HOME + "/tmp/expense/expense.log"),
    ],
    format="%(asctime)s - [%(levelname)s] %(message)s",
)

TITLE = "家計簿"
BOOKNAME = "CF (2024年度)"


def exec_command(command: list) -> Any:
    """
    utility method for shell command execution
    """
    # funcname = inspect.currentframe()
    log.info("start 'exec_command' method")
    log.debug(f"execute command: {command}")
    res = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    json_str = res.stdout.decode("utf-8")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise e
    log.info("end 'exec_command' method")
    return data


def select_expense_type() -> str:
    """
    select expense type
    """
    log.info("start 'select_expense_type' method")
    data = exec_command(
        [
            "termux-dialog",
            "sheet",
            "-t",
            TITLE,
            "-v",
            "食費,交通費,遊興費,雑費,書籍費,医療費,家賃,光熱費,通信費,特別経費",
        ]
    )
    expense_type = str(data["text"])
    log.debug(f"expense_type: {expense_type}")
    log.info("end 'select_expense_type' method")
    return expense_type


def enter_expense_amount(expense_type: str) -> int:
    """
    enter expense amount
    """
    log.info("start 'enter_expense_amount' method")
    data = exec_command(
        [
            "termux-dialog",
            "text",
            "-t",
            TITLE,
            "-i",
            f"{expense_type}の金額を入力",
            "-n",
        ]
    )
    expense_amount = int(data["text"])
    log.debug(f"expense_amount: {expense_amount}")
    log.info("end 'enter_expense_amount' method")
    return expense_amount


def enter_expense_memo(expense_type: str) -> str:
    """
    enter expense memo
    """
    log.info("start 'enter_expense_memo' method")
    data = exec_command(
        [
            "termux-dialog",
            "text",
            "-t",
            TITLE,
            "-i",
            f"{expense_type}のメモを入力",
        ]
    )
    expense_memo = str(data["text"])
    log.debug(f"expense_memo: {expense_memo}")
    log.info("end 'enter_expense_memo' method")
    return expense_memo


def confirmation(
    expense_type: str, expense_amount: int, expense_memo: str
) -> bool:
    """
    confirmation
    """
    log.info("start 'confirmation' method")
    data = exec_command(
        [
            "termux-dialog",
            "confirm",
            "-t",
            TITLE,
            "-i",
            f"以下の内容で登録しますか？\n\t{expense_type}{':'+expense_memo if expense_memo else ''}, {expense_amount}円",
        ]
    )
    choice = str(data["text"])
    log.debug("choice: " + choice)
    log.info("end 'confirmation' method")
    return choice == "yes"


def main() -> None:
    """
    main process
    """
    try:
        log.info("start 'main' method")
        expense_type = select_expense_type()
        expense_amount = enter_expense_amount(expense_type)
        expense_memo = enter_expense_memo(expense_type)
        res = confirmation(expense_type, expense_amount, expense_memo)
        if res:
            handler = GspreadHandler(BOOKNAME)
            handler.register_expense(expense_type, expense_amount, expense_memo)
        notify_command = [
            "termux-notification",
            "--title",
            "家計簿への登録が完了しました。",
            "--content",
            f"{expense_type}{':'+expense_memo if expense_memo else ''}, {expense_amount}円",
        ]
        log.debug(f"execute command: {notify_command}")
        subprocess.run(
            notify_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except Exception:
        log.exception("error occurred")
    finally:
        log.info("end 'main' method")


if __name__ == "__main__":
    main()
