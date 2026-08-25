import unittest
import threading
import datetime as dt
from unittest.mock import Mock, patch, mock_open

import pandas as pd

from src.expense.api.server import (
    _RECORD_CACHE_TTL,
    _LazyGspreadHandler,
    _clear_record_cache,
    _df_cache_record,
    _get_cached_graph,
)
from src.expense.api.server_tools import ServerTools


class TestLazyGspreadHandler(unittest.TestCase):
    def test_connects_on_first_use_and_retries(self) -> None:
        handler = Mock()
        handler.get_spreadsheet_url.return_value = "https://example.test"
        with (
            patch(
                "src.expense.api.server.GspreadHandler",
                side_effect=[RuntimeError("temporary"), handler],
            ) as constructor,
            patch("src.expense.api.server.time.sleep") as sleep,
        ):
            lazy_handler = _LazyGspreadHandler("book")

            self.assertEqual(
                lazy_handler.get_spreadsheet_url(), "https://example.test"
            )
            self.assertEqual(constructor.call_count, 2)
            sleep.assert_called_once_with(1)

    def test_does_not_fail_when_sheets_are_unavailable(self) -> None:
        with (
            patch(
                "src.expense.api.server.GspreadHandler",
                side_effect=RuntimeError("unavailable"),
            ),
            patch("src.expense.api.server.time.sleep"),
        ):
            lazy_handler = _LazyGspreadHandler("book")

            self.assertEqual(lazy_handler.get_spreadsheet_url(), "")


class TestCachedGraph(unittest.TestCase):
    def test_record_cache_can_be_cleared(self) -> None:
        _df_cache_record["graph_html"] = {("bar",): "<div>graph</div>"}
        _df_cache_record["timestamp"] = "not-a-real-timestamp"

        _clear_record_cache()

        self.assertEqual(_df_cache_record, {})

    def test_reuses_graph_for_the_same_key(self) -> None:
        cache: dict = {}
        generator = Mock(return_value="<div>graph</div>")

        first = _get_cached_graph(cache, threading.Lock(), ("bar",), generator)
        second = _get_cached_graph(cache, threading.Lock(), ("bar",), generator)

        self.assertEqual(first, "<div>graph</div>")
        self.assertEqual(second, first)
        generator.assert_called_once_with()

    def test_generates_separate_graphs_for_different_keys(self) -> None:
        cache: dict = {}
        generator = Mock(side_effect=["light", "dark"])

        light = _get_cached_graph(
            cache, threading.Lock(), ("bar", "light"), generator
        )
        dark = _get_cached_graph(
            cache, threading.Lock(), ("bar", "dark"), generator
        )

        self.assertEqual((light, dark), ("light", "dark"))
        self.assertEqual(generator.call_count, 2)

    def test_record_cache_ttl_is_five_minutes(self) -> None:
        self.assertEqual(_RECORD_CACHE_TTL, 300)


class TestLatestScreenshotData(unittest.TestCase):
    def test_returns_screenshot_and_registration_state(self) -> None:
        server_tools = ServerTools.__new__(ServerTools)
        server_tools.expense_handler = Mock(
            get_ocr_expense=Mock(return_value={})
        )
        with (
            patch(
                "src.expense.api.server_tools.get_latest_screenshot",
                return_value="/screenshots/receipt.png",
            ),
            patch("builtins.open", mock_open(read_data=b"png")),
        ):
            result = server_tools.get_latest_screenshot_data()

        self.assertEqual(result["screenshot_name"], "/screenshots/receipt.png")
        self.assertEqual(result["screenshot_base64"], "cG5n")
        self.assertFalse(result["disable_ocr"])

    def test_returns_empty_data_when_screenshot_is_missing(self) -> None:
        server_tools = ServerTools.__new__(ServerTools)
        with patch(
            "src.expense.api.server_tools.get_latest_screenshot",
            return_value="",
        ):
            result = server_tools.get_latest_screenshot_data()

        self.assertEqual(result["screenshot_name"], "")
        self.assertTrue(result["disable_ocr"])


class TestReportSummary(unittest.TestCase):
    def test_monthly_total_includes_expenses_later_on_today(self) -> None:
        server_tools = ServerTools.__new__(ServerTools)
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2026-08-01 12:00",
                        "2026-08-25 00:01",
                        "2026-08-25 23:59",
                        "2026-07-31 23:59",
                    ]
                ),
                "expense_amount": [100, 200, 300, 400],
            }
        )

        fixed_now = dt.datetime(2026, 8, 25, 18)
        with patch("src.expense.api.server_tools.dt.datetime") as datetime_mock:
            datetime_mock.today.return_value = fixed_now
            result = server_tools.generate_report_summary(df)

        self.assertEqual(result["today_total"], 500)
        self.assertEqual(result["monthly_total"], 600)
        self.assertEqual(result["prev_monthly_total"], 400)


if __name__ == "__main__":
    unittest.main()
