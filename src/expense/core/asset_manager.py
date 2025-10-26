import re
import gspread
import logging
import pandas as pd
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
