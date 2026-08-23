import re
import os
import json
import logging
import datetime as dt
import threading
import time
from typing import Any
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


class _LazyGspreadHandler:
    """Google Sheetsへの接続を最初の利用時まで遅延させる。"""

    def __init__(self, book_name: str) -> None:
        self.book_name = book_name
        self._handler: GspreadHandler | None = None
        self._lock = threading.Lock()

    def _get_handler(self) -> GspreadHandler:
        if self._handler is not None:
            return self._handler
        with self._lock:
            if self._handler is not None:
                return self._handler
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    self._handler = GspreadHandler(self.book_name)
                    return self._handler
                except Exception as error:
                    last_error = error
                    if attempt < 2:
                        time.sleep(2**attempt)
            assert last_error is not None
            raise last_error

    def get_spreadsheet_url(self) -> str:
        try:
            return self._get_handler().get_spreadsheet_url()
        except Exception:
            log.exception("Google Sheets is unavailable.")
            return ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_handler(), name)


gspread_handler: Any = _LazyGspreadHandler(f"CF ({get_fiscal_year()}年度)")
asset_manager: AssetManager = AssetManager()
_df_cache_record: dict = {}
_df_cache_record_lock = threading.Lock()
_RECORD_CACHE_TTL = 300
_df_cache_asset_table: dict = {}
_df_cache_asset_table_lock = threading.Lock()
_ASSET_CACHE_TTL: dict[str, int] = {
    "df_summary": 30,
    "df_stock": 30,
    "df_items": 300,
    "df_records": 86400,
}


def get_cached_records(
    server_tools: ServerTools,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    log.info("start 'get_cached_records' method")
    try:
        if _is_record_cache_valid():
            log.debug(f"returning cache DataFrame (< {_RECORD_CACHE_TTL}s)")
            return _get_record_cache_dataframes()

        with _df_cache_record_lock:
            if _is_record_cache_valid():
                log.debug("returning cache DataFrame after waiting for refresh")
                return _get_record_cache_dataframes()

            log.debug("generate new DataFrame")
            df_records, df_annual = get_dataframes(server_tools)
            _df_cache_record["df_records"] = df_records
            _df_cache_record["df_annual"] = df_annual
            _df_cache_record["graph_html"] = {}
            _df_cache_record["timestamp"] = dt.datetime.now()
            return df_records, df_annual
    finally:
        log.info("end 'get_cached_records' method")


def _is_record_cache_valid() -> bool:
    if not _df_cache_record:
        return False
    now = dt.datetime.now()
    cache_life_time = (
        now - _df_cache_record.get("timestamp", now)
    ).total_seconds()
    return cache_life_time < _RECORD_CACHE_TTL


def _get_record_cache_dataframes() -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        pd.DataFrame(_df_cache_record.get("df_records")),
        pd.DataFrame(_df_cache_record.get("df_annual")),
    )


def _get_cached_graph(
    cache: dict,
    lock: threading.Lock,
    key: tuple[Any, ...],
    generator: Callable[[], Any],
) -> Any:
    """同じデータスナップショットから生成したグラフHTMLを再利用する。"""
    with lock:
        graph_html = cache.setdefault("graph_html", {})
        if key not in graph_html:
            graph_html[key] = generator()
        return graph_html[key]


def _clear_record_cache() -> None:
    """支出データと、それを元にしたグラフHTMLを破棄する。"""
    with _df_cache_record_lock:
        _df_cache_record.clear()


def get_cached_asset_table(
    asset_manager: AssetManager,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    log.info("start 'get_cached_asset_table' method")
    try:
        expired_keys = _get_expired_asset_cache_keys()
        if not expired_keys:
            log.debug("returning asset cache")
            return _get_asset_cache_dataframes()

        # Prevent concurrent requests from refreshing the same snapshot.
        with _df_cache_asset_table_lock:
            expired_keys = _get_expired_asset_cache_keys()
            if not expired_keys:
                log.debug("returning asset cache after waiting for refresh")
                return _get_asset_cache_dataframes()

            log.debug(f"refreshing asset data: {expired_keys}")
            data = asset_manager.get_asset_data(set(expired_keys))
            refreshed_at = dt.datetime.now()
            for key, dataframe in data.items():
                _df_cache_asset_table[key] = dataframe
                _df_cache_asset_table[f"{key}_timestamp"] = refreshed_at
            _df_cache_asset_table["graph_html"] = {}
            return _get_asset_cache_dataframes()
    finally:
        log.info("end 'get_cached_asset_table' method")


def _get_expired_asset_cache_keys() -> list[str]:
    now = dt.datetime.now()
    return [
        key
        for key, ttl in _ASSET_CACHE_TTL.items()
        if key not in _df_cache_asset_table
        or (
            now - _df_cache_asset_table.get(f"{key}_timestamp", now)
        ).total_seconds()
        >= ttl
    ]


def _get_asset_cache_dataframes() -> (
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]
):
    df_summary = pd.DataFrame(_df_cache_asset_table.get("df_summary"))
    df_items = pd.DataFrame(_df_cache_asset_table.get("df_items"))
    df_records = pd.DataFrame(_df_cache_asset_table.get("df_records"))
    df_stock = pd.DataFrame(_df_cache_asset_table.get("df_stock"))
    df_jpy = df_items.query("ticker=='現金(日本円)'")
    df_stock = pd.concat(
        [
            df_stock,
            pd.DataFrame(
                dict(
                    ticker=["JPY"],
                    price=[pd.NA],
                    change_pct=[0],
                    change_pct_weekly=[0],
                    change_pct_monthly=[0],
                    drawdown=[0],
                    change_pct_yen=[0],
                    change_yen=[0],
                    valuation=[df_jpy["valuation"].iloc[0]],
                    profit=[0],
                    roi=[0],
                )
            ),
        ]
    )
    df_stock.index = range(1, len(df_stock) + 1)
    return df_summary, df_items, df_records, df_stock


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


def build_asset_summary_dict(
    df_summary: pd.DataFrame, df_items: pd.DataFrame, df_stock: pd.DataFrame
) -> dict:
    df_usdjpy = df_stock.query("ticker == 'USDJPY'")
    if df_usdjpy.empty:
        usdjpy_chg = 0
    else:
        usdjpy_chg = df_usdjpy["change_pct"].iloc[0]
    summary_list = df_summary.to_dict(orient="records")
    if not len(summary_list):
        return {}
    summary = summary_list[0]
    summary["total"] = f"¥{df_items['valuation'].sum():,.0f}"
    summary["change"] = (
        f" {'+' if summary['change_jpy'] >= 0 else '-'}¥{abs(summary['change_jpy']):,.0f}"
        + f" ( {'+' if summary['change_pct'] >= 0 else '-'}{abs(summary['change_pct']):,.2f}% )"
    )
    summary["drawdown"] = f"{summary['drawdown']:,.2f}%"
    summary["usdjpy"] = f"¥{summary['usdjpy']:,.2f}"
    summary["change_usdjpy"] = (
        f"{'+' if usdjpy_chg >= 0 else '-'}{abs(usdjpy_chg):,.2f}%"
    )
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
    return summary


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
    df_summary, df_items, df_records, df_stock = get_cached_asset_table(
        asset_manager
    )
    summary = build_asset_summary_dict(df_summary, df_items, df_stock)
    items = df_items.to_dict(orient="records")
    allocation_config = server_tools.config.get("asset_management", {}).get(
        "allocation", {}
    )
    target_weights = allocation_config.get("target_weights", {})
    tolerance_percent = allocation_config.get("tolerance_percent", 0.0)
    asset_allocation = asset_manager.build_asset_allocation(
        df_items, target_weights, tolerance_percent
    )
    allocation_adjustments = [
        allocation["ticker"]
        for allocation in asset_allocation
        if allocation["action"] != "調整不要"
    ]
    asset_tickers = [
        t for t in df_stock["ticker"].dropna().unique().tolist() if t != "JPY"
    ]
    asset_tickers.append("VIX")
    asset_tickers.append("High Yield Spread")
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
            "asset_allocation": asset_allocation,
            "allocation_adjustments": allocation_adjustments,
            "allocation_tolerance_percent": tolerance_percent,
            "asset_tickers": asset_tickers,
            "plotlyjs": plotlyjs,
        },
    )


def get_simulation_averages(
    records: list[dict],
    income_types: list[str],
    exclude_types: list[str],
    today: dt.date,
    average_months: int,
) -> tuple[int, int, int]:
    """今月を除く直近Nカ月の月次収支平均を万円で返す"""
    months = max(1, average_months)
    month_totals: dict[str, list[int]] = {}
    for offset in range(1, months + 1):
        month = today.replace(day=1)
        month -= dt.timedelta(days=month.day)
        for _ in range(offset - 1):
            month = month.replace(day=1) - dt.timedelta(days=1)
        month_totals[month.strftime("%Y-%m")] = [0, 0]

    for record in records:
        record_date = str(record.get("date", ""))[:10]
        month_key = record_date[:7]
        if month_key not in month_totals:
            continue
        amount = int(record.get("expense_amount", 0))
        if record.get("expense_type") in income_types:
            month_totals[month_key][0] += amount
        elif record.get("expense_type") not in exclude_types:
            month_totals[month_key][1] += amount

    income_average_man_yen = round(
        sum(v[0] for v in month_totals.values()) / months / 10000
    )
    expense_average_man_yen = round(
        sum(v[1] for v in month_totals.values()) / months / 10000
    )
    surplus_average_man_yen = max(
        0, income_average_man_yen - expense_average_man_yen
    )
    return (
        income_average_man_yen,
        expense_average_man_yen,
        surplus_average_man_yen,
    )


@app.get("/simulator", response_class=HTMLResponse)
def simulator(
    request: Request,
    status: bool | None = None,
    msg: str | None = None,
    info: str | None = None,
) -> HTMLResponse:
    """
    独立後シミュレーターページ
    """
    log.info("start 'simulator' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    commons = server_tools.generate_commons(request)
    _, df_items, _, _ = get_cached_asset_table(asset_manager)

    current_assets_val = df_items["valuation"].sum()
    current_assets_man_yen = int(current_assets_val / 10000)
    simulation_config = server_tools.config.get("simulation", {})
    average_months = int(simulation_config.get("average_months", 3))
    (
        average_income_man_yen,
        average_expense_man_yen,
        average_surplus_man_yen,
    ) = get_simulation_averages(
        commons["records"],
        server_tools.income_types,
        server_tools.exclude_types,
        dt.date.today(),
        average_months,
    )
    log.info("end 'simulator' method")
    return server_tools.templates.TemplateResponse(
        "simulator.j2",
        {
            "request": request,
            "status": status,
            "msg": msg,
            "info": info,
            "current_assets_man_yen": current_assets_man_yen,
            "average_months": max(1, average_months),
            "average_income_man_yen": average_income_man_yen,
            "average_expense_man_yen": average_expense_man_yen,
            "average_surplus_man_yen": average_surplus_man_yen,
            **commons,
        },
    )


def get_dataframes(
    server_tools: ServerTools,
) -> tuple[pd.DataFrame, pd.DataFrame]:
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
            "expense_type not in @server_tools.exclude_types"
        ).copy()
        df_records["date"] = pd.to_datetime(
            df_records["date"].map(lambda s: re.sub(r"[^\d\-]+", "", str(s))),
            errors="coerce",
        )
        df_records.dropna(subset=["date"], inplace=True)
    df_annual = server_tools.gspread_handler.get_annual_fiscal_table()
    log.info("end 'get_dataframes' method")
    return df_records, df_annual


@app.get("/api/pie_chart", response_class=JSONResponse)
def get_pie_chart(request: Request, month: str | None = None) -> JSONResponse:
    log.info("start 'get_pie_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records, _ = get_cached_records(server_tools)
    graph_html, available_months = _get_cached_graph(
        _df_cache_record,
        _df_cache_record_lock,
        ("pie", theme, month or ""),
        lambda: server_tools.graph_generator.generate_pie_chart(
            server_tools.graph_generator.generate_monthly_df(df_records),
            df_records,
            target_month=month,
            theme=theme,
            include_plotlyjs=False,
        ),
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
    df_records, _ = get_cached_records(server_tools)
    graph_html, available_months = _get_cached_graph(
        _df_cache_record,
        _df_cache_record_lock,
        ("daily", theme, month or ""),
        lambda: server_tools.graph_generator.generate_daily_chart(
            df_records,
            target_month=month,
            theme=theme,
            include_plotlyjs=False,
        ),
    )
    log.info("end 'get_daily_chart' method")
    return JSONResponse(
        content={"html": graph_html, "months": available_months}
    )


@app.get("/api/bar_chart", response_class=HTMLResponse)
def get_monthly_bar_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_monthly_bar_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records, _ = get_cached_records(server_tools)
    graph_html = _get_cached_graph(
        _df_cache_record,
        _df_cache_record_lock,
        ("bar", theme),
        lambda: server_tools.graph_generator.generate_monthly_bar_chart(
            server_tools.graph_generator.generate_monthly_df(df_records),
            theme=theme,
            include_plotlyjs=False,
        ),
    )
    log.info("end 'get_monthly_bar_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/annual_fiscal_report_chart", response_class=JSONResponse)
def get_annual_fiscal_report_chart(
    request: Request, year: str | None = None
) -> JSONResponse:
    log.info("start 'get_annual_fiscal_report_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records, _ = get_cached_records(server_tools)
    graph_html, available_years = _get_cached_graph(
        _df_cache_record,
        _df_cache_record_lock,
        ("annual_fiscal_report", theme, year or ""),
        lambda: server_tools.graph_generator.generate_annual_fiscal_report_chart(
            df_records, target_year=year, theme=theme, include_plotlyjs=False
        ),
    )
    log.info("end 'get_annual_fiscal_report_chart' method")
    return JSONResponse(content={"html": graph_html, "years": available_years})


@app.get("/api/fiscal_asset_history_chart", response_class=JSONResponse)
def get_fiscal_asset_history_chart(
    request: Request, year: str | None = None
) -> JSONResponse:
    log.info("start 'get_fiscal_asset_history_chart' method")
    server_tools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_records, _ = get_cached_records(server_tools)
    graph_html, available_years = _get_cached_graph(
        _df_cache_record,
        _df_cache_record_lock,
        ("fiscal_asset_history", theme, year or ""),
        lambda: server_tools.graph_generator.generate_fiscal_asset_history_chart(
            df_records,
            target_year=year,
            theme=theme,
            include_plotlyjs=False,
        ),
    )
    log.info("end 'get_fiscal_asset_history_chart' method")
    return JSONResponse(content={"html": graph_html, "years": available_years})


@app.get("/api/asset_summary", response_class=HTMLResponse)
def get_asset_summary(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_summary' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    df_summary, df_items, _, df_stock = get_cached_asset_table(asset_manager)
    summary = build_asset_summary_dict(df_summary, df_items, df_stock)
    log.info("end 'get_asset_summary' method")
    return server_tools.templates.TemplateResponse(
        "asset_summary_content.j2",
        {
            "request": request,
            "icons": server_tools.icons,
            "today": dt.datetime.today(),
            "asset_summary": summary,
        },
    )


@app.get("/api/asset_pie_chart", response_class=HTMLResponse)
def get_asset_pie_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_pie_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records, df_stock = get_cached_asset_table(
        asset_manager
    )
    graph_html = _get_cached_graph(
        _df_cache_asset_table,
        _df_cache_asset_table_lock,
        ("asset_pie", theme),
        lambda: server_tools.graph_generator.generate_asset_pie_chart(
            df_items,
            theme=theme,
            include_plotlyjs=False,
        ),
    )
    log.info("end 'get_asset_pie_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/asset_waterfall_chart", response_class=HTMLResponse)
def get_asset_waterfall_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_waterfall_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records, df_stock = get_cached_asset_table(
        asset_manager
    )
    graph_html = _get_cached_graph(
        _df_cache_asset_table,
        _df_cache_asset_table_lock,
        ("asset_waterfall", theme),
        lambda: server_tools.graph_generator.generate_asset_waterfall_chart(
            df_items, theme=theme, include_plotlyjs=False
        ),
    )
    log.info("end 'get_asset_waterfall_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/asset_heatmap_chart", response_class=HTMLResponse)
def get_asset_heatmap_chart(request: Request) -> HTMLResponse:
    log.info("start 'get_asset_heatmap_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records, df_stock = get_cached_asset_table(
        asset_manager
    )
    graph_html = _get_cached_graph(
        _df_cache_asset_table,
        _df_cache_asset_table_lock,
        ("asset_heatmap", theme),
        lambda: server_tools.graph_generator.generate_asset_heatmap_chart(
            df_stock,
            total_value=int(df_items["valuation"].sum()),
            total_change_pct=df_summary["change_pct"].iloc[0],
            theme=theme,
            include_plotlyjs=False,
        ),
    )
    log.info("end 'get_asset_heatmap_chart' method")
    return HTMLResponse(content=graph_html)


@app.get("/api/asset_monthly_history_chart", response_class=HTMLResponse)
def get_asset_monthly_history_chart(
    request: Request,
    annual_yield: float = 0.0,
    monthly_investment: float = 0.0,
    duration_years: float = 0,
) -> HTMLResponse:
    log.info("start 'get_asset_monthly_history_chart' method")
    server_tools: ServerTools = ServerTools(app, gspread_handler)
    theme = request.cookies.get("theme", "light")
    df_summary, df_items, df_records, df_stock = get_cached_asset_table(
        asset_manager
    )
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
    graph_html = _get_cached_graph(
        _df_cache_asset_table,
        _df_cache_asset_table_lock,
        (
            "asset_monthly_history",
            theme,
            dt.date.today(),
            annual_yield,
            monthly_investment,
            duration_years,
        ),
        lambda: server_tools.graph_generator.generate_asset_monthly_history_chart(
            df_records,
            theme=theme,
            include_plotlyjs=False,
            simulation_annual_yield=annual_yield,
            simulation_monthly_investment=monthly_investment,
            simulation_years=duration_years,
        ),
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
            try:
                server_tools.gspread_handler.register_expense(
                    expense_type, expense_amount_num, expense_memo, expense_date
                )
                server_tools.expense_handler.store_expense(
                    expense_type, expense_memo, expense_amount_num, expense_date
                )
            finally:
                _clear_record_cache()
            msg = "✅ 家計簿への登録が完了しました。"
            info = (
                f"[{expense_date}] "
                f"{expense_type}: "
                f"¥{expense_amount_num:,}"
                f"{' -  '+expense_memo if expense_memo else ''}"
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
                f"{' -  '+expense_memo if expense_memo else ''}"
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
                try:
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
                finally:
                    _clear_record_cache()
                msg = "✅ 家計簿への登録が完了しました。"
                info = (
                    f"[{expense_date}] "
                    f"{expense_type}: "
                    f"¥{expense_amount:,}"
                    f"{' -  '+expense_memo if expense_memo else ''}"
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

        if status:
            try:
                if not server_tools.gspread_handler.delete_expense(
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
            finally:
                _clear_record_cache()
        if status:
            msg = "✅ 家計簿の削除処理が完了しました。"
        else:
            msg = "🚫 家計簿の削除処理に失敗しました。"
        info = (
            f"[{expense_date}] "
            f"{expense_type}: "
            f"¥{expense_amount:,}"
            f"{' -  '+expense_memo if expense_memo else ''}"
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
            try:
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
            finally:
                _clear_record_cache()
            if status:
                msg = "✅ 家計簿の修正処理が完了しました。"
            else:
                msg = "🚫 家計簿の修正処理に失敗しました。"
            info = (
                f"[{target_date}] "
                f"{target_type}: "
                f"¥{target_amount:,}"
                f"{' -  '+target_memo if target_memo else ''}"
                " ▶ "
                f"[{new_expense_date}] "
                f"{new_expense_type}: "
                f"¥{new_expense_amount:,}"
                f"{' -  '+new_expense_memo if new_expense_memo else ''}"
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
