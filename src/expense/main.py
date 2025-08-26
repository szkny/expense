#!/usr/bin/env python
"""
家計簿スプレッドシートに自動で書き込みを行うバッチプログラム
"""

import os
import re
import glob
import json
import asyncio
import pathlib
import argparse
import datetime
import subprocess
import pytesseract
from PIL import Image
import logging as log
from typing import Any
from collections import Counter
from expense.gspread_wrapper import GspreadHandler
from platformdirs import user_cache_dir, user_config_dir

TITLE = "家計簿"

APP_NAME = "expense"
CACHE_PATH = pathlib.Path(user_cache_dir(APP_NAME))
CONFIG_PATH = pathlib.Path(user_config_dir(APP_NAME))
CACHE_PATH.mkdir(parents=True, exist_ok=True)
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

HOME = pathlib.Path(os.getenv("HOME") or "~")
EXPENSE_HISTORY = CACHE_PATH / f"{APP_NAME}_history.log"

log.basicConfig(
    level=log.DEBUG,
    handlers=[
        log.StreamHandler(),
        log.FileHandler(CACHE_PATH / f"{APP_NAME}.log"),
    ],
    format="%(asctime)s - [%(levelname)s] %(message)s",
)


def main() -> None:
    """
    main process
    """
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
    parser.add_argument(
        "-j",
        "--json",
        dest="json_data",
        type=str,
        default=None,
        help="expense data in JSON format",
    )
    parser.add_argument(
        "--ocr",
        dest="ocr_image",
        default=False,
        action="store_true",
        help="ocr image of the latest screenshot",
    )
    args = parser.parse_args()
    asyncio.run(expense_main(args))


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
            ocr_data = ocr_main()
            expense_type = ocr_data["expense_type"]
            expense_amount = int(ocr_data["expense_amount"])
            expense_memo = ocr_data.get("expense_memo", "")
            latest_ocr_data = get_ocr_expense()
            if len(latest_ocr_data) and (
                latest_ocr_data.get("screenshot_name") == ocr_data.get("screenshot_name")
            ):
                log.info("OCR data already exists, skipping registration.")
                notify(
                    "OCRデータは登録済のためスキップされました。",
                    f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
                )
                return
            json.dump(
                ocr_data,
                open(CACHE_PATH / "ocr_data.json", "w"),
                ensure_ascii=False,
                indent=2,
            )
        else:
            favorite_expenses = get_favorite_expenses()
            frequent_expenses = get_frequent_expenses(5)
            recent_expenses = get_recent_expenses(5)

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
    if not os.path.exists(EXPENSE_HISTORY):
        return []
    try:
        with open(CONFIG_PATH / "favorites.json", "r") as f:
            data: list[dict] = json.load(f)
    except FileNotFoundError:
        return []
    log.info("end 'get_favorite_expenses' method")
    return data


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
    log.info("end 'get_frequent_expenses' method")
    return frequent_expenses


def get_recent_expenses(num_items: int = 3) -> list[dict]:
    """
    get recent expenses
    """
    log.info("start 'get_recent_expenses' method")
    if not os.path.exists(EXPENSE_HISTORY):
        return []

    def parse_row(row: str) -> dict:
        data = row.strip().split(",")
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
            lines = f.readlines()[::-1]
    except FileNotFoundError:
        return []
    lines = [",".join(line.split(",")[1:]) for line in lines]
    lines = list(dict.fromkeys(lines))  # remove duplicates
    recent_expenses: list[dict] = [parse_row(row) for row in lines[:num_items]]
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


def ocr_main(offset: int = 0, enable_toast: bool = True) -> dict:
    """main method for OCR processing"""
    log.info("start 'ocr_main' method")
    if enable_toast:
        toast("画像解析中..")
    screenshot_name = get_latest_screenshot(offset)
    ocr_text = ocr_image(screenshot_name)
    expense_data = parse_ocr_text(ocr_text)
    expense_amount = expense_data.get("amount", "")
    expense_memo = expense_data.get("memo", "")
    if enable_toast:
        toast("支出項目解析中..")
    res = exec_command(
        [
            "expense_type_classifier",
            "--json",
            f'{{"amount": {expense_amount}, "memo": "{expense_memo}"}}',
        ]
    )
    expense_type = res.get("predicted_type", "")
    log.info("end 'ocr_main' method")
    return {
        "expense_type": expense_type,
        "expense_amount": expense_amount,
        "expense_memo": expense_memo,
        "screenshot_name": os.path.basename(screenshot_name),
    }


def get_latest_screenshot(offset: int = 0) -> str:
    """
    get the latest screenshot file name
    """
    log.info("start 'get_latest_screenshot' method")
    screenshot_list = glob.glob(
        (HOME / "storage/dcim/Screenshots/Screenshot_*Pay.jpg").as_posix()
    )
    if len(screenshot_list) == 0:
        raise FileNotFoundError("スクリーンショットが見つかりませんでした。")
    screenshot_name = sorted(screenshot_list)[-1 - offset]
    log.debug(f"Latest screenshot: {screenshot_name}")
    log.info("end 'get_latest_screenshot' method")
    return screenshot_name


def normalize_capture_text(text: str) -> str:
    """
    normalize capture text
    """
    log.info("start 'normalized_text' method")
    normalized_text = re.sub(
        r"[①-⑳]", lambda m: str(ord(m.group()) - ord("①") + 1), text
    )
    normalized_text = re.sub(
        r"[０-９]", lambda m: str(int(m.group(0))), normalized_text
    )
    normalized_text = re.sub(
        r"(?<=[^A-Za-z]) (?=[^A-Za-z])",
        "",
        normalized_text,
    )
    log.info("end 'normalized_text' method")
    return normalized_text


def ocr_image(screenshot_name: str) -> str:
    """
    perform OCR on the image
    """
    log.info("start 'ocr_image' method")
    img = Image.open(screenshot_name)

    # Define OCR regions for different payment apps
    try:
        with open(CONFIG_PATH / "ocr_regions.json", "r") as f:
            ocr_regions: dict[str, list] = json.load(f)
    except FileNotFoundError:
        ocr_regions = {}

    # Determine which regions to process based on screenshot name
    regions_to_process = {}
    for app_name, regions in ocr_regions.items():
        if app_name in screenshot_name:
            regions_to_process = {app_name: regions}
            break

    # Process regions if found, otherwise process entire image
    if regions_to_process:
        results = []
        for app_name, regions in regions_to_process.items():
            log.debug(f"Processing OCR for {app_name}")
            for i, region in enumerate(regions):
                cropped = img.crop(region)
                text = str(pytesseract.image_to_string(cropped, lang="jpn"))
                log.debug(f"\t[{i}] region: {region}, ocr text: {text}")
                results.append(text)
        text = "\n".join(results)
    else:
        text = str(pytesseract.image_to_string(img, lang="jpn"))

    text = normalize_capture_text(text)
    log.debug(f"OCR text:\n{text}")
    log.info("end 'ocr_image' method")
    return text


def parse_ocr_text(ocr_text: str) -> dict:
    """
    Extract expense data (amount and memo) from OCR text
    """
    log.info("start 'parse_ocr_text' method")

    date_pattern = re.compile(
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(日)?|\d{1,2}[:時]\d{1,2}(分)?)"
    )
    text_rows = ocr_text.split("\n")

    expense_data = {
        "amount": extract_amount(text_rows, date_pattern),
        "memo": extract_memo(text_rows, date_pattern),
    }

    if expense_data["amount"]:
        log.debug(f"Extracted Expense Amount: {expense_data['amount']}")
    if expense_data["memo"]:
        log.debug(f"Extracted Expense Memo: {expense_data['memo']}")

    log.info("end 'parse_ocr_text' method")
    return expense_data


def extract_amount(
    text_rows: list[str], date_pattern: re.Pattern
) -> int | None:
    """
    Extract amount from text rows
    """
    log.info("start 'extract_amount' method")
    amount_pattern = re.compile(r"([1-9]\d{0,2}[,\.]*\d{0,3})")
    amounts = []
    for i, row in enumerate(text_rows):
        row = row.replace(" ", "")

        # Skip first two rows and empty rows
        if i < 2 or not row.strip():
            continue

        # Skip rows containing date patterns
        if date_pattern.search(row):
            continue

        # Extract amounts
        if match := amount_pattern.search(row):
            log.debug(f"Processing row {i} for amount: {row}")
            amounts.append(int(re.sub("[,.]", "", match.group(1))))

    if not amounts:
        log.debug("金額の抽出に失敗しました。")
        toast("金額の抽出に失敗しました。")
        return None

    # Filter out amounts less than or equal to 30
    amounts = list(filter(lambda x: x > 30, amounts))
    log.info("end 'extract_amount' method")
    return amounts[0]


def extract_memo(text_rows: list[str], date_pattern: re.Pattern) -> str | None:
    """
    Extract memo from text rows
    """
    log.info("start 'extract_memo' method")
    memo_pattern = re.compile(r"([^(.*お支払い完了.*)]{3,30})")
    memos = []
    for i, row in enumerate(text_rows):
        # Skip empty rows
        if not row.strip():
            continue

        # Skip rows containing date patterns
        if date_pattern.search(row):
            break

        pattern = r"[^A-Za-z]"  # non-alphabets
        pattern_alpha = r"[A-Za-z]"  # alphabets
        row = re.sub(f"(?<={pattern_alpha}) (?={pattern})", "", row)
        row = re.sub(f"(?<={pattern}) (?={pattern_alpha})", "", row)

        if match := memo_pattern.search(row.strip()):
            log.debug(f"Processing row {i} for memo: {row}")
            memos.append(match.group(1))

    if not memos:
        log.debug("メモの抽出に失敗しました。")
        toast("メモの抽出に失敗しました。")
        return None

    memo = memos[0]
    # Combine first two memos
    if len(memos) > 1:
        if len(memos[0] + memos[1]) <= 30 and not (
            memos[0] in memos[1] or memos[1] in memos[0]
        ):
            memo += " " + memos[1]
        elif len(memos[0]) < len(memos[1]):
            memo = memos[1]
    log.info("end 'extract_memo' method")
    return memo


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
    item_list: list[dict[str, Any]] = [],
) -> str:
    """
    select expense type
    """
    log.info("start 'select_expense_type' method")
    items_list_str = "食費,交通費,遊興費,雑費,書籍費,医療費,家賃,光熱費,通信費,養育費,特別経費,給与,雑所得"
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
    data = exec_command(
        [
            "termux-dialog",
            "sheet",
            "-t",
            TITLE,
            "-v",
            items_list_str,
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


def toast(content: str, timeout: int = 5) -> None:
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
    main()
