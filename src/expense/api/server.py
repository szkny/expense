import re
import io
import os
import json
import base64
import pathlib
import logging as log
from typing import Any

# from plotly import express as px
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
from ..core.ocr import get_latest_screenshot
from ..core.gspread_wrapper import GspreadHandler

APP_NAME = "expense"
CACHE_PATH = pathlib.Path(user_cache_dir(APP_NAME))
CACHE_PATH.mkdir(parents=True, exist_ok=True)
N_RECORDS = 200
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
    """
    インスタント登録用のアイテムを生成
    """
    log.info("start 'generate_items' method")
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
    log.info("end 'generate_items' method")
    return items


def generate_commons() -> dict[str, Any]:
    """
    テンプレートに渡す共通データを生成
    """
    log.info("start 'generate_commons' method")
    # 最新のスクリーンショットを取得してBase64エンコード
    screenshot_name = get_latest_screenshot()
    buf = io.BytesIO()
    with open(screenshot_name, "rb") as f:
        buf.write(f.read())
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")

    # 最新のOCRデータを取得して、最新のスクリーンショットと同じならOCR登録済みとみなす
    latest_ocr_data = get_ocr_expense()
    disable_ocr = len(latest_ocr_data) and (
        latest_ocr_data.get("screenshot_name")
        == os.path.basename(screenshot_name)
    )

    # インスタント登録用のアイテムを取得
    items = generate_items()

    # 最近の支出履歴を取得
    recent_expenses = get_recent_expenses(
        N_RECORDS, drop_duplicates=False, with_date=True
    )
    # Plotlyのグラフを生成
    # df = px.data.iris()
    # fig = px.scatter(df, x="sepal_width", y="sepal_length", color="species")
    # graph_html = fig.to_html(full_html=False)
    log.info("end 'generate_commons' method")
    return {
        "n_records": N_RECORDS,
        "gspread_url": GSPREAD_URL,
        "items": items,
        "records": recent_expenses,
        "screenshot_name": screenshot_name,
        "screenshot_base64": img_base64,
        "disable_ocr": disable_ocr,
        # "graph": graph_html,
    }


@app.get("/manifest.json")
async def manifest() -> FileResponse:
    """
    manifest.json を返すエンドポイント
    """
    log.info("Serving manifest.json")
    return FileResponse("static/manifest.json")


@app.get("/", response_class=HTMLResponse)
def read_root(request: Request) -> HTMLResponse:
    """
    トップページ
    """
    log.info("start 'read_root' method")
    commons = generate_commons()
    log.info("end 'read_root' method")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            **commons,
        },
    )


@app.post("/register", response_class=HTMLResponse)
def register_item(
    request: Request,
    expense_type: str = Form(...),
    expense_amount: str = Form(...),
    expense_memo: str = Form(...),
) -> HTMLResponse:
    """
    フォーム送信を受け取るエンドポイント
    """
    log.info("start 'register_item' method")
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
    log.debug(f"Expense Type: {expense_type}")
    log.debug(f"Expense Amount: {expense_amount_num}")
    log.debug(f"Expense Memo: {expense_memo}")
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
    commons = generate_commons()
    log.info("end 'register_item' method")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "selected_type": expense_type,
            "input_amount": expense_amount_num,
            "input_memo": expense_memo,
            **commons,
        },
    )


@app.post("/ocr", response_class=HTMLResponse)
def ocr(
    request: Request,
) -> HTMLResponse:
    """
    OCRを実行するエンドポイント
    """
    log.info("start 'ocr' method")
    recent_screenshot = os.path.basename(get_latest_screenshot())
    latest_ocr_data = get_ocr_expense()
    if len(latest_ocr_data) and (
        latest_ocr_data.get("screenshot_name") == recent_screenshot
    ):
        log.info("OCR data already exists, skipping registration.")
        expense_type = latest_ocr_data["expense_type"]
        expense_amount: int | str = int(latest_ocr_data["expense_amount"])
        expense_memo = latest_ocr_data.get("expense_memo", "")
        notify(
            "OCRデータは登録済のためスキップされました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
        )
        expense_type = ""
        expense_amount = ""
        expense_memo = ""
    else:
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
        toast("登録中..")
        GSPREAD_HANDLER.register_expense(
            expense_type, expense_amount, expense_memo
        )
        store_expense(expense_type, expense_memo, expense_amount)
        notify(
            "家計簿への登録が完了しました。",
            f"{expense_type}{': '+expense_memo if expense_memo else ''}, ¥{expense_amount:,}",
        )
    commons = generate_commons()
    log.info("end 'ocr' method")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "selected_type": expense_type,
            "input_amount": expense_amount,
            "input_memo": expense_memo,
            **commons,
        },
    )
