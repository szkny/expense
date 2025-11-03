import io
import os
import re
import base64
import logging
import pandas as pd
import datetime as dt
from typing import Any
from markupsafe import Markup, escape

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..core.base import Base
from ..core.expense import Expense, get_fiscal_year
from ..core.gspread_wrapper import GspreadHandler
from ..core.ocr import get_latest_screenshot
from ..core.termux_api import TermuxAPI
from .graph_generator import GraphGenerator

log: logging.Logger = logging.getLogger("expense")


class ServerTools(Base):
    def __init__(self, app: FastAPI, gspread_handler: GspreadHandler) -> None:
        super().__init__()
        expense_config: dict[str, Any] = self.config.get("expense", {})
        expense_types_all: dict[str, list] = expense_config.get(
            "expense_types", {}
        )
        self.income_types: list[str] = expense_types_all.get("income", [])
        self.fixed_types: list[str] = expense_types_all.get("fixed", [])
        self.variable_types: list[str] = expense_types_all.get("variable", [])
        self.expense_types: list[str] = (
            self.variable_types + self.fixed_types + self.income_types
        )
        self.exclude_types: list[str] = expense_config.get("exclude_types", [])
        webui_config: dict[str, Any] = self.config.get("web_ui", {})
        self.icons: dict[str, str] = webui_config.get("icons", {})
        self.icons = self.icons | expense_config.get("icons", {})
        graph_config: dict[str, dict[str, str]] = webui_config.get("graph", {})

        self.expense_handler = Expense()
        self.gspread_handler: GspreadHandler = gspread_handler
        self.gspread_url: str = self.gspread_handler.get_spreadsheet_url()
        self.termux_api: TermuxAPI = TermuxAPI()

        self.graph_generator = GraphGenerator(
            expense_types=self.expense_types,
            variable_types=self.variable_types,
            exclude_types=self.exclude_types,
            graph_config=graph_config,
        )

        # setup FastAPI
        app.mount(
            "/static",
            StaticFiles(directory="src/expense/static"),
            name="static",
        )
        self.templates = Jinja2Templates(directory="src/expense/templates")
        self.templates.env.filters["info_to_html"] = self.info_to_html

    def info_to_html(self, info: str) -> Markup:
        """
        「 ▶ 」を安全に改行＋▼ブロックに変換
        info内のHTMLはすべてエスケープする（XSS対策）
        """
        # HTMLエスケープ
        escaped = escape(info)
        # 置換対象をマークアップ安全なタグで置換
        html = escaped.replace(
            " ▶ ", Markup("<br><div class='msg-arrow'>▼</div><br>")
        )
        return Markup(html)

    def generate_items(self) -> list[str]:
        """
        インスタント登録用のアイテムを生成
        """
        log.info("start 'generate_items' method")
        items = []
        try:
            favorite_expenses = self.expense_handler.get_favorite_expenses()
        except Exception:
            favorite_expenses = []
        expense_config: dict[str, Any] = self.config.get("expense", {})
        num_items: dict[str, int] = expense_config.get("num_instant_items", {})
        try:
            frequent_expenses = self.expense_handler.get_frequent_expenses(30)
        except Exception:
            frequent_expenses = []
        try:
            recent_expenses = self.expense_handler.get_recent_expenses(30)
        except Exception:
            recent_expenses = []
        if expense_config.get("filter_duplicated_items", True):
            (
                favorite_expenses,
                recent_expenses,
                frequent_expenses,
            ) = self.expense_handler.filter_duplicates(
                [
                    favorite_expenses,
                    recent_expenses,
                    frequent_expenses,
                ]
            )
        item_list = [
            {"icon": self.icons.get("favorite"), "items": favorite_expenses},
            {
                "icon": self.icons.get("frequent"),
                "items": frequent_expenses[: int(num_items.get("frequent", 5))],
            },
            {
                "icon": self.icons.get("recent"),
                "items": recent_expenses[: int(num_items.get("recent", 5))],
            },
        ]
        for item_data in item_list:
            icon: str = item_data.get("icon", "")
            for i in item_data.get("items", []):
                item_str = f'{icon} {i["expense_type"]}/{i["expense_memo"]}/¥{i["expense_amount"]}'
                item_str = item_str.replace("//", "/")
                items.append(item_str)
        items += self.expense_types
        log.info("end 'generate_items' method")
        return items

    def generate_report_summary(self, df: pd.DataFrame) -> dict[str, Any]:
        """
        レポートのサマリーを生成
        """
        log.info("start 'generate_report_summary' method")
        t = dt.datetime.today()
        today_str = t.date().isoformat()
        month_start = dt.date(t.year, t.month, 1).isoformat()
        prev_month_start = dt.date(
            t.year if t.month > 1 else t.year - 1,
            t.month - 1 if t.month > 1 else 12,
            1,
        ).isoformat()
        prev_month_end = (
            dt.date(t.year, t.month, 1) - dt.timedelta(days=1)
        ).isoformat()

        def calc_total(start: str, end: str | None = None) -> int:
            operator = ">=" if end else "=="
            condition1 = f"date {operator} @pd.Timestamp('{start}')"
            condition2 = f" and date <= @pd.Timestamp('{end}')" if end else ""
            return int(
                df.query(condition1 + condition2).loc[:, "expense_amount"].sum()
            )

        today_total = calc_total(today_str)
        monthly_total = calc_total(month_start, today_str)
        prev_monthly_total = calc_total(prev_month_start, prev_month_end)
        log.info("end 'generate_report_summary' method")
        return {
            "today_total": today_total,
            "monthly_total": monthly_total,
            "prev_monthly_total": prev_monthly_total,
        }

    def generate_commons(self, request: Request) -> dict[str, Any]:
        """
        テンプレートに渡す共通データを生成
        """
        log.info("start 'generate_commons' method")

        # テーマを取得
        theme = request.cookies.get("theme", "light")

        expense_date_range = (
            dt.date(get_fiscal_year(), 4, 1).isoformat(),
            dt.date(get_fiscal_year() + 1, 3, 31).isoformat(),
        )

        # 最新のスクリーンショットを取得してBase64エンコード
        try:
            screenshot_name = get_latest_screenshot()
            if screenshot_name:
                buf = io.BytesIO()
                with open(screenshot_name, "rb") as f:
                    buf.write(f.read())
                buf.seek(0)
                img_base64 = base64.b64encode(buf.read()).decode("utf-8")
                # 最新のOCRデータを取得して、最新のスクリーンショットと同じならOCR登録済みとみなす
                latest_ocr_data = self.expense_handler.get_ocr_expense()
                disable_ocr = len(latest_ocr_data) and (
                    latest_ocr_data.get("screenshot_name", "")
                    == os.path.basename(screenshot_name)
                )
            else:
                img_base64 = ""
                disable_ocr = True
        except Exception:
            log.exception("Error occurred in screenshot process.")
            screenshot_name = ""
            img_base64 = ""
            disable_ocr = True

        # インスタント登録用のアイテムを取得
        items = self.generate_items()

        # 最近の支出履歴を取得
        max_n_records = (
            self.config.get("web_ui", {})
            .get("record_table", {})
            .get("max_n_records", 5000)
        )
        try:
            recent_expenses = self.expense_handler.get_recent_expenses(
                max_n_records, drop_duplicates=False, with_date=True
            )
        except Exception:
            recent_expenses = []
        n_records = len(recent_expenses)

        # 支出レポートを計算
        df_records = pd.DataFrame(recent_expenses)
        if not df_records.empty:
            df_records = df_records.query(
                "expense_type not in @self.income_types and expense_type not in @self.exclude_types"
            )
            df_records.loc[:, "date"] = pd.to_datetime(
                df_records.loc[:, "date"].map(
                    lambda s: re.sub(r"[^\d\-]+", "", str(s))
                )
            )
            report_summary = self.generate_report_summary(df_records)
        else:
            report_summary = {
                "today_total": 0,
                "monthly_total": 0,
                "prev_monthly_total": 0,
            }

        # Plotly.js
        plotlyjs = self.graph_generator.get_plotlyjs()

        log.info("end 'generate_commons' method")
        return {
            "icons": self.icons,
            "theme": theme,
            "expense_date_range": expense_date_range,
            "n_records": n_records,
            "gspread_url": self.gspread_url,
            "items": items,
            "records": recent_expenses,
            "screenshot_name": screenshot_name,
            "screenshot_base64": img_base64,
            "disable_ocr": disable_ocr,
            "today": dt.datetime.today().date().isoformat(),
            "plotlyjs": plotlyjs,
            **report_summary,
        }
