import re
import gspread
import logging
import pandas as pd
import datetime as dt
from glob import glob
from typing import Any
from tenacity import retry, stop_after_attempt
from google.oauth2 import service_account

from .base import Base
from .expr_analyzer import expand_multiplication

log: logging.Logger = logging.getLogger("expense")


def get_fiscal_year() -> int:
    """
    get fiscal year
    """
    log.info("start 'get_fiscal_year' function")
    today = dt.date.today()
    year = today.year
    if today.month < 4:
        year -= 1
    log.info("end 'get_fiscal_year' function")
    return year


class GspreadHandler(Base):
    def __init__(self, book_name: str):
        super().__init__()
        log.info("start 'GspreadHandler' constructor")
        expense_config: dict[str, Any] = self.config.get("expense", {})
        expense_types_all: dict[str, list] = expense_config.get(
            "expense_types", {}
        )
        self.income_types: list[str] = expense_types_all.get("income", [])
        self.fixed_types: list[str] = expense_types_all.get("fixed", [])
        self.variable_types: list[str] = expense_types_all.get("variable", [])
        self.expense_types: list[str] = (
            self.income_types + self.fixed_types + self.variable_types
        )
        self.exclude_types: list[str] = expense_config.get("exclude_types", [])
        credentials = service_account.Credentials.from_service_account_file(
            self.config_path / "credentials.json",
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        self.client = gspread.authorize(credentials)
        self.workbook = self.client.open(book_name)
        self.sheetname_list: list[str] = [
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
        self.load_sheet()
        log.info("end 'GspreadHandler' constructor")

    def get_spreadsheet_url(self) -> str:
        return self.workbook.url + "/edit"

    @retry(stop=stop_after_attempt(3))
    def load_sheet(self, date_str: str = "") -> None:
        log.info("start 'load_sheet' method")
        try:
            date = dt.datetime.fromisoformat(date_str)
        except ValueError:
            date = dt.datetime.today()
        sheetname = self.sheetname_list[date.month - 1]
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
        row = offset + self.expense_types.index(expense_type)
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
        cell_range = (
            f"{column}{offset}:{column}{offset+len(self.expense_types)-1}"
        )
        cells = self.sheet.range(cell_range)

        def str2int(s: str) -> int:
            return int(re.sub(r"[^\d]", "", s))

        expense_list: list[gspread.Cell] = list(
            filter(lambda c: str2int(str(c.value)) > 0, cells)
        )
        log.debug(f"expense_list: {expense_list}")
        todays_expenses: list[dict] = [
            {
                "expense_type": self.expense_types[str2int(c.address) - offset],
                "amount": str(c.value),
            }
            for c in expense_list
        ]
        log.info(f"todays_expenses: {todays_expenses}")
        sum_amount = 0
        if len(todays_expenses):
            excluded_expenses: list[dict] = list(
                filter(
                    lambda item: item.get("expense_type")
                    not in (self.income_types + self.exclude_types),
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
        cell_range = f"{column}{offset+len(self.expense_types)+3}"
        cell1 = self.sheet.acell(cell_range)
        budget_left1 = max(
            str2int(str(self.sheet.acell("D16").value))
            - str2int(str(cell1.value)),
            0,
        )
        cell_range = f"{column}{offset+len(self.expense_types)+4}"
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
                _target_memo = target_memo.replace("(", "\\(").replace(
                    ")", "\\)"
                )
                s = str(cell.value)
                if matches := list(
                    re.finditer(
                        f"({target_type}:|,) *{_target_memo}",
                        s,
                    )
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

            new_expense_date = new_expense.get("expense_date", target_date)
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
                target_date == new_expense_date
                and target_type == new_expense_type
                and target_amount == new_expense_amount
                and target_memo == new_expense_memo
            ):
                log.debug("Nothing to do.")
                return False

            self.load_sheet(target_date)
            column = self.get_column(target_date)
            if (
                target_date != new_expense_date
                or target_type != new_expense_type
            ):
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
                    new_expense_date,
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

    @retry(stop=stop_after_attempt(3))
    def get_annual_fiscal_table(
        self,
        cell_range: str = "A20:F32",
        sheet_name: str = "Summary"
    ) -> pd.DataFrame:
        log.info("start 'get_annual_fiscal_table' method")
        try:
            sheet = self.workbook.worksheet(sheet_name)
            cells = sheet.get(cell_range)
            df = pd.DataFrame(cells)
            df.columns = df.iloc[0]
            df.columns.name = None
            df.set_index("日付", inplace=True)
            df = df.iloc[1:, 1:]
            df.index = pd.to_datetime(df.index)
            df = df.map(
                lambda v: int(re.sub(r"[^0-9\-]", "", v)) if type(v) is str else 0
            )
            log.debug(f"Annual fiscal table:\n{df}")
            log.info("end 'get_annual_fiscal_table' method")
            return df
        except Exception:
            log.exception("Error occurred.")
            return pd.DataFrame(
                columns=[
                    "収入",
                    "支出",
                    "CF",
                ]
            )
        finally:
            log.info("end 'get_annual_fiscal_table' method")

    @retry(stop=stop_after_attempt(3))
    def get_all_expense_df(
        self, offset: int = 31, exclude_rows_offset: int = 10
    ) -> bool:
        log.info("start 'get_all_expense_df' method")
        try:
            fyear = get_fiscal_year()
            month_list = [pd.Timestamp(m).month for m in self.sheetname_list]
            target_date_list = [
                pd.Timestamp(f"{fyear + 1 if m < 4 else fyear}-{m}-1").date()
                for m in month_list
            ]
            target_date_list.sort()
            t = dt.date.today()
            df = pd.DataFrame()
            for d in target_date_list:
                log.debug(f"target: {d}")
                month_start_str = d.isoformat()
                month_end_str = (
                    dt.date(
                        d.year if d.month < 12 else d.year + 1,
                        d.month + 1 if d.month < 12 else 1,
                        1,
                    )
                    - dt.timedelta(days=1)
                ).isoformat()
                if t < d:
                    log.debug(
                        f"stopped loop caused by the condition: {t} < {d}"
                    )
                    break
                date_list = pd.date_range(
                    month_start_str, month_end_str, freq="D"
                )
                self.load_sheet(date_str=month_start_str)
                column_start = self.get_column(date_str=month_start_str)
                column_end = self.get_column(date_str=month_end_str)
                cell_range = (
                    f"{column_start}{offset}:"
                    f"{column_end}{offset+len(self.expense_types)+exclude_rows_offset}"
                )
                cells = self.sheet.get(
                    cell_range,
                    value_render_option=gspread.worksheet.ValueRenderOption.formula,
                )
                _df_add = pd.DataFrame(cells, columns=date_list).T
                df = pd.concat([df, _df_add])
            if df.empty:
                return False
            df_memo = df.iloc[:, -4:]
            df_memo_add = df_memo.apply(
                lambda r: [s for s in r.to_list() if s], axis=1
            )
            df = pd.concat(
                [df.iloc[:, : len(self.expense_types)], df_memo_add], axis=1
            )
            df.columns = pd.Index(self.expense_types + ["memo"])
            log.debug(f"df:\n{df}")
            df_records = self.convert_expense_sheet_to_history_records(df)
            log.debug(f"df_records:\n{df_records}")
            output_path = self.cache_path / "expense_history_downloaded.log"
            df_records.to_csv(
                output_path,
                index=False,
                header=False,
            )
            log.debug(f"Generated downloaded history file: {output_path}")
            self.merge_expense_history_log()
            return True
        except Exception:
            log.exception("Error occured.")
            return False
        finally:
            log.info("end 'get_all_expense_df' method")

    def convert_expense_sheet_to_history_records(
        self, df: pd.DataFrame, memo_correct_threshold: int = 500
    ) -> pd.DataFrame:
        log.info("start 'convert_expense_sheet_to_history_records' method")
        try:
            df_records = pd.DataFrame()
            counter = 0
            for _, r in df.iterrows():
                d: str = str(r.name)
                date = pd.Timestamp(d).strftime("%Y-%m-%dT%H:%M:%S.%f")
                for t in self.expense_types:
                    amount_formula = str(r[t])
                    if not re.match(r"^=?0", amount_formula):
                        amount_formula = expand_multiplication(amount_formula)
                        amounts = [
                            int(s)
                            for s in re.findall(r"(\d+)", amount_formula)
                            if s != "0"
                        ]
                        memo_list = list(
                            filter(
                                lambda s: isinstance(s, str) and t + ": " in s,
                                r["memo"],
                            )
                        )
                        memos = (
                            memo_list[0].split(": ")[1].split(", ")
                            if len(memo_list)
                            else [""] * len(amounts)
                        )
                        # NOTE: 金額リストとメモリストの長さが合わない場合
                        # 500円以下はメモが残されていない前提で空文字列とする
                        if len(amounts) > len(memos):
                            log.debug(
                                f"modify memos for: {pd.Timestamp(date).date()}, {t}, {amounts}"
                            )
                            log.debug(f"Before: {memos}")
                            memos = [
                                (
                                    memos.pop(0)
                                    if len(memos) and i > memo_correct_threshold
                                    else ""
                                )
                                for i in amounts
                            ]
                            log.debug(f"After : {memos}")
                        for amount, memo in zip(amounts, memos):
                            df_records.loc[counter, "date"] = date
                            df_records.loc[counter, "expense_type"] = t
                            df_records.loc[counter, "expense_memo"] = memo
                            df_records.loc[counter, "expense_amount"] = amount
                            counter += 1
            df_records["expense_amount"] = df_records["expense_amount"].astype(
                int
            )
            return df_records
        finally:
            log.info("end 'convert_expense_sheet_to_history_records' method")

    def merge_expense_history_log(self) -> bool:
        log.info("start 'merge_expense_history_log' method")
        csv_files = glob((self.cache_path / "expense_history*.log").as_posix())
        dfs = []
        for f in csv_files:
            df = pd.read_csv(f, header=None)
            df.columns = pd.Index(
                ["datetime", "expense_type", "expense_memo", "expense_amount"]
            )
            df["expense_memo"] = df["expense_memo"].fillna("")
            df["__source__"] = f
            dfs.append(df)
        df_all = pd.concat(dfs, ignore_index=True)
        df_all["datetime"] = pd.to_datetime(df_all["datetime"])
        df_all["date"] = df_all["datetime"].dt.date
        cols_for_sort = [
            "datetime",
            "expense_type",
            "expense_memo",
        ]
        df_all = df_all.sort_values(cols_for_sort)

        # 各CSV内では削除しないように重複を判定し、
        # 同じデータが異なるCSVに存在する場合のみ削除
        cols_for_check = [
            "date",
            "expense_type",
            "expense_memo",
            "expense_amount",
        ]
        df_all["dup_count"] = df_all.groupby(
            cols_for_check + ["__source__"]
        ).cumcount()
        cols_for_check += ["dup_count"]
        df_merged = df_all.drop_duplicates(cols_for_check, keep="last")

        # 不要列削除
        df_merged = df_merged.drop(columns=["date", "__source__", "dup_count"])
        df_merged = df_merged.sort_values(cols_for_sort)
        df_merged["datetime"] = df_merged["datetime"].map(
            lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.%f")
        )

        # 保存
        log.debug(f"merged DataFrame:\n{df_merged}")
        output_path = self.cache_path / "merged_expense_history.log"
        df_merged.to_csv(
            output_path,
            index=False,
            header=False,
        )
        log.debug(f"Generated merged history file: {output_path}")
        log.info("end 'merge_expense_history_log' method")
        return True
