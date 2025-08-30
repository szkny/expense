import re
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
    store_expense,
)
from ..core.termux_api import toast, notify
from ..core.gspread_wrapper import GspreadHandler

app = FastAPI()

# 静的ファイル
app.mount("/static", StaticFiles(directory="src/expense/static"), name="static")

# テンプレート
templates = Jinja2Templates(directory="src/expense/templates")

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
    return templates.TemplateResponse(
        "index.html", {"request": request, "items": items}
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
            expense_amount = int(re.sub(r"[^\d]", "", data[2]))
        elif len(data) == 2:
            expense_type = data[0]
            expense_memo = ""
            expense_amount = int(re.sub(r"[^\d]", "", data[1]))
    print(f"Expense Type: {expense_type}")
    print(f"Expense Amount: {expense_amount}")
    print(f"Expense Memo: {expense_memo}")
    if expense_type and expense_amount:
        toast("登録中..")
        current_fiscal_year = get_fiscal_year()
        bookname = f"CF ({current_fiscal_year}年度)"
        handler = GspreadHandler(bookname)
        handler.register_expense(expense_type, expense_amount, expense_memo)
        store_expense(expense_type, expense_memo, expense_amount)
        notify(
            "家計簿への登録が完了しました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
        )
    items = generate_items()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "items": items,
            "selected_type": expense_type,
            "input_amount": expense_amount,
            "input_memo": expense_memo,
        },
    )
