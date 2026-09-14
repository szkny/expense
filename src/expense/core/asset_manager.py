import math
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
        df_summary: pd.DataFrame | None = None,
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
            drawdown = AssetManager._get_drawdown(df_summary)
            adjusted_target_weights = AssetManager._adjust_cash_target(
                target_weights, drawdown
            )
            missing_weight_count, _ = (
                AssetManager._get_weight_summary(
                    adjusted_target_weights, total_valuation
                )
            )
            allocation, missing_tickers = AssetManager._build_allocations(
                adjusted_target_weights,
                current_valuations,
                total_valuation,
                missing_weight_count,
                drawdown,
                tolerance,
            )
            AssetManager._apply_missing_weights(
                allocation, missing_tickers, total_valuation, tolerance
            )
            AssetManager._adjust_non_cash_weights(
                allocation, drawdown, total_valuation, tolerance
            )
            AssetManager._balance_allocations(
                allocation, total_valuation, tolerance
            )
            return allocation
        finally:
            log.info("end 'build_asset_allocation' method")

    @staticmethod
    def _get_drawdown(df_summary: pd.DataFrame | None) -> float | None:
        if df_summary is None or df_summary.empty or "drawdown" not in df_summary:
            return None
        try:
            drawdown = float(df_summary["drawdown"].iloc[0])
        except (IndexError, TypeError, ValueError):
            return None
        return drawdown if math.isfinite(drawdown) else None

    @staticmethod
    def _adjust_cash_target(
        target_weights: dict[str, Any], drawdown: float | None
    ) -> dict[str, Any]:
        adjusted = target_weights.copy()
        if drawdown is None or "現金" not in adjusted:
            return adjusted
        cash_target = adjusted["現金"]
        if isinstance(cash_target, dict):
            if cash_target.get("target_amount") is not None:
                return adjusted
            try:
                cash_target = cash_target.copy()
                cash_target["weight"] = max(
                    float(cash_target.get("weight", 0)) + drawdown, 0.0
                )
            except (TypeError, ValueError):
                return adjusted
            adjusted["現金"] = cash_target
            return adjusted
        try:
            adjusted["現金"] = max(float(cash_target) + drawdown, 0.0)
        except (TypeError, ValueError):
            pass
        return adjusted

    @staticmethod
    def _build_allocations(
        target_weights: dict[str, Any],
        current_valuations: pd.Series,
        total_valuation: float,
        missing_weight_count: int,
        drawdown: float | None,
        tolerance: float,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        missing_tickers = {
            ticker
            for ticker, configured_target in target_weights.items()
            if (
                (parsed_target := AssetManager._parse_target(configured_target))
                is not None
                and parsed_target[0] is None
                and parsed_target[2] is None
            )
        }
        allocation = []
        for ticker, configured_target in target_weights.items():
            item = AssetManager._build_allocation_item(
                ticker,
                configured_target,
                current_valuations,
                total_valuation,
                missing_weight_count,
                drawdown,
                tolerance,
            )
            if item is not None:
                allocation.append(item)
        return allocation, missing_tickers

    @staticmethod
    def _build_allocation_item(
        ticker: str,
        configured_target: Any,
        current_valuations: pd.Series,
        total_valuation: float,
        missing_weight_count: int,
        drawdown: float | None,
        tolerance: float,
    ) -> dict[str, Any] | None:
        parsed_target = AssetManager._parse_target(configured_target)
        if parsed_target is None:
            return None
        target, target_tickers, target_amount = parsed_target
        if target_amount is None:
            if target is None:
                if missing_weight_count == 0:
                    return None
                target = 0.0
            target_percent = AssetManager._parse_percent(target)
            if target_percent is None:
                return None
        else:
            target_percent = target_amount / total_valuation * 100
        current_value = AssetManager._get_current_value(
            current_valuations, ticker, target_tickers
        )
        if current_value is None:
            return None
        if target_amount is not None and ticker == "現金" and drawdown is not None:
            target_percent = max(target_percent + drawdown, 0.0)
        target_value = (
            target_amount
            if target_amount is not None and not (
                ticker == "現金" and drawdown is not None
            )
            else total_valuation * target_percent / 100
        )
        current_percent = current_value / total_valuation * 100
        return AssetManager._allocation_record(
            ticker,
            target_tickers,
            target_percent,
            target_value,
            current_value,
            current_percent,
            tolerance,
        )

    @staticmethod
    def _allocation_record(
        ticker: str,
        target_tickers: list[str] | None,
        target_percent: float,
        target_value: float,
        current_value: float,
        current_percent: float,
        tolerance: float,
    ) -> dict[str, Any]:
        difference_percent = target_percent - current_percent
        trade_value = target_value - current_value
        within_tolerance = abs(difference_percent) <= tolerance
        return {
            "ticker": ticker,
            "tickers": target_tickers,
            "target_weight": target_percent,
            "current_weight": current_percent,
            "target_value": target_value,
            "current_value": current_value,
            "difference_weight": difference_percent,
            "trade_value": 0 if within_tolerance else trade_value,
            "action": (
                "調整不要"
                if within_tolerance
                else ("買い" if trade_value > 0 else "売り")
            ),
        }

    @staticmethod
    def _apply_missing_weights(
        allocation: list[dict[str, Any]],
        missing_tickers: set[str],
        total_valuation: float,
        tolerance: float,
    ) -> None:
        missing = [
            item for item in allocation if item["ticker"] in missing_tickers
        ]
        if not missing:
            return
        remaining = max(
            100
            - sum(
                item["target_weight"]
                for item in allocation
                if item["ticker"] not in missing_tickers
            ),
            0.0,
        )
        targets = AssetManager._allocate_missing_weights(
            [item["current_weight"] for item in missing], remaining
        )
        for item, target in zip(missing, targets):
            item.update(
                AssetManager._allocation_record(
                    item["ticker"],
                    item["tickers"],
                    target,
                    total_valuation * target / 100,
                    item["current_value"],
                    item["current_weight"],
                    tolerance,
                )
            )

    @staticmethod
    def _adjust_non_cash_weights(
        allocation: list[dict[str, Any]],
        drawdown: float | None,
        total_valuation: float,
        tolerance: float,
    ) -> None:
        if drawdown is None:
            return
        cash = next(
            (item for item in allocation if item["ticker"] == "現金"), None
        )
        non_cash = [item for item in allocation if item["ticker"] != "現金"]
        non_cash_total = sum(item["target_weight"] for item in non_cash)
        target_total = sum(item["target_weight"] for item in allocation)
        if cash is None or non_cash_total <= 0 or math.isclose(target_total, 100):
            return
        scale = (100 - cash["target_weight"]) / non_cash_total
        for item in non_cash:
            target = item["target_weight"] * scale
            item.update(
                AssetManager._allocation_record(
                    item["ticker"],
                    item["tickers"],
                    target,
                    total_valuation * target / 100,
                    item["current_value"],
                    item["current_weight"],
                    tolerance,
                )
            )

    @staticmethod
    def _balance_allocations(
        allocation: list[dict[str, Any]],
        total_valuation: float,
        tolerance: float,
    ) -> None:
        locked = [
            item
            for item in allocation
            if abs(item["difference_weight"]) <= tolerance
        ]
        adjustable = [item for item in allocation if item not in locked]
        target_total = sum(item["target_weight"] for item in adjustable)
        if not adjustable or target_total <= 0:
            return
        locked_total = sum(item["current_weight"] for item in locked)
        scale = (100 - locked_total) / target_total
        for item in locked:
            item["target_weight"] = item["current_weight"]
        for item in adjustable:
            item["target_weight"] *= scale
        for item in allocation:
            target = item["target_weight"]
            item.update(
                AssetManager._allocation_record(
                    item["ticker"],
                    item["tickers"],
                    target,
                    total_valuation * target / 100,
                    item["current_value"],
                    item["current_weight"],
                    tolerance,
                )
            )

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
    def _allocate_missing_weights(
        current_weights: list[float], target_total: float
    ) -> list[float]:
        """Allocate a missing target while minimizing changes from current weights."""
        if not current_weights:
            return []
        current_total = sum(current_weights)
        if current_total <= target_total:
            increase = (target_total - current_total) / len(current_weights)
            return [weight + increase for weight in current_weights]

        target_weights = current_weights.copy()
        reduction = current_total - target_total
        active = list(range(len(target_weights)))
        while active and reduction > 0:
            amount = reduction / len(active)
            decrements = [
                min(target_weights[index], amount) for index in active
            ]
            reduction -= sum(decrements)
            for index, decrement in zip(active, decrements):
                target_weights[index] -= decrement
            active = [index for index in active if target_weights[index] > 0]
        return [max(weight, 0.0) for weight in target_weights]

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
        data_types: set[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Get selected asset-management ranges in one Sheets API request."""
        log.info("start 'get_asset_data' method")
        try:
            specs = [
                ("df_summary", "'ポートフォリオ'!A1:H2", 2, 8),
                ("df_items", "'ポートフォリオ'!A4:J15", 12, 10),
                ("df_records", "'資産推移 月次'!G18:K500", 483, 5),
                ("df_stock", "'株価情報'!A2:N15", 14, 14),
            ]
            selected_specs = [
                spec
                for spec in specs
                if data_types is None or spec[0] in data_types
            ]
            ranges = [spec[1] for spec in selected_specs]
            response = self.workbook.values_batch_get(ranges)
            value_ranges = response.get("valueRanges", [])
            if len(value_ranges) != len(ranges):
                raise ValueError("incomplete response from values_batch_get")

            dataframes: dict[str, pd.DataFrame] = {}
            for spec, value_range in zip(selected_specs, value_ranges):
                key, _, rows, columns = spec
                values = self._flatten_values(
                    value_range.get("values", []), rows, columns
                )
                if key == "df_summary":
                    dataframes[key] = self._parse_header_data(values)
                elif key == "df_items":
                    dataframes[key] = self._parse_table_data(values)
                elif key == "df_records":
                    dataframes[key] = self._parse_monthly_history_data(values)
                else:
                    dataframes[key] = self._parse_stock_info_data(values)
            return dataframes
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
