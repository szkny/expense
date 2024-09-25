import re
import gspread
import datetime as dt
from oauth2client.service_account import ServiceAccountCredentials


class GspreadHandler:
    def __init__(self, book_name: str) -> None:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            "credentials.json", scope
        )
        self.client = gspread.authorize(creds)
        self.workbook = self.client.open(book_name)
        self.load_sheet()

    def load_sheet(self) -> None:
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
        today = dt.datetime.today()
        sheetname = sheetname_list[today.month - 1]
        sheets = self.workbook.worksheets()
        if not any([sheetname == s.title for s in sheets]):
            raise ValueError(f"sheetname '{sheetname}' not found.")
        self.sheetname = sheetname
        self.sheet = self.workbook.worksheet(self.sheetname)

    def get_column(self) -> str:
        t = dt.datetime.today()
        today_str = t.date().isoformat()
        today_str = today_str.replace("-", "/")
        cell = self.sheet.find(today_str)
        if cell:
            match_result = re.match("[A-Z]+", cell.address)
            if match_result:
                return match_result[0]
        raise ValueError(
            f"'{today_str}' not found in sheet '{self.sheetname}'."
        )

    def get_row(self, expense_type: str, offset: int = 30) -> int:
        expense_type_list = [
            "給与",
            "雑所得",
            "家賃",
            "光熱費",
            "通信費",
            "特別経費",
            "食費",
            "交通費",
            "医療費",
            "書籍費",
            "遊興費",
            "雑費",
        ]
        row = offset + expense_type_list.index(expense_type)
        return row

    def add_amount_data(self, label: str, amount: int) -> None:
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
        print(f"writing: '{new_value}' to {label} in {self.sheetname}")
        self.sheet.update_acell(label, new_value)

    def add_memo(
        self, column: str, expense_type: str, memo: str, offset: int = 49
    ) -> None:
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
                print("there are no space to write a memo.")
                return
        print(f"writing: '{new_value}' to {address} in {self.sheetname}")
        self.sheet.update_acell(address, new_value)

    def register_expense(
        self, expense_type: str, amount: int, memo: str = ""
    ) -> None:
        column = self.get_column()
        row = self.get_row(expense_type)
        label = f"{column}{row}"
        self.add_amount_data(label, amount)
        if memo:
            self.add_memo(column, expense_type, memo)


if __name__ == "__main__":
    BOOKNAME = "CF (2024年度) テスト"
    handler = GspreadHandler(BOOKNAME)
    handler.register_expense("食費", 123, "コンビニ")
