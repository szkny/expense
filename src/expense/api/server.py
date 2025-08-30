import re
import json
import pathlib
from platformdirs import user_cache_dir

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core.expense import (
    get_fiscal_year,
    get_favorite_expenses,
    get_frequent_expenses,
    get_recent_expenses,
    filter_duplicates,
    ocr_main,
    get_ocr_expense,
    store_expense,
)
from ..core.termux_api import toast, notify
from ..core.gspread_wrapper import GspreadHandler

APP_NAME = "expense"
CACHE_PATH = pathlib.Path(user_cache_dir(APP_NAME))
CACHE_PATH.mkdir(parents=True, exist_ok=True)
N_RECORDS = 100
EXPENSE_TYPES = [
    "食費",
    "交通費",
    "遊興費",
    "雑費",
    "書籍費",
    "医療費",
    "家賃",
    "光熱費",
    "通信費",
    "養育費",
    "特別経費",
    "給与",
    "雑所得",
]
GSPREAD_HANDLER = GspreadHandler(f"CF ({get_fiscal_year()}年度)")
GSPREAD_URL = GSPREAD_HANDLER.get_spreadsheet_url()

app = FastAPI()

# 静的ファイル
app.mount("/static", StaticFiles(directory="src/expense/static"), name="static")

# テンプレート
templates = Jinja2Templates(directory="src/expense/templates")


def generate_items() -> list[str]:
    items = []
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
    item_list = [
        {"icon": "⭐", "items": favorite_expenses},
        {"icon": "🔥", "items": frequent_expenses},
        {"icon": "🕒️", "items": recent_expenses},
    ]
    for item_data in item_list:
        icon: str = item_data.get("icon", "")
        for i in item_data.get("items", []):
            item_str = f'{icon} {i["expense_type"]}/{i["expense_memo"]}/¥{i["expense_amount"]}'
            item_str = item_str.replace("//", "/")
            items.append(item_str)
    items += EXPENSE_TYPES
    return items


@app.get("/manifest.json")
async def manifest() -> FileResponse:
    # manifest.json を返すエンドポイント
    return FileResponse("static/manifest.json")


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request) -> HTMLResponse:
    # トップページ
    items = generate_items()
    recent_expenses = get_recent_expenses(
        N_RECORDS, drop_duplicates=False, with_date=True
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "n_records": N_RECORDS,
            "gspread_url": GSPREAD_URL,
            "items": items,
            "records": recent_expenses,
        },
    )


@app.post("/register", response_class=HTMLResponse)
def register_item(
    request: Request,
    expense_type: str = Form(...),
    expense_amount: str = Form(...),
    expense_memo: str = Form(...),
) -> HTMLResponse:
    # フォーム送信を受け取るエンドポイント
    if any([emoji in expense_type for emoji in "⭐🔥🕒️"]):
        data = re.sub("(⭐|🔥|🕒️) ", "", expense_type).split("/")
        if len(data) == 3:
            expense_type = data[0]
            expense_memo = data[1]
            expense_amount = data[2]
        elif len(data) == 2:
            expense_type = data[0]
            expense_memo = ""
            expense_amount = data[1]
    expense_amount_num = int(re.sub(r"[^\d]", "", expense_amount))
    print(f"Expense Type: {expense_type}")
    print(f"Expense Amount: {expense_amount_num}")
    print(f"Expense Memo: {expense_memo}")
    if expense_type and expense_amount:
        toast("登録中..")
        GSPREAD_HANDLER.register_expense(
            expense_type, expense_amount_num, expense_memo
        )
        store_expense(expense_type, expense_memo, expense_amount_num)
        notify(
            "家計簿への登録が完了しました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount_num:,}",
        )
    items = generate_items()
    recent_expenses = get_recent_expenses(
        N_RECORDS, drop_duplicates=False, with_date=True
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "n_records": N_RECORDS,
            "gspread_url": GSPREAD_URL,
            "items": items,
            "records": recent_expenses,
            "selected_type": expense_type,
            "input_amount": expense_amount_num,
            "input_memo": expense_memo,
        },
    )


@app.post("/ocr", response_class=HTMLResponse)
def ocr(
    request: Request,
) -> HTMLResponse:
    # OCRを実行するエンドポイント
    ocr_data = ocr_main()
    expense_type = ocr_data["expense_type"]
    expense_amount: int | str = int(ocr_data["expense_amount"])
    expense_memo = ocr_data.get("expense_memo", "")
    latest_ocr_data = get_ocr_expense()
    if len(latest_ocr_data) and (
        latest_ocr_data.get("screenshot_name")
        == ocr_data.get("screenshot_name")
    ):
        notify(
            "OCRデータは登録済のためスキップされました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
        )
        expense_type = ""
        expense_amount = ""
        expense_memo = ""
    else:
        json.dump(
            ocr_data,
            open(CACHE_PATH / "ocr_data.json", "w"),
            ensure_ascii=False,
            indent=2,
        )
        toast("登録中..")
        GSPREAD_HANDLER.register_expense(
            expense_type, expense_amount, expense_memo
        )
        store_expense(expense_type, expense_memo, expense_amount)
        notify(
            "家計簿への登録が完了しました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
        )
    items = generate_items()
    recent_expenses = get_recent_expenses(
        N_RECORDS, drop_duplicates=False, with_date=True
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "n_records": N_RECORDS,
            "gspread_url": GSPREAD_URL,
            "items": items,
            "records": recent_expenses,
            "selected_type": expense_type,
            "input_amount": expense_amount,
            "input_memo": expense_memo,
        },
    )
