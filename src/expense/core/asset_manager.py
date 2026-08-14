import re
import gspread
import logging
import pandas as pd
from typing import Any
from yahoo_fin import stock_info as si
from tenacity import retry, stop_after_attempt
from google.oauth2 import service_account

from .base import Base

log: logging.Logger = logging.getLogger("expense")


class AssetManager(Base):
    def __init__(
        self,
        book_name: str = "投資実績",
        sheet_name: str = "ポートフォリオ",
    ) -> None:
        super().__init__()
        credentials = service_account.Credentials.from_service_account_file(
            self.config_path / "credentials.json",
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        self.client = gspread.authorize(credentials)
        self.workbook = self.client.open(book_name)
        self.sheet = self.workbook.worksheet(sheet_name)
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def get_spreadsheet_url(self) -> str:
        return self.workbook.url + "/edit"

    @staticmethod
    def build_asset_allocation(
        df_items: pd.DataFrame,
        target_weights: dict[str, Any],
        tolerance_percent: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Build target allocation and trade suggestions for configured tickers."""
        log.info("start 'build_asset_allocation' method")
        try:
            if df_items.empty or not target_weights:
                return []

            total_valuation = float(df_items["valuation"].sum())
            if total_valuation <= 0:
                return []

            current_valuations = df_items.groupby("ticker")["valuation"].sum()
            tolerance = max(float(tolerance_percent), 0.0)
            allocation: list[dict[str, Any]] = []
            for ticker, target in target_weights.items():
                target_tickers: list[str] | None = None
                if isinstance(target, dict):
                    target_tickers = target.get("tickers")
                    target = target.get("weight")
                try:
                    target_percent = float(target)
                except (TypeError, ValueError):
                    continue
                if target_percent < 0 or target_percent > 100:
                    continue
                if target_tickers is None:
                    current_value = float(current_valuations.get(ticker, 0.0))
                else:
                    if not isinstance(target_tickers, list) or not all(
                        isinstance(target_ticker, str)
                        for target_ticker in target_tickers
                    ):
                        continue
                    current_value = sum(
                        float(current_valuations.get(target_ticker, 0.0))
                        for target_ticker in target_tickers
                    )
                current_percent = current_value / total_valuation * 100
                difference_percent = target_percent - current_percent
                target_value = total_valuation * target_percent / 100
                trade_value = target_value - current_value
                within_tolerance = abs(difference_percent) <= tolerance
                allocation.append(
                    {
                        "ticker": ticker,
                        "target_weight": target_percent,
                        "current_weight": current_percent,
                        "target_value": target_value,
                        "current_value": current_value,
                        "difference_weight": difference_percent,
                        "trade_value": 0 if within_tolerance else trade_value,
                        "action": "調整不要"
                        if within_tolerance
                        else ("買い" if trade_value > 0 else "売り"),
                    }
                )
            return allocation
        finally:
            log.info("end 'build_asset_allocation' method")

    @retry(stop=stop_after_attempt(3))
    def get_live_price(self, ticker: str) -> float | None:
        log.info("start 'get_live_price' method")
        try:
            log.debug(f"Target ticker: {ticker}")
            df = si.get_data(
                ticker,
                end_date=pd.Timestamp.today() + pd.Timedelta(days=10),
                headers=self.headers,
            )
            if df.empty:
                return None
            price: float | None = df["close"].iloc[-1]
            price = float(price) if price else None
            log.debug(f"live price: {price}")
            return price
        except Exception:
            log.exception("Error occurred.")
            return None
        finally:
            log.info("end 'get_live_price' method")

    @retry(stop=stop_after_attempt(3))
    def get_table_data(self, cell_range: str = "A4:J15") -> pd.DataFrame:
        log.info("start 'get_table_data' method")
        try:
            cells = self.sheet.range(cell_range)
            item_list = [c.value for c in cells]
            df = pd.DataFrame(item_list)
            df = pd.DataFrame(df.to_numpy().reshape(len(item_list) // 10, 10))
            df.columns = pd.Index(df.iloc[0], name=None)
            df = df.drop(0).replace("", pd.NA).replace("#N/A", "0").dropna()
            df = df.map(lambda s: re.sub("[$¥%,]", "", s))
            df.iloc[:, 1:] = df.iloc[:, 1:].astype(float)
            df.columns = pd.Index(
                [
                    "ticker",
                    "num",
                    "acquisition",
                    "price_dollar",
                    "price",
                    "invest_amount",
                    "valuation",
                    "profit",
                    "weight",
                    "roi",
                ]
            )
            # log.debug(f"df:\n{df}")
            return df
        except Exception:
            log.exception("Error occurred.")
            return pd.DataFrame(
                columns=[
                    "ticker",
                    "num",
                    "acquisition",
                    "price_dollar",
                    "price",
                    "invest_amount",
                    "valuation",
                    "profit",
                    "weight",
                    "roi",
                ]
            )
        finally:
            log.info("end 'get_table_data' method")

    @retry(stop=stop_after_attempt(3))
    def get_header_data(self, cell_range: str = "A1:H2") -> pd.DataFrame:
        log.info("start 'get_header_data' method")
        try:
            cells = self.sheet.range(cell_range)
            item_list = [c.value for c in cells]
            df = pd.DataFrame(item_list)
            df = pd.DataFrame(df.to_numpy().reshape(len(item_list) // 8, 8))
            df.columns = pd.Index(df.iloc[0], name=None)
            df = df.drop(0).replace("", pd.NA).replace("#N/A", "0").dropna()
            df = df.map(lambda s: re.sub("[$¥%,]", "", s))
            df = df.astype(float)
            df.columns = pd.Index(
                [
                    "total",
                    "profit",
                    "profit_etf",
                    "roi",
                    "change_jpy",
                    "change_pct",
                    "drawdown",
                    "usdjpy",
                ]
            )
            # log.debug(f"df:\n{df}")
            return df
        except Exception:
            log.exception("Error occurred.")
            return pd.DataFrame(
                columns=[
                    "total",
                    "profit",
                    "profit_etf",
                    "roi",
                    "change_jpy",
                    "change_pct",
                    "drawdown",
                    "usdjpy",
                ]
            )
        finally:
            log.info("end 'get_header_data' method")

    @retry(stop=stop_after_attempt(3))
    def get_stock_info_data(
        self, cell_range: str = "A2:N15", sheet_name: str = "株価情報"
    ) -> pd.DataFrame:
        log.info("start 'get_stock_info_data' method")
        try:
            sheet = self.workbook.worksheet(sheet_name)
            cells = sheet.range(cell_range)
            item_list = [c.value for c in cells]
            df = pd.DataFrame(item_list)
            df = pd.DataFrame(df.to_numpy().reshape(len(item_list) // 14, 14))
            df.columns = pd.Index(df.iloc[0], name=None)
            cols = [c for c in df.columns if "チャート" not in c]
            df = df[cols]
            df.set_index("No", inplace=True)
            df = df.map(lambda s: re.sub("[$¥%,+ー]", "", s))
            df = df.iloc[1:]
            df = df.replace("", pd.NA).replace("#N/A", pd.NA).dropna(how="all")
            df.iloc[:, 1:] = df.iloc[:, 1:].astype("Float64")
            df.columns = pd.Index(
                [
                    "ticker",
                    "price",
                    "change_pct",
                    "change_pct_weekly",
                    "change_pct_monthly",
                    "drawdown",
                    "change_pct_yen",
                    "change_yen",
                    "valuation",
                    "profit",
                    "roi",
                ]
            )
            # log.debug(f"df:\n{df}")
            return df
        except Exception:
            log.exception("Error occurred.")
            return pd.DataFrame(
                columns=[
                    "ticker",
                    "price",
                    "change_pct",
                    "change_pct_weekly",
                    "change_pct_monthly",
                    "drawdown",
                    "change_pct_yen",
                    "change_yen",
                    "valuation",
                    "profit",
                    "roi",
                ]
            )
        finally:
            log.info("end 'get_stock_info_data' method")

    @retry(stop=stop_after_attempt(3))
    def get_monthly_history_data(
        self, cell_range: str = "G18:K500", sheet_name: str = "資産推移 月次"
    ) -> pd.DataFrame:
        log.info("start 'get_monthly_history_data' method")
        try:
            sheet = self.workbook.worksheet(sheet_name)
            cells = sheet.range(cell_range)
            item_list = [c.value for c in cells]
            df = pd.DataFrame(item_list)
            df = pd.DataFrame(df.to_numpy().reshape(len(item_list) // 5, 5))
            df.columns = pd.Index(df.iloc[0], name=None)
            df = df.drop(0).replace("", pd.NA).replace("#N/A", "0").dropna()
            df = df.map(lambda s: re.sub("[$¥%,]", "", s))
            df.columns = pd.Index(
                [
                    "date",
                    "invest_amount",
                    "valuation",
                    "profit",
                    "roi",
                ]
            )
            df["date"] = pd.to_datetime(df["date"])
            df.iloc[:, 1:] = df.iloc[:, 1:].astype(float)
            # log.debug(f"df:\n{df}")
            return df
        except Exception:
            log.exception("Error occurred.")
            return pd.DataFrame(
                columns=[
                    "date",
                    "invest_amount",
                    "valuation",
                    "profit",
                    "roi",
                ]
            )
        finally:
            log.info("end 'get_monthly_history_data' method")
