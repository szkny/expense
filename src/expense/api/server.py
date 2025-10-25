import re
import os
import json
import logging
import datetime as dt
import pandas as pd
from typing import Callable

from fastapi import FastAPI, Request, Form
from fastapi.responses import (
    Response,
    HTMLResponse,
    FileResponse,
    RedirectResponse,
    JSONResponse,
)

from .server_tools import ServerTools
from ..core.expense import get_fiscal_year
from ..core.asset_manager import AssetManager
from ..core.ocr import Ocr, get_latest_screenshot
from ..core.gspread_wrapper import GspreadHandler

app: FastAPI = FastAPI()
log: logging.Logger = logging.getLogger("expense")
gspread_handler: GspreadHandler = GspreadHandler(
    f"CF ({get_fiscal_year()}年度)"
)
asset_manager: AssetManager = AssetManager()
_df_cache_record: dict = {}
_df_cache_asset_table: dict = {}


def get_cached_records(server_tools: ServerTools) -> pd.DataFrame:
    log.info("start 'get_cached_records' method")
    try:
        now = dt.datetime.now()
        cache_life_time = (
            now - _df_cache_record.get("timestamp", now)
        ).total_seconds()
        log.debug(f"lapsed time of latest cache: {cache_life_time: ,.1f} s")
        if _df_cache_record and cache_life_time < 30:
            log.debug("returning cache DataFrame (< 30s)")
            return pd.DataFrame(_df_cache_record.get("df_records"))

        log.debug("generate new DataFrame")
        df_records = get_dataframes(server_tools)
        _df_cache_record["df_records"] = df_records
        _df_cache_record["timestamp"] = now
        return df_records
    finally:
        log.info("end 'get_cached_records' method")


def get_cached_asset_table(
    asset_manager: AssetManager,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    log.info("start 'get_cached_asset_table' method")
    try:
        now = dt.datetime.now()
        cache_life_time = (
            now - _df_cache_asset_table.get("timestamp", now)
        ).total_seconds()
        log.debug(f"lapsed time of latest cache: {cache_life_time: ,.1f} s")
        if _df_cache_asset_table and cache_life_time < 30:
            log.debug("returning cache DataFrame (< 30s)")
            return (
                pd.DataFrame(_df_cache_asset_table.get("df_summary")),
                pd.DataFrame(_df_cache_asset_table.get("df_items")),
                pd.DataFrame(_df_cache_asset_table.get("df_records")),
            )

        log.debug("generate new DataFrame")
        df_summary = asset_manager.get_header_data()
        df_items = asset_manager.get_table_data()
        df_records = asset_manager.get_monthly_history_data()
        _df_cache_asset_table["df_summary"] = df_summary
        _df_cache_asset_table["df_items"] = df_items
        _df_cache_asset_table["df_records"] = df_records
        _df_cache_asset_table["timestamp"] = now
        return (df_summary, df_items, df_records)
    finally:
        log.info("end 'get_cached_asset_table' method")


@app.middleware("http")
async def no_cache_middleware(request: Request, call_next: Callable):
    """
    /static/のキャッシュを無効化
    """
    response: Response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/manifest.json")
async def manifest() -> FileResponse:
    """
    manifest.json を返すエンドポイント
    """
    log.info("Serving manifest.json")
    return FileResponse("static/manifest.json")


@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    status: bool | None = None,
    msg: str | None = None,
    info: str | None = None,
) -> HTMLResponse:
    """
    トップページ
    """
    log.info("start 'read_root' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    commons = server_tools.generate_commons(request)
    log.info("end 'read_root' method")
    return server_tools.templates.TemplateResponse(
        "index.j2",
        {
            "request": request,
            "status": status,
            "msg": msg,
            "info": info,
            **commons,
        },
    )


@app.get("/asset_management", response_class=HTMLResponse)
def asset_management(
    request: Request,
    status: bool | None = None,
    msg: str | None = None,
    info: str | None = None,
) -> HTMLResponse:
    """
    資産管理ページ
    """
    log.info("start 'asset_management' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    df_summary, df_items, df_records = get_cached_asset_table(asset_manager)
    summary = df_summary.to_dict(orient="records")
    if len(summary):
        summary = summary[0]
        summary["total"] = f"¥{df_items['valuation'].sum():,.0f}"
        summary["change"] = (
            f" {'+' if summary['change_jpy'] >= 0 else '-'}¥{abs(summary['change_jpy']):,.0f}"
            + f" ( {'+' if summary['change_pct'] >= 0 else '-'}{abs(summary['change_pct']):,.2f}% )"
        )
        summary["usdjpy"] = f"¥{summary['usdjpy']:,.2f}"
        summary["profit"] = df_items["profit"].sum()
        summary["profit"] = (
            f"{'+' if summary['profit'] >= 0 else '-'}¥{abs(summary['profit']):,.0f}"
        )
        summary["profit_etf"] = (
            f"{'+' if summary['profit_etf'] >= 0 else '-'}¥{abs(summary['profit_etf']):,.0f}"
        )
        summary["roi"] = (
            f"{'+' if summary['roi'] >= 0 else '-'}{abs(summary['roi']):,.2f}%"
        )
    items = df_items.to_dict(orient="records")
    plotlyjs = server_tools.graph_generator.get_plotlyjs()
    log.info("end 'asset_management' method")
    return server_tools.templates.TemplateResponse(
        "asset_management.j2",
        {
            "request": request,
            "status": status,
            "msg": msg,
            "info": info,
            "icons": server_tools.icons,
            "gspread_url": asset_manager.get_spreadsheet_url(),
            "today": dt.datetime.today(),
            "asset_summary": summary,
            "asset_items": items,
            "plotlyjs": plotlyjs,
        },
    )


def get_dataframes(server_tools: ServerTools) -> pd.DataFrame:
    log.info("start 'get_dataframes' method")
    max_n_records = (
        server_tools.config.get("web_ui", {})
        .get("record_table", {})
        .get("max_n_records", 5000)
    )
    try:
        recent_expenses = server_tools.expense_handler.get_recent_expenses(
            max_n_records, drop_duplicates=False, with_date=True
        )
    except Exception:
        recent_expenses = []

    df_records = pd.DataFrame(recent_expenses)
    if not df_records.empty:
        df_records = df_records.query(
            "expense_type not in @server_tools.income_types and expense_type not in @server_tools.exclude_types"
        ).copy()
        df_records["date"] = pd.to_datetime(
            df_records["date"].map(lambda s: re.sub(r"[^\d\-]+", "", str(s))),
            errors="coerce",
        )
        df_records.dropna(subset=["date"], inplace=True)
    log.info("end 'get_dataframes' method")
    return df_records


@app.get("/api/pie_chart", response_class=JSONResponse)
def get_pie_chart(request: Request, month: str | None = None) -> JSONResponse:
    log.info("start 'get_pie_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records = get_cached_records(server_tools)
    df_graph = server_tools.graph_generator.generate_monthly_df(df_records)
    graph_html, available_months = (
        server_tools.graph_generator.generate_pie_chart(
            df_graph,
            df_records,
            target_month=month,
            theme=theme,
            include_plotlyjs=False,
        )
    )
    log.info("end 'get_pie_chart' method")
    return JSONResponse(
        content={"html": graph_html, "months": available_months}
    )


@app.get("/api/daily_chart", response_class=JSONResponse)
def get_daily_chart(request: Request, month: str | None = None) -> JSONResponse:
    log.info("start 'get_daily_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records = get_cached_records(server_tools)
    graph_html, available_months = (
        server_tools.graph_generator.generate_daily_chart(
            df_records,
            target_month=month,
            theme=theme,
            include_plotlyjs=False,
        )
    )
    log.info("end 'get_daily_chart' method")
    return JSONResponse(
        content={"html": graph_html, "months": available_months}
    )


@app.get("/api/bar_chart", response_class=HTMLResponse)
def get_bar_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_bar_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records = get_cached_records(server_tools)
    df_graph = server_tools.graph_generator.generate_monthly_df(df_records)
    graph_html = server_tools.graph_generator.generate_bar_chart(
        df_graph, theme, include_plotlyjs=False
    )
    log.info("end 'get_bar_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/asset_pie_chart", response_class=HTMLResponse)
def get_asset_pie_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_pie_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records = get_cached_asset_table(asset_manager)
    graph_html = server_tools.graph_generator.generate_asset_pie_chart(
        df_items,
        theme=theme,
        include_plotlyjs=False,
    )
    log.info("end 'get_asset_pie_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/asset_waterfall_chart", response_class=HTMLResponse)
def get_asset_waterfall_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_waterfall_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records = get_cached_asset_table(asset_manager)
    graph_html = server_tools.graph_generator.generate_asset_waterfall_chart(
        df_items, theme=theme, include_plotlyjs=False
    )
    log.info("end 'get_asset_waterfall_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/asset_monthly_history_chart", response_class=HTMLResponse)
def get_asset_monthly_history_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_monthly_history_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records = get_cached_asset_table(asset_manager)
    _df_add = pd.DataFrame()
    _df_add.loc[0, "date"] = dt.date.today()
    _df_add.loc[0, "invest_amount"] = df_records["invest_amount"].iloc[-1]
    _df_add.loc[0, "valuation"] = df_items["valuation"].sum()
    _df_add.loc[0, "profit"] = (
        _df_add.loc[0, "valuation"] - _df_add.loc[0, "invest_amount"]
    )
    _df_add.loc[0, "roi"] = (
        _df_add.loc[0, "profit"] / _df_add.loc[0, "invest_amount"] * 100
    )
    df_records = pd.concat([df_records, _df_add])
    df_records.index = pd.Index(range(len(df_records)))
    graph_html = (
        server_tools.graph_generator.generate_asset_monthly_history_chart(
            df_records, theme=theme, include_plotlyjs=False
        )
    )
    log.info("end 'get_asset_monthly_history_chart' method")
    return HTMLResponse(content=graph_html)


@app.post("/register")
def register(
    request: Request,
    expense_type: str = Form(...),
    expense_amount: str = Form(...),
    expense_memo: str = Form(...),
    expense_date: str = Form(...),
) -> RedirectResponse:
    """
    レコード登録を実行するエンドポイント
    """
    log.info("start 'register' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    status = True
    msg = ""
    info = ""
    try:
        icons: list[str] = [
            server_tools.icons.get("favorite", ""),
            server_tools.icons.get("frequent", ""),
            server_tools.icons.get("recent", ""),
        ]
        if any([emoji in expense_type for emoji in icons]):
            data = re.sub(f"({'|'.join(icons)}) ", "", expense_type).split("/")
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
        log.debug(f"Expense Date: {expense_date}")
        if expense_type and expense_amount and expense_date:
            try:
                server_tools.termux_api.toast("登録中..")
            except Exception:
                log.info("Toast notification failed.")
            server_tools.gspread_handler.register_expense(
                expense_type, expense_amount_num, expense_memo, expense_date
            )
            server_tools.expense_handler.store_expense(
                expense_type, expense_memo, expense_amount_num, expense_date
            )
            msg = "✅ 家計簿への登録が完了しました。"
            info = (
                f"[{expense_date}] "
                f"{expense_type}: "
                f"¥{expense_amount_num:,}"
                f"{', '+expense_memo if expense_memo else ''}"
            )
            try:
                server_tools.termux_api.notify(
                    msg,
                    info,
                )
            except Exception:
                log.info("Notification failed.")
        else:
            status = False
            msg = "🚫 家計簿の登録処理に失敗ました。"
    except Exception:
        log.exception("Error occurred")
        status = False
        msg = "🚫 家計簿の登録処理に失敗ました。"
    finally:
        log.info("end 'register' method")
    return RedirectResponse(
        url=f"/?status={status}&msg={msg}&info={info}", status_code=303
    )


@app.post("/ocr")
def ocr_process(
    request: Request,
) -> RedirectResponse:
    """
    OCRを実行するエンドポイント
    """
    log.info("start 'ocr' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    status = True
    msg = ""
    info = ""
    ocr = Ocr()
    try:
        recent_screenshot = os.path.basename(get_latest_screenshot())
        latest_ocr_data = server_tools.expense_handler.get_ocr_expense()
        status = True
        if len(latest_ocr_data) and (
            latest_ocr_data.get("screenshot_name") == recent_screenshot
        ):
            log.info("OCR data already exists, skipping registration.")
            expense_date = latest_ocr_data.get("expense_date")
            expense_type = latest_ocr_data.get("expense_type")
            expense_amount: int | str = int(
                latest_ocr_data.get("expense_amount")
            )
            expense_memo = latest_ocr_data.get("expense_memo", "")
            status = False
            msg = "🚫 OCRデータは登録済のためスキップされました。"
            info = (
                f"[{expense_date}] "
                f"{expense_type}: "
                f"¥{expense_amount:,}"
                f"{', '+expense_memo if expense_memo else ''}"
            )
            try:
                server_tools.termux_api.notify(msg, info)
            except Exception:
                log.info("Notification failed.")
        else:
            try:
                ocr_data = ocr.main()
            except Exception:
                log.exception("Error occurred")
                status = False
                msg = "🚫 画像の読み取り処理に失敗ました。"
                ocr_data = {}
            if ocr_data:
                expense_type = ocr_data.get("expense_type")
                expense_amount = int(ocr_data.get("expense_amount"))
                expense_memo = ocr_data.get("expense_memo", "")
                expense_date = ocr_data.get("expense_date", "")
                try:
                    server_tools.termux_api.toast("登録中..")
                except Exception:
                    log.info("Toast notification failed.")
                server_tools.gspread_handler.register_expense(
                    expense_type, expense_amount, expense_memo, expense_date
                )
                json.dump(
                    ocr_data,
                    open(server_tools.cache_path / "ocr_data.json", "w"),
                    ensure_ascii=False,
                    indent=2,
                )
                server_tools.expense_handler.store_expense(
                    expense_type, expense_memo, expense_amount, expense_date
                )
                msg = "✅ 家計簿への登録が完了しました。"
                info = (
                    f"[{expense_date}] "
                    f"{expense_type}: "
                    f"¥{expense_amount:,}"
                    f"{', '+expense_memo if expense_memo else ''}"
                )
                try:
                    server_tools.termux_api.notify(
                        msg,
                        info,
                    )
                except Exception:
                    log.info("Notification failed.")
    except Exception:
        log.exception("Error occurred")
        status = False
        msg = "🚫 家計簿の登録処理に失敗ました。"
    finally:
        log.info("end 'ocr' method")
    return RedirectResponse(
        url=f"/?status={status}&msg={msg}&info={info}", status_code=303
    )


@app.post("/delete")
def delete_process(
    request: Request,
    expense_date: str = Form(...),
    expense_type: str = Form(...),
    expense_amount: str | int = Form(...),
    expense_memo: str = Form(...),
) -> RedirectResponse:
    """
    登録レコードを削除するエンドポイント
    """
    log.info("start 'delete' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    status = True
    msg = ""
    info = ""
    try:
        try:
            server_tools.termux_api.toast("削除中..")
        except Exception:
            log.info("Toast notification failed.")
        if not expense_date or not expense_type or not expense_amount:
            status = False
        # parse date
        expense_date = re.sub(r"\(.+\)", "", expense_date)
        # parse amount
        expense_amount = int(re.sub(r"[^\d]", "", str(expense_amount)))

        if status and not server_tools.gspread_handler.delete_expense(
            expense_date,
            expense_type,
            expense_amount,
            expense_memo,
        ):
            status = False
        if status and not server_tools.expense_handler.delete_expense(
            expense_date, expense_type, expense_amount, expense_memo
        ):
            status = False
        if status:
            msg = "✅ 家計簿の削除処理が完了しました。"
        else:
            msg = "🚫 家計簿の削除処理に失敗しました。"
        info = (
            f"[{expense_date}] "
            f"{expense_type}: "
            f"¥{expense_amount:,}"
            f"{', '+expense_memo if expense_memo else ''}"
        )
        try:
            server_tools.termux_api.notify(msg, info)
        except Exception:
            log.info("Notification failed.")
    except Exception:
        log.exception("Error occurred")
        status = False
        msg = "🚫 家計簿の削除処理に失敗しました。"
    finally:
        log.info("end 'delete' method")
    return RedirectResponse(
        url=f"/?status={status}&msg={msg}&info={info}", status_code=303
    )


@app.post("/edit")
def edit_process(
    request: Request,
    target_date: str = Form(...),
    target_type: str = Form(...),
    target_amount: str | int = Form(...),
    target_memo: str = Form(...),
    new_expense_date: str = Form(...),
    new_expense_type: str = Form(...),
    new_expense_amount: str | int = Form(...),
    new_expense_memo: str = Form(...),
) -> RedirectResponse:
    """
    登録レコードを修正するエンドポイント
    """
    log.info("start 'edit' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    status = True
    msg = ""
    info = ""
    try:
        # parse date
        target_date = re.sub(r"\(.+\)", "", target_date)
        new_expense_date = re.sub(r"\(.+\)", "", new_expense_date)
        # parse amount
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
        if (
            target_date != new_expense_date
            or target_type != new_expense_type
            or target_amount != new_expense_amount
            or target_memo != new_expense_memo
        ):
            try:
                server_tools.termux_api.toast("修正中..")
            except Exception:
                log.info("Toast notification failed.")
            target_expense = dict(
                expense_date=target_date,
                expense_type=target_type,
                expense_amount=target_amount,
                expense_memo=target_memo,
            )
            new_expense = dict(
                expense_date=new_expense_date,
                expense_type=new_expense_type,
                expense_amount=new_expense_amount,
                expense_memo=new_expense_memo,
            )
            if status and not server_tools.gspread_handler.edit_expense(
                target_expense=target_expense,
                new_expense=new_expense,
            ):
                status = False
            if status and not server_tools.expense_handler.edit_expense(
                target_expense=target_expense,
                new_expense=new_expense,
            ):
                status = False
            if status:
                msg = "✅ 家計簿の修正処理が完了しました。"
            else:
                msg = "🚫 家計簿の修正処理に失敗しました。"
            info = (
                f"[{target_date}] "
                f"{target_type}: "
                f"¥{target_amount:,}"
                f"{', '+target_memo if target_memo else ''}"
                " ▶ "
                f"[{new_expense_date}] "
                f"{new_expense_type}: "
                f"¥{new_expense_amount:,}"
                f"{', '+new_expense_memo if new_expense_memo else ''}"
            )
            try:
                server_tools.termux_api.notify(msg, info)
            except Exception:
                log.info("Notification failed.")
        else:
            log.debug("Nothing to do.")
            try:
                server_tools.termux_api.toast("修正点なし")
            except Exception:
                log.info("Toast notification failed.")
            status = False
    except Exception:
        log.exception("Error occurred")
        status = False
    finally:
        log.info("end 'edit' method")
    return RedirectResponse(
        url=f"/?status={status}&msg={msg}&info={info}", status_code=303
    )
