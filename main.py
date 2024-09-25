#!/usr/bin/env python
"""
家計簿スプレッドシートに自動で書き込みを行うバッチプログラム
"""
import json
from json import JSONDecodeError
import subprocess
from typing import Any

from gspread_wrapper import GspreadHandler

TITLE = "家計簿"
BOOKNAME = "CF (2024年度)"


def exec_command(command: list) -> Any:
    """
    utility method for shell command execution
    """
    res = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    json_str = res.stdout.decode("utf-8")

    try:
        data = json.loads(json_str)
    except JSONDecodeError as e:
        raise e
    return data


def select_expense_type() -> str:
    """
    select expense type
    """
    data = exec_command(
        [
            "termux-dialog",
            "sheet",
            "-t",
            TITLE,
            "-v",
            "食費,交通費,遊興費,雑費,書籍費,医療費",
        ]
    )
    expense_type = str(data["text"])
    print("expense_type: ", expense_type)
    return expense_type


def enter_expense_amount(expense_type: str) -> int:
    """
    enter expense amount
    """
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
    print("expense_amount: ", expense_amount)
    return expense_amount


def enter_expense_memo(expense_type: str) -> str:
    """
    enter expense memo
    """
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
    print(
        "expense_memo: ",
    )
    return expense_memo


def confirmation(
    expense_type: str, expense_amount: int, expense_memo: str
) -> bool:
    """
    confirmation
    """
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
    print("choice: ", choice)
    return choice == "yes"


def main() -> None:
    """
    main process
    """
    expense_type = select_expense_type()
    expense_amount = enter_expense_amount(expense_type)
    expense_memo = enter_expense_memo(expense_type)
    confirmation(expense_type, expense_amount, expense_memo)
    handler = GspreadHandler(BOOKNAME)
    handler.register_expense(expense_type, expense_amount, expense_memo)


if __name__ == "__main__":
    main()
