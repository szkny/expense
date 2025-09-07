import re
import pathlib
import gspread
import datetime as dt
import logging as log
from platformdirs import user_config_dir
from tenacity import retry, stop_after_attempt
from google.oauth2 import service_account

APP_NAME = "expense"
CONFIG_PATH = pathlib.Path(user_config_dir(APP_NAME))
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

expense_type_list: list[str] = [
    "給与",
    "雑所得",
    "家賃",
    "光熱費",
    "通信費",
    "養育費",
    "特別経費",
    "食費",
    "交通費",
    "医療費",
    "書籍費",
    "遊興費",
    "雑費",
]


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
        row = offset + expense_type_list.index(expense_type)
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
    ) -> None:
        log.info("start 'add_memo' method")
        cell_range = f"{column}{offset}:{column}{offset+3}"
        cells = self.sheet.range(cell_range)
        non_empty_counts = len(
            list(filter(lambda c: c.value != "" and c.value is not None, cells))
        )
        cells = list(
            filter(
                lambda c: isinstance(c.value, str) and expense_type in c.value,
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
                return
        log.debug(f"writing: '{new_value}' to {address} in {self.sheetname}")
        log.info("end 'add_memo' method")
        self.sheet.update_acell(address, new_value)

    def register_expense(
        self, expense_type: str, amount: int, memo: str = "", date_str: str = ""
    ) -> None:
        log.info("start 'register_expense' method")
        column = self.get_column(date_str)
        row = self.get_row(expense_type)
        label = f"{column}{row}"
        self.add_amount_data(label, amount)
        if memo:
            self.add_memo(column, expense_type, memo)
        log.info("end 'register_expense' method")

    @retry(stop=stop_after_attempt(3))
    def get_todays_expenses(self, offset: int = 31) -> str:
        log.info("start 'get_today_expenses' method")
        column = self.get_column()
        cell_range = (
            f"{column}{offset}:{column}{offset+len(expense_type_list)-1}"
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
                "expense_type": expense_type_list[str2int(c.address) - offset],
                "amount": str(c.value),
            }
            for c in expense_list
        ]
        log.info(f"todays_expenses: {todays_expenses}")
        exclude_expense_types = ["給与", "雑所得"]
        sum_amount = 0
        if len(todays_expenses):
            excluded_expenses = list(
                filter(
                    lambda item: item.get("expense_type")
                    not in exclude_expense_types,
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
        cell_range = f"{column}{offset+len(expense_type_list)+3}"
        cell1 = self.sheet.acell(cell_range)
        budget_left1 = max(
            str2int(str(self.sheet.acell("D16").value))
            - str2int(str(cell1.value)),
            0,
        )
        cell_range = f"{column}{offset+len(expense_type_list)+4}"
        cell2 = self.sheet.acell(cell_range)
        budget_left2 = str2int(str(cell2.value))
        log.debug(f"cell1: {cell1}, cell2: {cell2}")
        log.debug(f"budget_left1: {budget_left1}, budget_left2: {budget_left2}")
        result = f"💰️残予算: ¥{budget_left1:,}  (¥{budget_left2:,}/日)"
        log.info("end 'get_budget_left' method")
        return result


if __name__ == "__main__":
    BOOKNAME = "CF (2024年度)"
    handler = GspreadHandler(BOOKNAME)
    # handler.register_expense("食費", 123, "コンビニ")
    todays_expenses = handler.get_todays_expenses()
    print(todays_expenses)
