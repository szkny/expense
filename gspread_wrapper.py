import gspread
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

    def add_amount_data(self, label: str, amount: int) -> None:
        sheet = self.workbook.worksheet("シート1")
        cell = sheet.acell(
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
        print(f"writing: '{new_value}' to {label}")
        sheet.update_acell(label, new_value)

    def add_memo(self, column: str, category: str, memo: str) -> None:
        sheet = self.workbook.worksheet("シート1")
        offset = 2
        cells = sheet.range(f"{column}{offset}:{column}{offset+5}")
        non_empty_counts = len(
            list(filter(lambda c: c.value != "" and c.value is not None, cells))
        )
        cells = list(
            filter(
                lambda c: isinstance(c.value, str) and category in c.value,
                cells,
            )
        )
        if len(cells):
            cell = cells[0]
            new_value = f"{cell.value}, {memo}"
            address = cell.address
        else:
            new_value = f"{category}: {memo}"
            address = f"{column}{offset+non_empty_counts}"
        print(f"writing: '{new_value}' to {address}")
        sheet.update_acell(address, new_value)


if __name__ == "__main__":
    handler = GspreadHandler("hoge")
    handler.add_amount_data("B4", 9)
