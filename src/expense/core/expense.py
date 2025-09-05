import os
import re
import json
import asyncio
import pathlib
import argparse
import datetime
import pandas as pd
import logging as log
from collections import Counter
from platformdirs import user_cache_dir, user_config_dir

from .ocr import ocr_main, get_latest_screenshot
from .termux_api import (
    toast,
    notify,
    select_expense_type,
    enter_expense_amount,
    enter_expense_memo,
)
from .gspread_wrapper import GspreadHandler

APP_NAME = "expense"
CACHE_PATH = pathlib.Path(user_cache_dir(APP_NAME))
CONFIG_PATH = pathlib.Path(user_config_dir(APP_NAME))
CACHE_PATH.mkdir(parents=True, exist_ok=True)
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

EXPENSE_HISTORY = CACHE_PATH / f"{APP_NAME}_history.log"

log.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    handlers=[
        log.StreamHandler(),
        log.FileHandler(CACHE_PATH / f"{APP_NAME}.log"),
    ],
    format="%(asctime)s - [%(levelname)s] %(message)s",
)


async def expense_main(args: argparse.Namespace) -> None:
    """
    main process for expense registration
    """
    log.info("start 'expense_main' method")
    try:
        loop = asyncio.get_running_loop()
        current_fiscal_year = get_fiscal_year()
        bookname = f"CF ({current_fiscal_year}年度)"
        if args.check_todays_expenses:
            loop.run_in_executor(None, lambda: toast("データ取得中.."))
            handler = GspreadHandler(bookname)
            todays_expenses = handler.get_todays_expenses()
            t = datetime.datetime.today()
            today_str = t.date().isoformat()
            notify(
                "家計簿の取得が完了しました。",
                f"🗓️{today_str}\n{todays_expenses}",
            )
            return
        elif args.json_data:
            data = json.loads(args.json_data)
            expense_type = data["type"]
            expense_amount = int(data["amount"])
            expense_memo = data.get("memo", "")
        elif args.ocr_image:
            recent_screenshot = get_latest_screenshot()
            latest_ocr_data = get_ocr_expense()
            if len(latest_ocr_data) and (
                latest_ocr_data.get("screenshot_name")
                == os.path.basename(recent_screenshot)
            ):
                log.info("OCR data already exists, skipping registration.")
                expense_type = latest_ocr_data["expense_type"]
                expense_amount = int(latest_ocr_data["expense_amount"])
                expense_memo = latest_ocr_data.get("expense_memo", "")
                notify(
                    "OCRデータは登録済のためスキップされました。",
                    f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
                )
                return
            ocr_data = ocr_main()
            expense_type = ocr_data["expense_type"]
            expense_amount = int(ocr_data["expense_amount"])
            expense_memo = ocr_data.get("expense_memo", "")
            json.dump(
                ocr_data,
                open(CACHE_PATH / "ocr_data.json", "w"),
                ensure_ascii=False,
                indent=2,
            )
        else:
            favorite_expenses = get_favorite_expenses()
            frequent_expenses = get_frequent_expenses(8)
            recent_expenses = get_recent_expenses(8)

            (
                favorite_expenses,
                frequent_expenses,
                recent_expenses,
            ) = filter_duplicates(
                [
                    favorite_expenses,
                    frequent_expenses,
                    recent_expenses,
                ]
            )

            expense_type = select_expense_type(
                item_list=[
                    {"icon": "⭐", "items": favorite_expenses},
                    {"icon": "🔥", "items": frequent_expenses},
                    {"icon": "🕒️", "items": recent_expenses},
                ],
            )
            if any([emoji in expense_type for emoji in "⭐🔥🕒️"]):
                data = re.sub("(⭐|🔥|🕒️) ", "", expense_type).split("/")
                if len(data) == 3:
                    expense_type = data[0]
                    expense_memo = data[1]
                    expense_amount = int(re.sub(r"[^\d]", "", data[2]))
                elif len(data) == 2:
                    expense_type = data[0]
                    expense_memo = ""
                    expense_amount = int(re.sub(r"[^\d]", "", data[1]))
            else:
                expense_amount = enter_expense_amount(expense_type)
                expense_memo = enter_expense_memo(
                    f"{expense_type}(¥{expense_amount:,})"
                )
        loop.run_in_executor(None, lambda: toast("登録中.."))
        handler = GspreadHandler(bookname)
        handler.register_expense(expense_type, expense_amount, expense_memo)
        store_expense(expense_type, expense_memo, expense_amount)
        notify(
            "家計簿への登録が完了しました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
        )
    except Exception as e:
        log.exception("処理に失敗しました。")
        notify("🚫処理に失敗しました。", str(e))
    finally:
        log.info("end 'expense_main' method")


def get_favorite_expenses() -> list[dict]:
    """
    get favorite expenses
    """
    log.info("start 'get_favorite_expenses' method")
    try:
        with open(CONFIG_PATH / "favorites.json", "r") as f:
            favorite_expenses: list[dict] = json.load(f)
    except FileNotFoundError:
        return []
    # log.debug(
    #     f"Favorite expenses: {json.dumps(favorite_expenses, indent=2, ensure_ascii=False)}"
    # )
    log.info("end 'get_favorite_expenses' method")
    return favorite_expenses


def get_frequent_expenses(num_items: int = 3) -> list[dict]:
    """
    get frequent expenses
    """
    log.info("start 'get_frequent_expenses' method")
    if not os.path.exists(EXPENSE_HISTORY):
        return []

    def parse_row(row: tuple[str, int]) -> dict:
        data = row[0].strip().split(",")
        if len(data) == 2:
            return {
                "expense_type": data[0],
                "expense_memo": "",
                "expense_amount": int(data[1]),
            }
        elif len(data) == 3:
            return {
                "expense_type": data[0],
                "expense_memo": data[1],
                "expense_amount": int(data[2]),
            }
        else:
            return {}

    try:
        with open(EXPENSE_HISTORY, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    lines = [",".join(line.split(",")[1:]) for line in lines]
    aggregated_lines: list[tuple] = [
        item for item in Counter(lines).most_common() if item[1] >= 2
    ]
    frequent_expenses: list[dict] = [
        parse_row(row) for row in aggregated_lines[:num_items]
    ]
    # log.debug(
    #     f"Frequent expenses: {json.dumps(frequent_expenses, indent=2, ensure_ascii=False)}"
    # )
    log.info("end 'get_frequent_expenses' method")
    return frequent_expenses


def get_recent_expenses(
    num_items: int = 3,
    drop_duplicates: bool = True,
    with_date: bool = False,
) -> list[dict]:
    """
    get recent expenses
    """
    log.info("start 'get_recent_expenses' method")
    try:
        df = pd.read_csv(EXPENSE_HISTORY, header=None)
    except FileNotFoundError:
        return []
    df.columns = pd.Index(
        ["date", "expense_type", "expense_memo", "expense_amount"]
    )
    df["expense_memo"] = df["expense_memo"].fillna("")
    if not with_date:
        df = df.drop(columns=["date"])
    else:
        df["date"] = (
            pd.to_datetime(df["date"])
            .dt.strftime("%Y-%m-%d(%a)")
            .map(
                lambda x: x.replace("Mon", "月")
                .replace("Tue", "火")
                .replace("Wed", "水")
                .replace("Thu", "木")
                .replace("Fri", "金")
                .replace("Sat", "土")
                .replace("Sun", "日")
            )
        )
    if drop_duplicates:
        df = df.drop_duplicates(
            subset=["expense_type", "expense_memo", "expense_amount"]
        )
    recent_expenses = df.iloc[::-1].iloc[:num_items].to_dict(orient="records")
    # log.debug(
    #     f"Recent expenses: {json.dumps(recent_expenses, indent=2, ensure_ascii=False)}"
    # )
    log.info("end 'get_recent_expenses' method")
    return recent_expenses


def get_ocr_expense() -> dict:
    """
    get OCR expenses
    """
    log.info("start 'get_ocr_expenses' method")
    try:
        with open(CACHE_PATH / "ocr_data.json", "r") as f:
            data: dict = json.load(f)
    except FileNotFoundError:
        log.debug("OCR data not found.")
        return {}
    ocr_expense = {
        "expense_type": data.get("expense_type", ""),
        "expense_memo": data.get("expense_memo", ""),
        "expense_amount": int(data.get("expense_amount", 0)),
        "screenshot_name": data.get("screenshot_name", ""),
    }
    log.debug(
        f"Latest OCR expense: {json.dumps(ocr_expense, indent=2, ensure_ascii=False)}"
    )
    log.info("end 'get_ocr_expenses' method")
    return ocr_expense


def filter_duplicates(
    expenses_list: list[list[dict]],
) -> list[list[dict]]:
    """
    filter out duplicate expenses across different expense categories
    """
    log.info("start 'filter_duplicates' method")

    def dict_to_key(d: dict) -> str:
        return json.dumps(d, sort_keys=True)

    def filter_list(expenses: list[dict], seen: set) -> list[dict]:
        filtered = []
        for expense in expenses:
            key = dict_to_key(expense)
            if key not in seen:
                seen.add(key)
                filtered.append(expense)
        return filtered

    # Add first expenses keys to seen set
    seen_keys: set[str] = set()
    seen_keys.update(dict_to_key(d) for d in expenses_list[0])

    # Filter remaining lists in priority order
    result = [expenses_list[0]]
    for expenses in expenses_list[1:]:
        filtered_expenses = filter_list(expenses, seen_keys)
        result.append(filtered_expenses)

    log.info("end 'filter_duplicates' method")
    return result


def store_expense(
    expense_type: str, expense_memo: str, expense_amount: int
) -> None:
    """
    store expense
    """
    log.info("start 'store_expense' method")
    with open(EXPENSE_HISTORY, "a") as f:
        f.write(
            f"{datetime.datetime.today().isoformat()},{expense_type},{expense_memo},{expense_amount}\n"
        )
    log.info("end 'store_expense' method")
    return


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
