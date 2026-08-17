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
            missing_weight_count, specified_weight_total = (
                AssetManager._get_weight_summary(
                    target_weights, total_valuation
                )
            )
            allocation: list[dict[str, Any]] = []
            for ticker, configured_target in target_weights.items():
                parsed_target = AssetManager._parse_target(configured_target)
                if parsed_target is None:
                    continue
                target, target_tickers, target_amount = parsed_target
                if target_amount is None:
                    if target is None:
                        if missing_weight_count != 1:
                            continue
                        target = 100 - specified_weight_total
                    target_percent = AssetManager._parse_percent(target)
                    if target_percent is None:
                        continue
                else:
                    target_percent = target_amount / total_valuation * 100
                current_value = AssetManager._get_current_value(
                    current_valuations, ticker, target_tickers
                )
                if current_value is None:
                    continue
                current_percent = current_value / total_valuation * 100
                if target_amount is not None:
                    target_value = target_amount
                    target_percent = target_value / total_valuation * 100
                else:
                    target_value = total_valuation * target_percent / 100
                difference_percent = target_percent - current_percent
                trade_value = target_value - current_value
                within_tolerance = abs(difference_percent) <= tolerance
                allocation.append(
                    {
                        "ticker": ticker,
                        "tickers": target_tickers,
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

    @staticmethod
    def _parse_target(
        target: Any,
    ) -> tuple[Any, list[str] | None, float | None] | None:
        target_tickers: list[str] | None = None
        target_amount: float | None = None
        if isinstance(target, dict):
            target_tickers = target.get("tickers")
            if target.get("target_amount") is not None:
                try:
                    target_amount = float(target["target_amount"])
                except (TypeError, ValueError):
                    return None
                if target_amount < 0:
                    return None
            target = target.get("weight")
        return target, target_tickers, target_amount

    @staticmethod
    def _parse_percent(value: Any) -> float | None:
        try:
            percent = float(value)
        except (TypeError, ValueError):
            return None
        return percent if 0 <= percent <= 100 else None

    @staticmethod
    def _get_weight_summary(
        target_weights: dict[str, Any], total_valuation: float
    ) -> tuple[int, float]:
        missing_count = 0
        specified_total = 0.0
        for configured_target in target_weights.values():
            parsed_target = AssetManager._parse_target(configured_target)
            if parsed_target is None:
                continue
            target, _, target_amount = parsed_target
            if target_amount is not None:
                specified_total += target_amount / total_valuation * 100
            elif target is None:
                missing_count += 1
            else:
                target_percent = AssetManager._parse_percent(target)
                if target_percent is not None:
                    specified_total += target_percent
        return missing_count, specified_total

    @staticmethod
    def _get_current_value(
        current_valuations: pd.Series,
        ticker: str,
        target_tickers: list[str] | None,
    ) -> float | None:
        if target_tickers is None:
            return float(current_valuations.get(ticker, 0.0))
        if not isinstance(target_tickers, list) or not all(
            isinstance(target_ticker, str) for target_ticker in target_tickers
        ):
            return None
        return sum(
            float(current_valuations.get(target_ticker, 0.0))
            for target_ticker in target_tickers
        )

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

    @staticmethod
    def _flatten_values(
        values: list[list[Any]], rows: int, columns: int
    ) -> list[Any]:
        padded_rows = [
            row[:columns] + [""] * max(columns - len(row), 0)
            for row in values[:rows]
        ]
        padded_rows.extend([[""] * columns] * (rows - len(padded_rows)))
        return [value for row in padded_rows for value in row]

    @staticmethod
    def _parse_table_data(item_list: list[Any]) -> pd.DataFrame:
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
        return df

    @staticmethod
    def _parse_header_data(item_list: list[Any]) -> pd.DataFrame:
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
        return df

    @staticmethod
    def _parse_stock_info_data(item_list: list[Any]) -> pd.DataFrame:
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
        return df

    @staticmethod
    def _parse_monthly_history_data(item_list: list[Any]) -> pd.DataFrame:
        df = pd.DataFrame(item_list)
        df = pd.DataFrame(df.to_numpy().reshape(len(item_list) // 5, 5))
        df.columns = pd.Index(df.iloc[0], name=None)
        df = df.drop(0).replace("", pd.NA).replace("#N/A", "0").dropna()
        df = df.map(lambda s: re.sub("[$¥%,]", "", s))
        df.columns = pd.Index(
            ["date", "invest_amount", "valuation", "profit", "roi"]
        )
        df["date"] = pd.to_datetime(df["date"])
        df.iloc[:, 1:] = df.iloc[:, 1:].astype(float)
        return df

    @retry(stop=stop_after_attempt(3))
    def get_asset_data(
        self,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Get all asset-management ranges in one Sheets API request."""
        log.info("start 'get_asset_data' method")
        try:
            ranges = [
                "'ポートフォリオ'!A1:H2",
                "'ポートフォリオ'!A4:J15",
                "'資産推移 月次'!G18:K500",
                "'株価情報'!A2:N15",
            ]
            response = self.workbook.values_batch_get(ranges)
            value_ranges = response.get("valueRanges", [])
            if len(value_ranges) != len(ranges):
                raise ValueError("incomplete response from values_batch_get")

            header_values = self._flatten_values(
                value_ranges[0].get("values", []), 2, 8
            )
            table_values = self._flatten_values(
                value_ranges[1].get("values", []), 12, 10
            )
            monthly_values = self._flatten_values(
                value_ranges[2].get("values", []), 483, 5
            )
            stock_values = self._flatten_values(
                value_ranges[3].get("values", []), 14, 14
            )
            return (
                self._parse_header_data(header_values),
                self._parse_table_data(table_values),
                self._parse_monthly_history_data(monthly_values),
                self._parse_stock_info_data(stock_values),
            )
        finally:
            log.info("end 'get_asset_data' method")

    @retry(stop=stop_after_attempt(3))
    def get_table_data(self, cell_range: str = "A4:J15") -> pd.DataFrame:
        log.info("start 'get_table_data' method")
        try:
            cells = self.sheet.range(cell_range)
            item_list = [c.value for c in cells]
            return self._parse_table_data(item_list)
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
            return self._parse_header_data(item_list)
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
