import re
import io
import os
import json
import base64
import logging
import pandas as pd
import datetime as dt
from typing import Any

from plotly import express as px
from plotly import graph_objects as go

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse

from ..core.base import Base
from ..core.termux_api import TermuxAPI
from ..core.gspread_wrapper import GspreadHandler
from ..core.ocr import Ocr, get_latest_screenshot
from ..core.expense import Expense, get_fiscal_year

app: FastAPI = FastAPI()
log: logging.Logger = logging.getLogger("expense")


class ServerTools(Base):
    def __init__(self):
        super().__init__()
        expense_config: dict[str, Any] = self.config.get("expense", {})
        expense_types_all: dict[str, list] = expense_config.get(
            "expense_types", {}
        )
        income_types: list[str] = expense_types_all.get("income", [])
        fixed_types: list[str] = expense_types_all.get("fixed", [])
        variable_types: list[str] = expense_types_all.get("variable", [])
        self.expense_types: list[str] = (
            variable_types + fixed_types + income_types
        )
        self.exclude_types: list[str] = expense_config.get("exclude_types", [])
        self.icons: dict[str, str] = self.config.get("web_ui", {}).get(
            "icons", {}
        ) | expense_config.get("icons", {})

        self.expense_handler = Expense()
        self.gspread_handler: GspreadHandler = GspreadHandler(
            f"CF ({get_fiscal_year()}年度)"
        )
        self.gspread_url: str = self.gspread_handler.get_spreadsheet_url()
        self.termux_api: TermuxAPI = TermuxAPI()

        # setup FastAPI
        app.mount(
            "/static",
            StaticFiles(directory="src/expense/static"),
            name="static",
        )
        self.templates = Jinja2Templates(directory="src/expense/templates")

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
        try:
            frequent_expenses = self.expense_handler.get_frequent_expenses(8)
        except Exception:
            frequent_expenses = []
        try:
            recent_expenses = self.expense_handler.get_recent_expenses(8)
        except Exception:
            recent_expenses = []
        (
            favorite_expenses,
            frequent_expenses,
            recent_expenses,
        ) = self.expense_handler.filter_duplicates(
            [
                favorite_expenses,
                frequent_expenses,
                recent_expenses,
            ]
        )
        item_list = [
            {"icon": self.icons.get("favorite"), "items": favorite_expenses},
            {"icon": self.icons.get("frequent"), "items": frequent_expenses},
            {"icon": self.icons.get("recent"), "items": recent_expenses},
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

        def calc_total(start: str, end: str = None) -> int:
            operator = ">=" if end else "=="
            condition1 = f"date {operator} @pd.Timestamp('{start}')"
            condition2 = f" and date <= @pd.Timestamp('{end}')" if end else ""
            return (
                df.query(condition1 + condition2).loc[:, "expense_amount"].sum()
            )

        today_total = calc_total(today_str)
        monthly_total = calc_total(month_start, today_str)
        prev_monthly_total = calc_total(prev_month_start, month_start)
        log.info("end 'generate_report_summary' method")
        return {
            "today_total": today_total,
            "monthly_total": monthly_total,
            "prev_monthly_total": prev_monthly_total,
        }

    def generate_monthly_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        月別のDataFrameを生成
        """
        log.info("start 'generate_monthly_df' method")
        df_new = df.copy()
        df_new.loc[:, "date"] = pd.to_datetime(df_new.loc[:, "date"])
        df_new.loc[:, "month"] = pd.to_datetime(
            df_new.loc[:, "date"]
        ).dt.strftime("%Y-%m")
        df_ref = df_new.copy()
        df_new = (
            df_new.groupby(["month", "expense_type"])["expense_amount"]
            .sum()
            .reset_index()
        )
        # extract memos for hover text of monthly chart
        df_new = self._add_expense_memo_summary(df_new, df_ref, "month")
        log.info("end 'generate_monthly_df' method")
        return df_new

    def _add_expense_memo_summary(
        self,
        df: pd.DataFrame,
        df_ref: pd.DataFrame,
        date_or_month: str,
        len_memo_text: int = 50,
    ) -> pd.DataFrame:
        for i, r in df.iterrows():
            key = r[date_or_month]
            expense_type = r["expense_type"]
            condition = f"expense_type=='{expense_type}' and "
            condition += (
                f"date==@pd.Timestamp('{key}')"
                if date_or_month == "date"
                else f"month=='{key}'"
            )
            _data = df_ref.query(condition)
            n_memo = _data["expense_memo"].value_counts()
            _data = (
                _data.groupby(["expense_memo"])["expense_amount"]
                .sum()
                .reset_index()
            ).sort_values("expense_amount")
            _add_memo = ""
            for memo in _data["expense_memo"].iloc[::-1]:
                if memo in _add_memo:
                    continue
                n = n_memo[memo]
                if n > 1:
                    memo += f" ×{n}"
                if len(_add_memo + memo) > len_memo_text:
                    _add_memo += ", ⋯"
                    break
                if len(memo) > 0:
                    _add_memo += ",<br>" + memo if len(_add_memo) else memo
            df.loc[i, "expense_memo"] = _add_memo
        return df

    def generate_daily_chart(
        self, df: pd.DataFrame, theme: str = "light", min_yrange: int = 50000
    ) -> str:
        """
        累積折れ線グラフを生成
        """
        log.info("start 'generate_daily_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return ""
        t = dt.datetime.today()
        month_start, month_end = self._get_month_boundaries(t)
        df_graph = self._prepare_graph_dataframe(df, month_start, month_end)
        df_bar = self._prepare_bar_dataframe(df_graph)
        df_graph = self._add_month_start_point(df_graph, month_start)
        df_graph, df_predict = self._handle_predictions(
            df_graph, t, month_start, month_end
        )
        fig_bar = self._create_bar_figure(
            df_bar, month_start, month_end, min_yrange, df_graph, df_predict
        )
        fig_line = self._create_line_figure(df_graph, theme)
        fig_predict = self._create_prediction_figure(df_predict, theme)
        self._update_traces(fig_bar, fig_line, fig_predict)
        self._update_layout(fig_bar, theme)
        fig_bar.add_traces(fig_line.data)
        fig_bar.add_traces(fig_predict.data)
        self._add_bar_chart_labels(fig_bar, df_bar, "date", theme, fontsize=10)
        graph_html = fig_bar.to_html(full_html=False)
        log.info("end 'generate_daily_chart' method")
        return graph_html

    def _get_month_boundaries(self, t: dt.datetime) -> tuple[str, str]:
        month_start = dt.date(t.year, t.month, 1).isoformat()
        month_end = (
            dt.date(
                t.year if t.month < 12 else t.year + 1,
                t.month + 1 if t.month < 12 else 1,
                1,
            )
            - dt.timedelta(days=1)
        ).isoformat()
        return month_start, month_end

    def _prepare_graph_dataframe(
        self, df: pd.DataFrame, month_start: str, month_end: str
    ) -> pd.DataFrame:
        df_graph = df.copy()
        df_graph = df_graph.query("expense_type not in @self.exclude_types")
        df_graph["date"] = pd.to_datetime(df_graph["date"])
        df_graph = df_graph.query(
            f"date >= @pd.Timestamp('{month_start}') and date <= @pd.Timestamp('{month_end}')"
        )
        df_graph = df_graph.sort_values("date")
        df_graph["cumsum"] = df_graph["expense_amount"].cumsum()
        return df_graph

    def _prepare_bar_dataframe(self, df_graph: pd.DataFrame) -> pd.DataFrame:
        df_graph = df_graph.sort_values(
            ["date", "expense_type", "expense_amount"]
        )
        df_bar = (
            df_graph.groupby(["date", "expense_type"])["expense_amount"]
            .sum()
            .reset_index()
        )
        df_bar.index = pd.Index(range(len(df_bar)))
        # extract memos for hover text of bar chart
        df_bar = self._add_expense_memo_summary(df_bar, df_graph, "date")
        # add offset to `date` column
        df_bar["date"] = pd.to_datetime(df_bar["date"]) + pd.Timedelta(hours=12)
        return df_bar

    def _add_month_start_point(
        self, df_graph: pd.DataFrame, month_start: str
    ) -> pd.DataFrame:
        if pd.to_datetime(month_start) < df_graph["date"].iloc[0]:
            df_graph = pd.concat(
                [
                    pd.DataFrame(
                        {
                            "date": [pd.to_datetime(month_start)],
                            "cumsum": [0],
                        }
                    ),
                    df_graph,
                ],
                ignore_index=True,
            )
        return df_graph

    def _handle_predictions(
        self,
        df_graph: pd.DataFrame,
        t: dt.datetime,
        month_start: str,
        month_end: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        latest_date = df_graph.iloc[-1]["date"]
        latest_date = t if t > latest_date else latest_date
        if latest_date < pd.to_datetime(month_end):
            df_graph = pd.concat(
                [
                    df_graph,
                    pd.DataFrame(
                        {
                            "date": [pd.to_datetime(month_end)],
                            "cumsum": [df_graph["cumsum"].iloc[-1]],
                        }
                    ),
                ],
                ignore_index=True,
            )
            total_monthly_expense = df_graph["expense_amount"].sum()
            days_passed = (
                pd.to_datetime(latest_date.date()) - pd.to_datetime(month_start)
            ).days + 1
            df_predict = pd.DataFrame(
                {
                    "date": [
                        pd.to_datetime(month_start),
                        pd.to_datetime(month_end),
                    ],
                    "predict": [
                        0,
                        df_graph["cumsum"].iloc[-1]
                        + (
                            pd.to_datetime(month_end)
                            - pd.to_datetime(latest_date.date())
                        ).days
                        * total_monthly_expense
                        / days_passed,
                    ],
                }
            )
        else:
            df_predict = pd.DataFrame(columns=["date", "predict"])
        return df_graph, df_predict

    def _create_bar_figure(
        self,
        df_bar: pd.DataFrame,
        month_start: str,
        month_end: str,
        min_yrange: int,
        df_graph: pd.DataFrame,
        df_predict: pd.DataFrame,
    ) -> px.bar:
        month_str = pd.Timestamp(month_start).strftime("%Y年%-m月")
        return px.bar(
            df_bar,
            x="date",
            y="expense_amount",
            color="expense_type",
            title=f"支出内訳 日別（{month_str}）",
            hover_data=["expense_memo"],
            category_orders={"expense_type": self.expense_types},
            barmode="stack",
            range_x=[
                pd.Timestamp(month_start),
                pd.Timestamp(month_end),
            ],
            range_y=[
                0,
                max(
                    min_yrange,
                    df_graph["cumsum"].max() * 1.2,
                    df_predict["predict"].max() * 1.2,
                ),
            ],
        )

    def _create_line_figure(
        self, df_graph: pd.DataFrame, theme: str
    ) -> px.line:
        return px.line(
            df_graph,
            x="date",
            y="cumsum",
            line_shape="hv",
            color_discrete_sequence=[
                "#3b82f6" if theme == "dark" else "#223377"
            ],
        )

    def _create_prediction_figure(
        self, df_predict: pd.DataFrame, theme: str
    ) -> px.line:
        return px.line(
            df_predict,
            x="date",
            y="predict",
            color_discrete_sequence=[
                "#dd4433" if theme == "dark" else "#ff5544"
            ],
        )

    def _add_bar_chart_labels(
        self,
        fig: px.bar,
        df_bar: pd.DataFrame,
        key: str,
        theme: str,
        fontsize: int = 14,
        threshold: int = 2000,
        label_offset: int = 3000,
    ) -> None:
        totals = df_bar.groupby(key, as_index=False)["expense_amount"].sum()
        totals["label"] = totals["expense_amount"].map(
            lambda x: f"¥{x:,}" if x >= threshold else ""
        )
        y = [
            j if (i + 1) % 2 else j + label_offset
            for i, j in enumerate(totals["expense_amount"])
        ]
        fig.add_trace(
            go.Scatter(
                x=totals[key],
                y=y,
                text=totals["label"],
                mode="text",
                textposition="top center",
                textfont=dict(
                    size=fontsize,
                    weight="bold",
                    color="#ffffff" if theme == "dark" else "#000000",
                ),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    def _update_traces(
        self, fig_bar: px.bar, fig_line: px.line, fig_predict: px.line
    ) -> None:
        fig_bar.update_traces(
            hovertemplate="¥%{y:,.0f}<br>%{customdata[0]}",
            textfont=dict(size=14),
        )
        fig_line.update_traces(
            line=dict(dash="solid", width=1.5),
            hovertemplate="¥%{y:,.0f}",
        )
        fig_predict.update_traces(
            line=dict(dash="dot", width=1.5),
            hovertemplate="¥%{y:,.0f}",
        )

    def _update_layout(self, fig: go.Figure, theme: str) -> None:
        fig.update_layout(
            height=500,
            xaxis_title="",
            yaxis_title="金額(¥)",
            title_y=0.98,
            legend_title="",
            yaxis=dict(
                tickprefix="¥",
                tickformat=",",
                autorange=True,
            ),
            dragmode=False,
            legend=dict(orientation="h"),
            margin=dict(l=10, r=10, t=50, b=0),
            paper_bgcolor="#1f2937" if theme == "dark" else "#ffffff",
            plot_bgcolor="#1f2937" if theme == "dark" else "#ffffff",
            template="plotly_dark" if theme == "dark" else "plotly_white",
        )

    def generate_pie_chart(self, df: pd.DataFrame, theme: str = "light") -> str:
        """
        円グラフを生成
        """
        log.info("start 'generate_pie_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_pie = df.copy()
        df_pie = df_pie.loc[
            df_pie.loc[:, "month"] == dt.datetime.today().strftime("%Y-%m")
        ]
        month_str = pd.Timestamp(df_pie.iloc[-1]["month"]).strftime("%Y年%-m月")
        total_amount = df_pie["expense_amount"].sum()
        fig = px.pie(
            df_pie,
            names="expense_type",
            values="expense_amount",
            title=f"支出内訳（{month_str}）",
            hover_data=["expense_memo"],
            category_orders={"expense_type": self.expense_types},
            hole=0.4,
        )
        fig.update_traces(
            texttemplate="¥%{value:,} (%{percent})",
            hovertemplate="%{label}<br>¥%{value:,.0f}<br>%{customdata[0]}",
            textfont=dict(size=14),
        )
        fig.add_annotation(
            text=f"合計<br>¥{total_amount: ,.0f}",
            x=0.5,
            y=0.5,
            font_size=20,
            showarrow=False,
            font=dict(
                color="#ffffff" if theme == "dark" else "#000000", size=20
            ),
        )
        self._update_layout(fig, theme)
        graph_html = fig.to_html(full_html=False)
        log.info("end 'generate_pie_chart' method")
        return graph_html

    def generate_bar_chart(
        self, df: pd.DataFrame, theme: str = "light", max_monthes: int = 12
    ) -> str:
        """
        月別の棒グラフを生成
        """
        log.info("start 'generate_bar_chart' method")
        if df.empty:
            log.info("DataFrame is empty, skipping graph generation.")
            return ""
        df_graph = df.copy()
        df_graph.loc[:, "label"] = df_graph.loc[:, "expense_amount"].map(
            lambda x: f"¥{x:,}" if 10000 <= x else ""
        )
        df_graph["month"] = pd.to_datetime(df_graph["month"])
        cutoff_date = dt.datetime.today() - dt.timedelta(
            days=30 * (max_monthes - 1)
        )
        cutoff_date = cutoff_date.strftime("%Y-%m-01")
        df_graph = df_graph.query("month >= @pd.Timestamp(@cutoff_date)")
        df_graph["month"] = df_graph["month"].dt.strftime("%Y-%m")
        fig = px.bar(
            df_graph,
            x="month",
            y="expense_amount",
            color="expense_type",
            text="label",
            title="支出内訳（月別）",
            hover_data=["expense_memo"],
            range_y=[0, None],
            category_orders={"expense_type": self.expense_types},
        )
        fig.update_traces(
            hovertemplate="¥%{value:,.0f}<br>%{customdata[0]}",
            textfont=dict(size=14),
        )
        self._update_layout(fig, theme)
        self._add_bar_chart_labels(fig, df_graph, "month", theme, fontsize=14)
        graph_html = fig.to_html(full_html=False)
        log.info("end 'generate_bar_chart' method")
        return graph_html

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
        n_records = (
            self.config.get("web_ui", {})
            .get("record_table", {})
            .get("n_records", 200)
        )
        try:
            recent_expenses = self.expense_handler.get_recent_expenses(
                n_records, drop_duplicates=False, with_date=True
            )
        except Exception:
            recent_expenses = []

        # 支出レポートを計算
        df_records = pd.DataFrame(recent_expenses)
        if not df_records.empty:
            df_records = df_records.query(
                "expense_type not in @self.exclude_types"
            )
            df_records.loc[:, "date"] = pd.to_datetime(
                df_records.loc[:, "date"].map(
                    lambda s: re.sub(r"[^\d\-]+", "", s)
                )
            )
            report_summary = self.generate_report_summary(df_records)
            # グラフを生成
            df_graph = self.generate_monthly_df(df_records)
            graph_html = self.generate_daily_chart(df_records, theme)
            graph_html += "<hr>" if graph_html else ""
            graph_html += self.generate_pie_chart(df_graph, theme)
            graph_html += "<hr>" if graph_html else ""
            graph_html += self.generate_bar_chart(df_graph, theme)
        else:
            report_summary = {
                "today_total": 0,
                "monthly_total": 0,
                "prev_monthly_total": 0,
            }
            graph_html = ""
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
            "graph_html": graph_html,
            **report_summary,
        }


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
    server_tools: ServerTools = ServerTools()
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
    server_tools: ServerTools = ServerTools()
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
    server_tools: ServerTools = ServerTools()
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
            ocr_data = ocr.main()
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
    expense_amount: str = Form(...),
    expense_memo: str = Form(...),
) -> RedirectResponse:
    """
    登録レコードを削除するエンドポイント
    """
    log.info("start 'delete' method")
    server_tools: ServerTools = ServerTools()
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
    target_amount: str = Form(...),
    target_memo: str = Form(...),
    new_expense_type: str = Form(...),
    new_expense_amount: str = Form(...),
    new_expense_memo: str = Form(...),
) -> RedirectResponse:
    """
    登録レコードを修正するエンドポイント
    """
    log.info("start 'edit' method")
    server_tools: ServerTools = ServerTools()
    status = True
    msg = ""
    info = ""
    try:
        # parse date
        target_date = re.sub(r"\(.+\)", "", target_date)
        # parse amount
        target_amount = int(re.sub(r"[^\d]", "", str(target_amount)))
        new_expense_amount = int(re.sub(r"[^\d]", "", str(new_expense_amount)))

        log.debug(f"target_date: {target_date}")
        log.debug(f"target_type: {target_type}")
        log.debug(f"target_amount: {target_amount}")
        log.debug(f"target_memo: {target_memo}")
        log.debug(f"new_expense_type: {new_expense_type}")
        log.debug(f"new_expense_amount: {new_expense_amount}")
        log.debug(f"new_expense_memo: {new_expense_memo}")
        if (
            target_type != new_expense_type
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
