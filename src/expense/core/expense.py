import os
import re
import json
import asyncio
import logging
import argparse
import datetime
import pandas as pd
from typing import Any
from collections import Counter

from .base import Base
from .termux_api import TermuxAPI
from .ocr import Ocr, get_latest_screenshot
from .gspread_wrapper import GspreadHandler

logging.getLogger("asyncio").setLevel(logging.WARNING)
log: logging.Logger = logging.getLogger("expense")


def get_fiscal_year() -> int:
    """
    get fiscal year
    """
    log.info("start 'get_fiscal_year' function")
    today = datetime.date.today()
    year = today.year
    if today.month < 4:
        year -= 1
    log.info("end 'get_fiscal_year' function")
    return year


class Expense(Base):
    def __init__(self):
        super().__init__()
        self.termux_api: TermuxAPI = TermuxAPI()

    async def expense_main(self, args: argparse.Namespace) -> None:
        """
        main process for expense registration
        """
        log.info("start 'expense_main' method")
        try:
            loop = asyncio.get_running_loop()
            current_fiscal_year = get_fiscal_year()
            bookname = f"CF ({current_fiscal_year}年度)"
            if args.check_todays_expenses:
                loop.run_in_executor(
                    None, lambda: self.termux_api.toast("データ取得中..")
                )
                handler = GspreadHandler(bookname)
                todays_expenses = handler.get_todays_expenses()
                t = datetime.datetime.today()
                today_str = t.date().isoformat()
                self.termux_api.notify(
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
                latest_ocr_data = self.get_ocr_expense()
                if len(latest_ocr_data) and (
                    latest_ocr_data.get("screenshot_name")
                    == os.path.basename(recent_screenshot)
                ):
                    log.info("OCR data already exists, skipping registration.")
                    expense_type = latest_ocr_data["expense_type"]
                    expense_amount = int(latest_ocr_data["expense_amount"])
                    expense_memo = latest_ocr_data.get("expense_memo", "")
                    self.termux_api.notify(
                        "OCRデータは登録済のためスキップされました。",
                        f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
                    )
                    return
                ocr = Ocr()
                ocr_data = ocr.main()
                expense_type = ocr_data["expense_type"]
                expense_amount = int(ocr_data["expense_amount"])
                expense_memo = ocr_data.get("expense_memo", "")
                json.dump(
                    ocr_data,
                    open(self.cache_path / "ocr_data.json", "w"),
                    ensure_ascii=False,
                    indent=2,
                )
            else:
                favorite_expenses = self.get_favorite_expenses()
                frequent_expenses = self.get_frequent_expenses(8)
                recent_expenses = self.get_recent_expenses(8)

                (
                    favorite_expenses,
                    frequent_expenses,
                    recent_expenses,
                ) = self.filter_duplicates(
                    [
                        favorite_expenses,
                        frequent_expenses,
                        recent_expenses,
                    ]
                )

                expense_type = self.termux_api.select_expense_type(
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
                    expense_amount = self.termux_api.enter_expense_amount(
                        expense_type
                    )
                    expense_memo = self.termux_api.enter_expense_memo(
                        f"{expense_type}(¥{expense_amount:,})"
                    )
            loop.run_in_executor(
                None, lambda: self.termux_api.toast("登録中..")
            )
            handler = GspreadHandler(bookname)
            handler.register_expense(expense_type, expense_amount, expense_memo)
            self.store_expense(expense_type, expense_memo, expense_amount)
            self.termux_api.notify(
                "家計簿への登録が完了しました。",
                f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
            )
        except Exception as e:
            log.exception("処理に失敗しました。")
            self.termux_api.notify("🚫処理に失敗しました。", str(e))
        finally:
            log.info("end 'expense_main' method")

    def get_favorite_expenses(self) -> list[dict]:
        """
        get favorite expenses
        """
        log.info("start 'get_favorite_expenses' method")
        expense_config: dict[str, Any] = self.config.get("expense", {})
        favorite_expenses: list[dict] = expense_config.get("favorites", [])
        # log.debug(
        #     f"Favorite expenses: {json.dumps(favorite_expenses, indent=2, ensure_ascii=False)}"
        # )
        log.info("end 'get_favorite_expenses' method")
        return favorite_expenses

    def get_frequent_expenses(self, num_items: int = 3) -> list[dict]:
        """
        get frequent expenses
        """
        log.info("start 'get_frequent_expenses' method")
        if not os.path.exists(self.expense_history):
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
            with open(self.expense_history, "r") as f:
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
        self,
        num_items: int = 3,
        drop_duplicates: bool = True,
        with_date: bool = False,
    ) -> list[dict]:
        """
        get recent expenses
        """
        log.info("start 'get_recent_expenses' method")
        try:
            df = pd.read_csv(self.expense_history, header=None)
        except FileNotFoundError:
            return []
        df.columns = pd.Index(
            ["date", "expense_type", "expense_memo", "expense_amount"]
        )
        df["expense_memo"] = df["expense_memo"].fillna("")
        df.sort_values(by="date", ascending=False, inplace=True)
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
        recent_expenses = df.iloc[:num_items].to_dict(orient="records")
        # log.debug(
        #     f"Recent expenses: {json.dumps(recent_expenses, indent=2, ensure_ascii=False)}"
        # )
        log.info("end 'get_recent_expenses' method")
        return recent_expenses

    def get_ocr_expense(self) -> dict:
        """
        get OCR expenses
        """
        log.info("start 'get_ocr_expenses' method")
        try:
            with open(self.cache_path / "ocr_data.json", "r") as f:
                data: dict = json.load(f)
        except FileNotFoundError:
            log.exception("OCR data not found.")
            return {}
        except ValueError:
            log.exception("OCR data is invalid.")
            return {}
        ocr_expense = {
            "expense_type": data.get("expense_type", ""),
            "expense_memo": data.get("expense_memo", ""),
            "expense_amount": int(data.get("expense_amount", 0)),
            "screenshot_name": data.get("screenshot_name", ""),
        }
        # log.debug(
        #     f"Latest OCR expense: {json.dumps(ocr_expense, indent=2, ensure_ascii=False)}"
        # )
        log.info("end 'get_ocr_expenses' method")
        return ocr_expense

    def filter_duplicates(
        self,
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
        self,
        expense_type: str,
        expense_memo: str,
        expense_amount: int,
        expense_date: str = "",
    ) -> None:
        """
        store expense
        """
        log.info("start 'store_expense' method")
        expense_date_iso = (
            pd.Timestamp(expense_date).strftime("%Y-%m-%dT%H:%M:%S.%f")
            if expense_date
            and pd.Timestamp(expense_date).date() != datetime.date.today()
            else datetime.datetime.today().isoformat()
        )
        with open(self.expense_history, "a") as f:
            f.write(
                f"{expense_date_iso},{expense_type},{expense_memo},{expense_amount}\n"
            )
        log.debug(
            f"Stored expense: {expense_date_iso}, {expense_type}, {expense_memo}, {expense_amount}"
        )
        log.info("end 'store_expense' method")
        return

    def delete_expense(
        self,
        target_date: str,
        target_type: str,
        target_amount: int,
        target_memo: str,
    ) -> bool:
        """
        delete expense
        """
        log.info("start 'delete_expense' method")
        status = True
        try:
            df = pd.read_csv(self.expense_history, header=None)
            columns = ["datetime", "type", "memo", "amount"]
            df.columns = pd.Index(columns)
            df.loc[:, "date"] = pd.to_datetime(df.loc[:, "datetime"]).dt.date
        except FileNotFoundError:
            log.debug(f"File not found. {self.expense_history}")
            return False
        condition = f"date == @pd.Timestamp('{target_date}').date()"
        condition += " and type == @target_type" if target_type else ""
        condition += " and memo == @target_memo" if target_memo else ""
        condition += " and amount == @target_amount" if target_amount else ""
        idx = df.query(condition).index.to_list()
        if len(idx):
            target_idx = idx[-1]
            log.debug(f"Target index: {target_idx}")
            target_row = ", ".join(df.loc[target_idx, columns].map(str))
            df = df.drop(target_idx)
            df.loc[:, columns].to_csv(
                self.expense_history, index=False, header=False
            )
            log.debug(f"Deleted expense: {target_row}")
        else:
            log.debug(
                f"Deleting expense Failed: records not found. ({target_date}, {target_type}, {target_memo}, {target_amount})"
            )
            status = False
        log.info("end 'delete_expense' method")
        return status

    def edit_expense(
        self,
        target_expense: dict[str, Any],
        new_expense: dict[str, Any],
    ) -> bool:
        """
        edit expense
        """
        log.info("start 'edit_expense' method")
        status = True

        # validation check
        target_date = target_expense.get("expense_date")
        target_type = target_expense.get("expense_type")
        target_amount = target_expense.get("expense_amount")
        target_memo = target_expense.get("expense_memo")
        if not target_date:
            log.debug("Failed to edit record. target_date must be specified.")
            return False
        if not target_type:
            log.debug("Failed to edit record. target_type must be specified.")
            return False
        if not target_amount:
            log.debug("Failed to edit record. target_amount must be specified.")
            return False

        new_expense_date = new_expense.get("expense_date", target_date)
        new_expense_type = new_expense.get("expense_type", target_type)
        new_expense_amount = new_expense.get("expense_amount", target_amount)
        new_expense_memo = new_expense.get("expense_memo", "")

        target_amount = int(re.sub(r"[^\d]", "", str(target_amount)))
        new_expense_amount = int(re.sub(r"[^\d]", "", str(new_expense_amount)))

        log.debug(f"target_date: {target_date}")
        log.debug(f"target_type: {target_type}")
        log.debug(f"target_amount: {target_amount}")
        log.debug(f"target_memo: {target_memo}")
        log.debug(f"new_expense_date: {new_expense_date}")
        log.debug(f"new_expense_type: {new_expense_type}")
        log.debug(f"new_expense_amount: {new_expense_amount}")
        log.debug(f"new_expense_memo: {new_expense_memo}")

        try:
            df = pd.read_csv(self.expense_history, header=None)
            columns = ["datetime", "type", "memo", "amount"]
            df.columns = pd.Index(columns)
            df.loc[:, "date"] = pd.to_datetime(df.loc[:, "datetime"]).dt.date
        except FileNotFoundError:
            log.debug(f"File not found. {self.expense_history}")
            return False
        condition = f"date == @pd.Timestamp('{target_date}').date()"
        condition += " and type == @target_type" if target_type else ""
        condition += " and memo == @target_memo" if target_memo else ""
        condition += " and amount == @target_amount" if target_amount else ""
        idx = df.query(condition).index.to_list()
        if len(idx):
            target_idx = idx[-1]
            log.debug(f"Target index: {target_idx}")
            target_row = ", ".join(df.loc[target_idx, columns].map(str))
            log.debug(f"Target expense: {target_row}")
            df.loc[target_idx, "datetime"] = pd.Timestamp(
                new_expense_date
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")
            df.loc[target_idx, "type"] = new_expense_type
            df.loc[target_idx, "memo"] = new_expense_memo
            df.loc[target_idx, "amount"] = new_expense_amount
            df.sort_values("datetime", inplace=True)
            df.loc[:, columns].to_csv(
                self.expense_history, index=False, header=False
            )
            edited_row = ", ".join(df.loc[target_idx, columns].map(str))
            log.debug(f"Edited expense: {edited_row}")
        else:
            log.debug(
                f"Editing expense Failed: records not found. ({target_date}, {target_type}, {target_memo}, {target_amount})"
            )
            status = False
        log.info("end 'edit_expense' method")
        return status
