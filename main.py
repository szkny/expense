#!/usr/bin/env python
import json
from json import JSONDecodeError
import subprocess
from typing import Any

TITLE = "家計簿"


def exec_command(command: list) -> Any:
    """
    method for execution util
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
            f"Amount for {expense_type}",
            "-n",
        ]
    )
    expense_amount = int(data["text"])
    print("expense_amount: ", expense_amount)
    return expense_amount


def main() -> None:
    """ """
    expense_type = select_expense_type()
    expense_amount = enter_expense_amount(expense_type)
    exec_command(
        [
            "termux-dialog",
            "confirm",
            "-t",
            TITLE,
            "-i",
            f"expense_type: {expense_type}, expense_amount: {expense_amount}",
        ]
    )


if __name__ == "__main__":
    main()
