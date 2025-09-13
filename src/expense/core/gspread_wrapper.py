import re
import json
import pathlib
import gspread
import datetime as dt
import logging as log
from typing import Any
from platformdirs import user_config_dir
from tenacity import retry, stop_after_attempt
from google.oauth2 import service_account

APP_NAME: str = "expense"
CONFIG_PATH: pathlib.Path = pathlib.Path(user_config_dir(APP_NAME))
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

try:
    with open(CONFIG_PATH / "config.json", "r") as f:
        CONFIG: dict[str, Any] = json.load(f)
except Exception:
    log.debug(
        f"Error occurred when loading config file. ({CONFIG_PATH / 'config.json'})"
    )
    CONFIG = {}
EXPENSE_TYPES_ALL: dict[str, list] = CONFIG.get("expense_types", {})
INCOME_TYPES: list[str] = EXPENSE_TYPES_ALL.get("income", [])
FIXED_TYPES: list[str] = EXPENSE_TYPES_ALL.get("fixed", [])
VARIABLE_TYPES: list[str] = EXPENSE_TYPES_ALL.get("variable", [])
EXPENSE_TYPES: list[str] = INCOME_TYPES + FIXED_TYPES + VARIABLE_TYPES
EXCLUDE_TYPES: list[str] = CONFIG.get("exclude_types", [])


class GspreadHandler:
    def __init__(self, book_name: str) -> None:
        log.info("start 'GspreadHandler' constructor")
        credentials = service_account.Credentials.from_service_account_file(
            CONFIG_PATH / "credentials.json",
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        self.client = gspread.authorize(credentials)
        self.workbook = self.client.open(book_name)
        self.load_sheet()
        log.info("end 'GspreadHandler' constructor")

    def get_spreadsheet_url(self) -> str:
        return self.workbook.url

    @retry(stop=stop_after_attempt(3))
    def load_sheet(self, date_str: str = "") -> None:
        log.info("start 'load_sheet' method")
        sheetname_list: list[str] = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        try:
            date = dt.datetime.fromisoformat(date_str)
        except ValueError:
            date = dt.datetime.today()
        sheetname = sheetname_list[date.month - 1]
        sheets = self.workbook.worksheets()
        if not any([sheetname == s.title for s in sheets]):
            raise ValueError(f"sheetname '{sheetname}' not found.")
        self.sheetname = sheetname
        self.sheet = self.workbook.worksheet(self.sheetname)
        log.info("end 'load_sheet' method")

    def get_column(self, date_str: str = "") -> str:
        log.info("start 'get_column' method")
        try:
            try:
                date_str = (
                    dt.datetime.fromisoformat(date_str).date().isoformat()
                )
            except ValueError:
                pass
            date_str = date_str.replace("-", "/")
            if not re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", date_str):
                date_str = dt.date.today().isoformat()
                date_str = date_str.replace("-", "/")
            cell = self.sheet.find(date_str)
            if cell:
                match_result = re.match("[A-Z]+", cell.address)
                if match_result:
                    return match_result[0]
            raise ValueError(
                f"'{date_str}' not found in sheet '{self.sheetname}'."
            )
        finally:
            log.info("end 'get_column' method")

    def get_row(self, expense_type: str, offset: int = 31) -> int:
        log.info("start 'get_row' method")
        row = offset + EXPENSE_TYPES.index(expense_type)
        log.info("end 'get_row' method")
        return row

    @retry(stop=stop_after_attempt(3))
    def add_amount_data(self, label: str, amount: int) -> None:
        log.info("start 'add_amount_data' method")
        cell = self.sheet.acell(
            label,
            value_render_option=gspread.worksheet.ValueRenderOption.formula,
        )
        if cell.value == 0:
            new_value = f"={amount}"
        elif isinstance(cell.value, int):
            new_value = f"={cell.value}+{amount}"
        elif isinstance(cell.value, str):
            new_value = f"{cell.value}+{amount}"
        else:
            new_value = str(amount)
        log.debug(f"writing: '{new_value}' to {label} in {self.sheetname}")
        log.info("end 'add_amount_data' method")
        self.sheet.update_acell(label, new_value)

    @retry(stop=stop_after_attempt(3))
    def add_memo(
        self, column: str, expense_type: str, memo: str, offset: int = 51
    ) -> bool:
        log.info("start 'add_memo' method")
        try:
            cell_range = f"{column}{offset}:{column}{offset+3}"
            cells = self.sheet.range(cell_range)
            non_empty_counts = len(
                list(
                    filter(
                        lambda c: c.value != "" and c.value is not None, cells
                    )
                )
            )
            cells = list(
                filter(
                    lambda c: isinstance(c.value, str)
                    and expense_type in c.value,
                    cells,
                )
            )
            if len(cells):
                cell = cells[0]
                new_value = f"{cell.value}, {memo}"
                address = cell.address
            else:
                new_value = f"{expense_type}: {memo}"
                address = f"{column}{offset+non_empty_counts}"
                if non_empty_counts > 3:
                    log.warn("there are no space to write a memo.")
                    return False
            log.debug(
                f"writing: '{new_value}' to {address} in {self.sheetname}"
            )
            self.sheet.update_acell(address, new_value)
        except Exception:
            log.exception("Error occured.")
            return False
        finally:
            log.info("end 'add_memo' method")
            return True

    def register_expense(
        self, expense_type: str, amount: int, memo: str = "", date_str: str = ""
    ) -> None:
        log.info("start 'register_expense' method")
        try:
            self.load_sheet(date_str)
            column = self.get_column(date_str)
            row = self.get_row(expense_type)
            label = f"{column}{row}"
            self.add_amount_data(label, amount)
            if memo:
                self.add_memo(column, expense_type, memo)
        finally:
            self.load_sheet()
            log.info("end 'register_expense' method")

    @retry(stop=stop_after_attempt(3))
    def get_todays_expenses(self, offset: int = 31) -> str:
        log.info("start 'get_today_expenses' method")
        column = self.get_column()
        cell_range = f"{column}{offset}:{column}{offset+len(EXPENSE_TYPES)-1}"
        cells = self.sheet.range(cell_range)

        def str2int(s: str) -> int:
            return int(re.sub(r"[^\d]", "", s))

        expense_list: list[gspread.Cell] = list(
            filter(lambda c: str2int(str(c.value)) > 0, cells)
        )
        log.debug(f"expense_list: {expense_list}")
        todays_expenses: list[dict] = [
            {
                "expense_type": EXPENSE_TYPES[str2int(c.address) - offset],
                "amount": str(c.value),
            }
            for c in expense_list
        ]
        log.info(f"todays_expenses: {todays_expenses}")
        sum_amount = 0
        if len(todays_expenses):
            excluded_expenses = list(
                filter(
                    lambda item: item.get("expense_type") not in EXCLUDE_TYPES,
                    todays_expenses,
                )
            )
            sum_amount = sum(
                [str2int(str(c.get("amount"))) for c in excluded_expenses]
            )
            result = "📝"
            result += ", ".join(
                [
                    f"{d.get('expense_type')}: {d.get('amount')}"
                    for d in todays_expenses
                ]
            )
        else:
            result = ""
        result += f"\n🔢合計: ¥{sum_amount:,}"
        budget_left = self.get_budget_left(offset=offset)
        result += f"\n{budget_left}"
        log.info("end 'get_today_expenses' method")
        return result

    @retry(stop=stop_after_attempt(3))
    def get_budget_left(self, offset: int = 31) -> str:
        log.info("start 'get_budget_left' method")

        def str2int(s: str) -> int:
            return int(re.sub(r"[^\d]", "", s))

        column = self.get_column()
        cell_range = f"{column}{offset+len(EXPENSE_TYPES)+3}"
        cell1 = self.sheet.acell(cell_range)
        budget_left1 = max(
            str2int(str(self.sheet.acell("D16").value))
            - str2int(str(cell1.value)),
            0,
        )
        cell_range = f"{column}{offset+len(EXPENSE_TYPES)+4}"
        cell2 = self.sheet.acell(cell_range)
        budget_left2 = str2int(str(cell2.value))
        log.debug(f"cell1: {cell1}, cell2: {cell2}")
        log.debug(f"budget_left1: {budget_left1}, budget_left2: {budget_left2}")
        result = f"💰️残予算: ¥{budget_left1:,}  (¥{budget_left2:,}/日)"
        log.info("end 'get_budget_left' method")
        return result

    @retry(stop=stop_after_attempt(3))
    def delete_amount(
        self,
        column: str,
        target_type: str,
        target_amount: int,
    ) -> bool:
        log.info("start 'delete_amount' method")
        row = self.get_row(target_type)
        address = f"{column}{row}"
        cell = self.sheet.acell(
            address,
            value_render_option=gspread.worksheet.ValueRenderOption.formula,
        )

        if isinstance(cell.value, int):
            if cell.value == target_amount:
                log.debug(
                    f"Deleting amount: `{target_amount}` of {address} in {self.sheetname}"
                )
                self.sheet.update_acell(address, 0)
            else:
                log.debug(
                    f"Deleting amount failed: target not found. (target_amount={target_amount}, cell.value={cell.value})"
                )
                return False
        elif isinstance(cell.value, str):
            # 最後にマッチした部分を探す
            new_value: str | int = ""
            s = str(cell.value)
            if matches := list(re.finditer(f"[=+] *{target_amount}", s)):
                last_match = matches[-1]
                start, end = last_match.span()
                new_value = s[:start] + s[end:]
            else:
                log.debug(
                    f"Deleting amount failed: target not found in the cell formula. (target_amount={target_amount}, cell.value={cell.value})"
                )
                return False
            new_value = new_value.strip()
            if len(new_value) == 0:
                new_value = 0
            elif new_value[0] == "+":
                new_value = "=" + new_value[1:]
            log.debug(f"Generated new_value: '{new_value}'")
            if cell.value != new_value:
                log.debug(
                    (
                        f"Deleting amount: `{target_amount}` of {address} in {self.sheetname}\n"
                        f"\tBefore: '{cell.value}'\n\tAfter : '{new_value}'"
                    )
                )
                self.sheet.update_acell(address, new_value)
            else:
                log.debug(
                    f"Deleting amount failed: target not found in the cell formula. (target_amount={target_amount}, cell.value={cell.value})"
                )
                return False
        else:
            return False
        log.info("end 'delete_amount' method")
        return True

    @retry(stop=stop_after_attempt(3))
    def delete_memo(
        self, column: str, target_type: str, target_memo: str, offset: int = 51
    ) -> bool:
        log.info("start 'delete_memo' method")
        cell_range = f"{column}{offset}:{column}{offset+3}"
        cells = self.sheet.range(cell_range)
        cells = list(
            filter(
                lambda c: isinstance(c.value, str) and target_type in c.value,
                cells,
            )
        )
        if len(cells):
            cell = cells[0]
            address = cell.address

            # 最後にマッチした部分を探す
            new_value: str = ""
            s = str(cell.value)
            if matches := list(
                re.finditer(f"({target_type}:|,) *{target_memo}", s)
            ):
                last_match = matches[-1]
                start, end = last_match.span()
                new_value = s[:start] + s[end:]
            else:
                new_value = s
            new_value = new_value.strip()
            if len(new_value) == 0:
                new_value = ""
            elif new_value[0] == ",":
                new_value = target_type + ":" + new_value[1:]
            log.debug(f"Generated new_value: '{new_value}'")
            if cell.value != new_value:
                log.debug(
                    (
                        f"Deleting memo: '{target_memo}' of {address} in {self.sheetname}\n"
                        f"\tBefore: '{cell.value}'\n\tAfter : '{new_value}'"
                    )
                )
                self.sheet.update_acell(address, new_value)
            else:
                log.debug(
                    f"Deleting memo failed: target not found in the cell. (target_memo={target_memo}, cell.value={cell.value})"
                )
                return False
        else:
            log.debug(
                f"Deleting memo failed: target not found in the cell. (target_memo={target_memo})"
            )
            return False
        log.info("end 'delete_memo' method")
        return True

    def delete_expense(
        self,
        target_date: str,
        target_type: str,
        target_amount: str | int,
        target_memo: str = "",
    ) -> bool:
        log.info("start 'delete_expense' method")
        try:
            log.debug(f"target_date: {target_date}")
            log.debug(f"target_type: {target_type}")
            log.debug(f"target_amount: {target_amount}")
            log.debug(f"target_memo: {target_memo}")
            if not target_date:
                log.debug(
                    "Failed to delete record. target_date must be specified."
                )
                return False
            if not target_type:
                log.debug(
                    "Failed to delete record. target_type must be specified."
                )
                return False
            if not target_amount:
                log.debug(
                    "Failed to delete record. target_amount must be specified."
                )
                return False

            target_amount = int(re.sub(r"[^\d]", "", str(target_amount)))

            self.load_sheet(target_date)
            column = self.get_column(target_date)
            if not self.delete_amount(column, target_type, target_amount):
                return False

            if target_memo and not self.delete_memo(
                column, target_type, target_memo
            ):
                return False
            return True
        finally:
            self.load_sheet()
            log.info("end 'delete_expense' method")

    @retry(stop=stop_after_attempt(3))
    def edit_amount(
        self,
        column: str,
        target_type: str,
        target_amount: int,
        new_expense_amount: int,
    ) -> bool:
        log.info("start 'edit_amount' method")
        log.debug(
            f"Editing expense_amount: '{target_amount}' to '{new_expense_amount}'"
        )
        row = self.get_row(target_type)
        address = f"{column}{row}"
        cell = self.sheet.acell(
            address,
            value_render_option=gspread.worksheet.ValueRenderOption.formula,
        )
        log.debug(
            f"call.value='{cell.value}', address='{address}', sheetname='{self.sheetname}'"
        )
        if isinstance(cell.value, int):
            if cell.value == target_amount:
                log.debug(
                    f"Editing amount: `{target_amount}` to `{new_expense_amount}`"
                )
                self.sheet.update_acell(address, new_expense_amount)
            else:
                log.debug(
                    f"Editing amount failed: target not found. (target_amount={target_amount}, cell.value={cell.value})"
                )
                return False
        elif isinstance(cell.value, str):
            # 最後にマッチした部分を探す
            new_value: str | int = ""
            s = str(cell.value)
            if matches := list(re.finditer(f"[=+] *{target_amount}", s)):
                last_match = matches[-1]
                log.debug(f"match pattern found: '{last_match}'")
                start, end = last_match.span()
                new_value = (
                    (s[:start] + "+" if len(s[:start]) and s[0] == "=" else "=")
                    + str(new_expense_amount)
                    + s[end:]
                )
            else:
                log.debug(
                    f"Editing amount failed: target not found in the cell formula. (target_amount={target_amount}, cell.value={cell.value})"
                )
                return False
            new_value = new_value.strip()
            log.debug(f"Generated new_value: '{new_value}'")
            if cell.value != new_value:
                log.debug(
                    (
                        f"Editing amount: `{target_amount}` of {address} in {self.sheetname}\n"
                        f"\tBefore: '{cell.value}'\n\tAfter : '{new_value}'"
                    )
                )
                self.sheet.update_acell(address, new_value)
            else:
                log.debug(
                    f"Editing amount failed: target not found in the cell formula. (target_amount={target_amount}, cell.value={cell.value})"
                )
                return False
        else:
            log.debug(
                f"Editing amount failed: cell.value is invalid. (call.value={cell.value} at address='{address}')"
            )
            return False
        log.info("end 'edit_amount' method")
        return True

    @retry(stop=stop_after_attempt(3))
    def edit_memo(
        self,
        column: str,
        target_type: str,
        target_memo: str,
        new_expense_memo: str,
        offset: int = 51,
    ) -> bool:
        log.info("start 'edit_memo' method")
        log.debug(
            f"Editing expense_memo: '{target_memo}' to '{new_expense_memo}'"
        )
        if len(target_memo) and len(new_expense_memo) == 0:
            if not self.delete_memo(column, target_type, target_memo):
                return False
        elif len(target_memo) == 0 and len(new_expense_memo):
            if not self.add_memo(column, target_type, new_expense_memo):
                return False
        else:
            cell_range = f"{column}{offset}:{column}{offset+3}"
            cells = self.sheet.range(cell_range)
            cells = list(
                filter(
                    lambda c: isinstance(c.value, str)
                    and target_type in c.value,
                    cells,
                )
            )
            if len(cells):
                cell = cells[0]
                address = cell.address
                log.debug(
                    f"call.value='{cell.value}', address='{address}', sheetname='{self.sheetname}'"
                )
                # 最後にマッチした部分を探す
                new_value: str = ""
                s = str(cell.value)
                if matches := list(
                    re.finditer(f"({target_type}:|,) *{target_memo}", s)
                ):
                    last_match = matches[-1]
                    start, end = last_match.span()
                    new_value = (
                        (
                            s[:start] + ", "
                            if len(s[:start])
                            else f"{target_type}: "
                        )
                        + new_expense_memo
                        + s[end:]
                    )
                else:
                    log.debug(
                        f"Editing memo failed: target not found in the cell. (target_memo={target_memo}, cell.value={cell.value})"
                    )
                    return False
                new_value = new_value.strip()
                log.debug(f"Generated new_value: '{new_value}'")
                if cell.value != new_value:
                    log.debug(
                        (
                            f"Editing memo: '{target_memo}' of {address} in {self.sheetname}\n"
                            f"\tBefore: '{cell.value}'\n\tAfter : '{new_value}'"
                        )
                    )
                    self.sheet.update_acell(address, new_value)
                else:
                    log.debug(
                        f"Editing memo failed: target not found in the cell. (target_memo={target_memo}, cell.value={cell.value})"
                    )
                    return False
            else:
                log.debug(
                    f"Editing memo failed: target not found in the cell. (target_memo={target_memo})"
                )
                return False
        log.info("end 'edit_memo' method")
        return True

    def edit_expense(
        self,
        target_expense: dict[str, Any],
        new_expense: dict[str, Any],
    ) -> bool:
        log.info("start 'edit_record' method")
        try:
            target_date = target_expense.get("expense_date")
            target_type = target_expense.get("expense_type")
            target_amount = target_expense.get("expense_amount")
            target_memo = str(target_expense.get("expense_memo"))
            if not target_date:
                log.debug(
                    "Failed to edit record. target_date must be specified."
                )
                return False
            if not target_type:
                log.debug(
                    "Failed to edit record. target_type must be specified."
                )
                return False
            if not target_amount:
                log.debug(
                    "Failed to edit record. target_amount must be specified."
                )
                return False

            new_expense_type = new_expense.get("expense_type", target_type)
            new_expense_amount = new_expense.get(
                "expense_amount", target_amount
            )
            new_expense_memo = str(new_expense.get("expense_memo", ""))

            target_amount = int(re.sub(r"[^\d]", "", str(target_amount)))
            new_expense_amount = int(
                re.sub(r"[^\d]", "", str(new_expense_amount))
            )

            if (
                target_type == new_expense_type
                and target_amount == new_expense_amount
                and target_memo == new_expense_memo
            ):
                log.debug("Nothing to do.")
                return False

            self.load_sheet(target_date)
            column = self.get_column(target_date)
            if target_type != new_expense_type:
                log.debug(
                    f"Change expense_type: '{target_type}' to '{new_expense_type}'"
                )
                self.delete_amount(column, target_type, target_amount)
                if target_memo:
                    self.delete_memo(column, target_type, target_memo)
                self.register_expense(
                    new_expense_type,
                    new_expense_amount,
                    new_expense_memo,
                    target_date,
                )
            else:
                if (
                    target_amount != new_expense_amount
                    and not self.edit_amount(
                        column,
                        target_type,
                        target_amount,
                        new_expense_amount,
                    )
                ):
                    return False
                if target_memo != new_expense_memo and not self.edit_memo(
                    column,
                    target_type,
                    target_memo,
                    new_expense_memo,
                ):
                    return False
            return True
        finally:
            self.load_sheet()
            log.info("end 'end_record' method")


if __name__ == "__main__":
    BOOKNAME = "CF (2024年度)"
    handler = GspreadHandler(BOOKNAME)
    # handler.register_expense("食費", 123, "コンビニ")
    todays_expenses = handler.get_todays_expenses()
    print(todays_expenses)
