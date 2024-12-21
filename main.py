#!/usr/bin/env python
"""
家計簿スプレッドシートに自動で書き込みを行うバッチプログラム
"""
import os
import json
import asyncio
import argparse
import datetime
import subprocess
import logging as log
from typing import Any

from gspread_wrapper import GspreadHandler

TITLE = "家計簿"

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


async def main(args: argparse.Namespace) -> None:
    """
    main process
    """
    log.info("start 'main' method")
    try:
        loop = asyncio.get_running_loop()
        current_fiscal_year = get_fiscal_year()
        bookname = f"CF ({current_fiscal_year}年度)"
        if args.check_todays_expenses:
            await loop.run_in_executor(None, lambda: toast("データ取得中.."))
            handler = GspreadHandler(bookname)
            todays_expenses = handler.get_todays_expenses()
            t = datetime.datetime.today()
            today_str = t.date().isoformat()
            notify(
                "家計簿の取得が完了しました。",
                f"🗓️{today_str}\n{todays_expenses}",
            )
        else:
            expense_type = select_expense_type()
            expense_amount = enter_expense_amount(expense_type)
            expense_memo = enter_expense_memo(expense_type)
            res = confirmation(
                f"以下の内容で登録しますか？\n\t{expense_type}{':'+expense_memo if expense_memo else ''}, {expense_amount}円"
            )
            if res:
                await loop.run_in_executor(None, lambda: toast("登録中.."))
                handler = GspreadHandler(bookname)
                handler.register_expense(
                    expense_type, expense_amount, expense_memo
                )
                notify(
                    "家計簿への登録が完了しました。",
                    f"{expense_type}{':'+expense_memo if expense_memo else ''}, {expense_amount}円",
                )
    except Exception as e:
        log.exception("家計簿の登録処理に失敗しました。")
        notify("🚫家計簿の登録処理に失敗しました。", str(e))
    finally:
        log.info("end 'main' method")


def get_fiscal_year() -> int:
    """
    get fiscal year
    """
    log.info("start 'get_fiscal_year' method")
    today = datetime.date.today()
    year = today.year
    if today.month < 4:
        year -= 1
    log.info("end 'get_fiscal_year' method")
    return year


def exec_command(command: list, timeout: int = 60) -> Any:
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
    )
    json_str = res.stdout.decode("utf-8")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise e
    if data["text"] == "":
        raise Exception("入力がキャンセルされました。")
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
            "食費,交通費,遊興費,雑費,書籍費,医療費,家賃,光熱費,通信費,特別経費,給与,雑所得",
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


def confirmation(content: str) -> bool:
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
            content,
        ]
    )
    choice = str(data["text"])
    log.debug("choice: " + choice)
    log.info("end 'confirmation' method")
    return choice == "yes"


def toast(content: str, timeout: int = 30) -> None:
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


def notify(title: str, content: str, timeout: int = 30) -> None:
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="家計簿スプレッドシートに自動で書き込みを行うバッチプログラム"
    )
    parser.add_argument(
        "-c",
        "--check",
        dest="check_todays_expenses",
        default=False,
        action="store_true",
        help="check today's expenses",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
