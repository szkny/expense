import unittest
import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch, mock_open

import pandas as pd
from fastapi.testclient import TestClient

from expense.api.server import (
    _RECORD_CACHE_TTL,
    _LazyGspreadHandler,
    _clear_record_cache,
    _df_cache_record,
    _is_local_only_type,
    app,
    get_simulation_averages,
)
from expense.api.server_tools import ServerTools


class TestServiceWorkerRoute(unittest.TestCase):
    def test_service_worker_is_served_from_root_scope(self) -> None:
        response = TestClient(app).get("/service-worker.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/javascript", response.headers["content-type"]
        )
        self.assertIn('const CACHE_NAME = "expense-cache-v10"', response.text)
        self.assertIn(
            'requestUrl.pathname === "/api/asset_management/content"',
            response.text,
        )

    def test_repeated_requests_do_not_add_static_mounts_or_change_response(
        self,
    ) -> None:
        static_mounts_before = [
            route
            for route in app.routes
            if getattr(route, "name", "") == "static"
        ]
        route_count_before = len(app.routes)
        with (
            patch(
                "expense.api.server.gspread_handler",
                Mock(get_spreadsheet_url=Mock(return_value="")),
            ),
            patch(
                "expense.api.server_tools.get_latest_screenshot",
                return_value="",
            ),
        ):
            client = TestClient(app)
            first = client.get("/api/ocr/latest")
            second = client.get("/api/ocr/latest")

        static_mounts_after = [
            route
            for route in app.routes
            if getattr(route, "name", "") == "static"
        ]
        self.assertEqual(len(static_mounts_before), 1)
        self.assertEqual(len(static_mounts_after), 1)
        self.assertEqual(len(app.routes), route_count_before)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())


class TestRecurringExpenseDialog(unittest.TestCase):
    def test_renders_escaped_recommendation_and_today_registration_form(
        self,
    ) -> None:
        server_tools = Mock(templates=app.state.templates)
        server_tools.generate_commons.return_value = {
            "icons": {},
            "theme": "light",
            "expense_date_range": ("2026-04-01", "2027-03-31"),
            "n_records": 0,
            "gspread_url": "",
            "items": [],
            "records": [],
            "recurring_expenses": [
                {
                    "expense_type": "通信費",
                    "expense_memo": '<script>alert("x")</script>',
                    "expense_amount": 3000,
                }
            ],
            "screenshot_name": "",
            "screenshot_base64": "",
            "disable_ocr": True,
            "today": "2026-04-15",
            "plotlyjs": "",
            "today_total": 0,
            "monthly_total": 0,
            "prev_monthly_total": 0,
        }

        with patch("expense.api.server.ServerTools", return_value=server_tools):
            response = TestClient(app).get("/api/home")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("この内容で登録しますか？", response.text)
        self.assertIn("3,000円", response.text)
        self.assertIn("&lt;script&gt;", response.text)
        self.assertNotIn('<script>alert("x")</script>', response.text)
        self.assertIn('data-today="2026-04-15"', response.text)
        self.assertIn('data-expense-type="通信費"', response.text)
        self.assertIn('name="expense_date" value="2026-04-15"', response.text)


class TestHomeShell(unittest.TestCase):
    def test_root_returns_shell_without_generating_home_data(self) -> None:
        server_tools = Mock(
            templates=app.state.templates,
            icons={},
            expense_types=["食費", "給与"],
        )

        with patch("expense.api.server.ServerTools", return_value=server_tools):
            response = TestClient(app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("家計簿を読み込んでいます", response.text)
        self.assertIn('id="expense-type"', response.text)
        self.assertIn('<option value="食費">', response.text)
        self.assertIn('name="expense_date"', response.text)
        server_tools.generate_commons.assert_not_called()

    def test_plotly_bundle_is_cached_separately(self) -> None:
        with patch(
            "expense.api.server._get_plotlyjs_bundle",
            return_value="window.Plotly = {};",
        ):
            response = TestClient(app).get("/plotly.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "window.Plotly = {};")
        self.assertIn("max-age=86400", response.headers["cache-control"])

    def test_spreadsheet_url_is_loaded_separately(self) -> None:
        handler = Mock(
            get_spreadsheet_url=Mock(return_value="https://example.test")
        )

        with patch("expense.api.server.gspread_handler", handler):
            response = TestClient(app).get("/api/spreadsheet_url")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://example.test"})
        self.assertEqual(response.headers["cache-control"], "no-store")


class TestAssetManagementShell(unittest.TestCase):
    def test_asset_management_returns_shell_without_loading_asset_data(
        self,
    ) -> None:
        server_tools = Mock(templates=app.state.templates, icons={})
        asset_manager = Mock()

        with (
            patch("expense.api.server.ServerTools", return_value=server_tools),
            patch("expense.api.server.asset_manager", asset_manager),
            patch(
                "expense.api.server.get_cached_asset_table"
            ) as get_asset_table,
        ):
            response = TestClient(app).get("/asset_management")

        self.assertEqual(response.status_code, 200)
        self.assertIn("資産データを読み込んでいます", response.text)
        self.assertIn("/static/js/asset.js", response.text)
        self.assertNotIn("window.Plotly", response.text)
        get_asset_table.assert_not_called()
        asset_manager.get_spreadsheet_url.assert_not_called()

    def test_asset_content_is_not_cached_and_renders_asset_data(self) -> None:
        server_tools = Mock(
            templates=app.state.templates,
            icons={},
            config={"asset_management": {"allocation": {}}},
        )
        df_summary = pd.DataFrame(
            [
                {
                    "change_jpy": 0,
                    "change_pct": 0,
                    "drawdown": 0,
                    "usdjpy": 150,
                    "profit_etf": 0,
                    "roi": 0,
                }
            ]
        )
        df_items = pd.DataFrame(
            [
                {
                    "ticker": "TEST",
                    "num": 1,
                    "acquisition": 100,
                    "price_dollar": 1,
                    "price": 150,
                    "invest_amount": 100,
                    "valuation": 150,
                    "profit": 50,
                    "weight": 100,
                    "roi": 50,
                }
            ]
        )
        df_stock = pd.DataFrame({"ticker": ["JPY"], "change_pct": [0]})
        asset_manager = Mock()
        asset_manager.build_asset_allocation.return_value = []

        with (
            patch("expense.api.server.ServerTools", return_value=server_tools),
            patch("expense.api.server.asset_manager", asset_manager),
            patch(
                "expense.api.server.get_cached_asset_table",
                return_value=(df_summary, df_items, pd.DataFrame(), df_stock),
            ),
        ):
            response = TestClient(app).get("/api/asset_management/content")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("資産一覧", response.text)
        self.assertIn("TEST", response.text)
        self.assertIn('id="asset-advice-chat"', response.text)
        self.assertIn('id="asset-advice-chat-form"', response.text)
        self.assertIn('aria-label="会話をリセット"', response.text)
        self.assertIn("data-no-loader", response.text)
        self.assertNotIn("資産データを読み込んでいます", response.text)
        self.assertNotIn("window.Plotly", response.text)
        asset_manager.get_spreadsheet_url.assert_not_called()

    def test_asset_spreadsheet_url_is_loaded_separately(self) -> None:
        asset_manager = Mock()
        asset_manager.get_spreadsheet_url.return_value = "https://example.test"

        with patch("expense.api.server.asset_manager", asset_manager):
            response = TestClient(app).get("/api/asset_spreadsheet_url")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://example.test"})
        self.assertEqual(response.headers["cache-control"], "no-store")


class TestAssetRecentlyHistoryChartRoute(unittest.TestCase):
    def test_passes_recent_history_and_current_valuation_to_generator(
        self,
    ) -> None:
        today = pd.Timestamp.today().normalize()
        df_items = pd.DataFrame({"valuation": [250]})
        df_monthly = pd.DataFrame(
            {
                "date": [today - pd.Timedelta(days=20)],
                "invest_amount": [100],
                "valuation": [110],
                "profit": [10],
            }
        )
        df_daily = pd.DataFrame(
            {
                "date": [today - pd.Timedelta(days=1)],
                "invest_amount": [100],
                "valuation": [120],
                "profit": [20],
            }
        )
        graph_generator = Mock()
        graph_generator.generate_asset_recently_history_chart.return_value = (
            "<div>recent</div>"
        )
        server_tools = Mock(graph_generator=graph_generator)

        with (
            patch("expense.api.server.ServerTools", return_value=server_tools),
            patch(
                "expense.api.server.get_cached_asset_table",
                return_value=(
                    pd.DataFrame(),
                    df_items,
                    df_monthly,
                    pd.DataFrame(),
                ),
            ),
            patch(
                "expense.api.server.get_cached_asset_history_records",
                return_value=df_daily,
            ),
            patch(
                "expense.api.server.get_cached_graph",
                side_effect=lambda *args: args[-1](),
            ),
        ):
            response = TestClient(app).get("/api/asset_recently_history_chart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "<div>recent</div>")
        graph_data = graph_generator.generate_asset_recently_history_chart.call_args.args[
            0
        ]
        self.assertEqual(list(graph_data["valuation"]), [120, 250])
        self.assertEqual(pd.Timestamp(graph_data["date"].iloc[-1]), today)


class TestLazyGspreadHandler(unittest.TestCase):
    def test_connects_on_first_use_and_retries(self) -> None:
        handler = Mock()
        handler.get_spreadsheet_url.return_value = "https://example.test"
        with (
            patch(
                "expense.api.server.GspreadHandler",
                side_effect=[RuntimeError("temporary"), handler],
            ) as constructor,
            patch("expense.api.server.time.sleep") as sleep,
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
                "expense.api.server.GspreadHandler",
                side_effect=RuntimeError("unavailable"),
            ),
            patch("expense.api.server.time.sleep"),
        ):
            lazy_handler = _LazyGspreadHandler("book")

            self.assertEqual(lazy_handler.get_spreadsheet_url(), "")


class TestRecordCache(unittest.TestCase):
    def test_record_cache_can_be_cleared(self) -> None:
        _df_cache_record["graph_html"] = {("bar",): "<div>graph</div>"}
        _df_cache_record["timestamp"] = "not-a-real-timestamp"

        _clear_record_cache()

        self.assertEqual(_df_cache_record, {})

    def test_record_cache_ttl_is_five_minutes(self) -> None:
        self.assertEqual(_RECORD_CACHE_TTL, 300)


class TestWriteEndpoints(unittest.TestCase):
    def make_server_tools(self) -> Mock:
        return Mock(
            icons={},
            gspread_handler=Mock(),
            expense_handler=Mock(),
            termux_api=Mock(),
            notification=Mock(),
        )

    def post(
        self, path: str, data: dict[str, str], server_tools: Mock
    ) -> tuple[Any, Mock]:
        with (
            patch(
                "expense.api.server.ServerTools",
                return_value=server_tools,
            ),
            patch("expense.api.server._clear_record_cache") as clear_cache,
        ):
            response = TestClient(app, follow_redirects=False).post(
                path, data=data
            )

        return response, clear_cache

    def test_register_writes_to_sheets_and_history(self) -> None:
        tools = self.make_server_tools()

        response, clear_cache = self.post(
            "/register",
            {
                "expense_type": "食費",
                "expense_amount": "¥12,345",
                "expense_memo": "昼食",
                "expense_date": "2026-04-01",
            },
            tools,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("status=True", response.headers["location"])
        tools.gspread_handler.register_expense.assert_called_once_with(
            "食費", 12345, "昼食", "2026-04-01"
        )
        tools.expense_handler.store_expense.assert_called_once_with(
            "食費", "昼食", 12345, "2026-04-01"
        )
        clear_cache.assert_called_once_with()

    def test_register_rejects_invalid_amount_without_writes(self) -> None:
        tools = self.make_server_tools()

        response, clear_cache = self.post(
            "/register",
            {
                "expense_type": "食費",
                "expense_amount": "invalid",
                "expense_memo": "昼食",
                "expense_date": "2026-04-01",
            },
            tools,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("status=False", response.headers["location"])
        tools.gspread_handler.register_expense.assert_not_called()
        tools.expense_handler.store_expense.assert_not_called()
        clear_cache.assert_not_called()

    def test_register_stops_after_sheets_failure_and_invalidates_cache(
        self,
    ) -> None:
        tools = self.make_server_tools()
        tools.gspread_handler.register_expense.side_effect = RuntimeError(
            "Sheets unavailable"
        )

        response, clear_cache = self.post(
            "/register",
            {
                "expense_type": "食費",
                "expense_amount": "1000",
                "expense_memo": "昼食",
                "expense_date": "2026-04-01",
            },
            tools,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("status=False", response.headers["location"])
        tools.expense_handler.store_expense.assert_not_called()
        clear_cache.assert_called_once_with()

    def test_delete_normalizes_date_and_amount(self) -> None:
        tools = self.make_server_tools()

        response, clear_cache = self.post(
            "/delete",
            {
                "expense_date": "2026-04-01(水)",
                "expense_type": "食費",
                "expense_amount": "¥12,345",
                "expense_memo": "昼食",
            },
            tools,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("status=True", response.headers["location"])
        tools.gspread_handler.delete_expense.assert_called_once_with(
            "2026-04-01", "食費", 12345, "昼食"
        )
        tools.expense_handler.delete_expense.assert_called_once_with(
            "2026-04-01", "食費", 12345, "昼食"
        )
        clear_cache.assert_called_once_with()

    def test_delete_does_not_change_history_when_sheets_rejects(self) -> None:
        tools = self.make_server_tools()
        tools.gspread_handler.delete_expense.return_value = False

        response, clear_cache = self.post(
            "/delete",
            {
                "expense_date": "2026-04-01",
                "expense_type": "食費",
                "expense_amount": "1000",
                "expense_memo": "昼食",
            },
            tools,
        )

        self.assertIn("status=False", response.headers["location"])
        tools.expense_handler.delete_expense.assert_not_called()
        clear_cache.assert_called_once_with()

    def test_edit_normalizes_both_records_and_invalidates_cache(self) -> None:
        tools = self.make_server_tools()

        response, clear_cache = self.post(
            "/edit",
            {
                "target_date": "2026-03-31(火)",
                "target_type": "食費",
                "target_amount": "¥1,000",
                "target_memo": "昼食",
                "new_expense_date": "2026-04-01(水)",
                "new_expense_type": "外食",
                "new_expense_amount": "¥2,000",
                "new_expense_memo": "夕食",
            },
            tools,
        )

        target = {
            "expense_date": "2026-03-31",
            "expense_type": "食費",
            "expense_amount": 1000,
            "expense_memo": "昼食",
        }
        new = {
            "expense_date": "2026-04-01",
            "expense_type": "外食",
            "expense_amount": 2000,
            "expense_memo": "夕食",
        }
        self.assertEqual(response.status_code, 303)
        self.assertIn("status=True", response.headers["location"])
        tools.gspread_handler.edit_expense.assert_called_once_with(
            target_expense=target, new_expense=new
        )
        tools.expense_handler.edit_expense.assert_called_once_with(
            target_expense=target, new_expense=new
        )
        clear_cache.assert_called_once_with()

    def test_edit_does_not_write_when_sheets_fails(self) -> None:
        tools = self.make_server_tools()
        tools.gspread_handler.edit_expense.return_value = False

        response, clear_cache = self.post(
            "/edit",
            {
                "target_date": "2026-03-31",
                "target_type": "食費",
                "target_amount": "1000",
                "target_memo": "昼食",
                "new_expense_date": "2026-04-01",
                "new_expense_type": "外食",
                "new_expense_amount": "2000",
                "new_expense_memo": "夕食",
            },
            tools,
        )

        self.assertIn("status=False", response.headers["location"])
        tools.expense_handler.edit_expense.assert_not_called()
        clear_cache.assert_called_once_with()

    def test_missing_register_fields_are_rejected_before_request_processing(
        self,
    ) -> None:
        with patch("expense.api.server.ServerTools") as server_tools:
            response = TestClient(app, follow_redirects=False).post(
                "/register", data={}
            )

        self.assertEqual(response.status_code, 422)
        server_tools.assert_not_called()

    def test_ocr_registers_fixed_result_and_caches_it_in_temp_directory(
        self,
    ) -> None:
        tools = self.make_server_tools()
        tools.expense_handler.get_ocr_expense.return_value = {}
        ocr = Mock()
        ocr.main.return_value = {
            "expense_type": "食費",
            "expense_amount": "1234",
            "expense_memo": "昼食",
            "expense_date": "2026-04-01",
        }
        with tempfile.TemporaryDirectory() as directory:
            tools.cache_path = Path(directory)
            with (
                patch("expense.api.server.Ocr", return_value=ocr),
                patch(
                    "expense.api.server.get_latest_screenshot",
                    return_value="/screenshots/receipt.jpg",
                ),
                patch("builtins.open", mock_open()) as open_file,
            ):
                response, clear_cache = self.post("/ocr", {}, tools)

            self.assertEqual(response.status_code, 303)
            self.assertIn("status=True", response.headers["location"])
            tools.gspread_handler.register_expense.assert_called_once_with(
                "食費", 1234, "昼食", "2026-04-01"
            )
            tools.expense_handler.store_expense.assert_called_once_with(
                "食費", "昼食", 1234, "2026-04-01"
            )
            open_file.assert_called_once_with(
                Path(directory) / "ocr_data.json", "w"
            )
            serialized_cache = "".join(
                call.args[0] for call in open_file().write.call_args_list
            )
            self.assertEqual(
                json.loads(serialized_cache), ocr.main.return_value
            )
            clear_cache.assert_called_once_with()

    def test_ocr_failure_does_not_write_history_and_clears_cache(self) -> None:
        tools = self.make_server_tools()
        tools.expense_handler.get_ocr_expense.return_value = {}
        tools.gspread_handler.register_expense.side_effect = RuntimeError(
            "Sheets unavailable"
        )
        ocr = Mock()
        ocr.main.return_value = {
            "expense_type": "食費",
            "expense_amount": "1234",
            "expense_memo": "昼食",
            "expense_date": "2026-04-01",
        }
        with tempfile.TemporaryDirectory() as directory:
            tools.cache_path = Path(directory)
            with (
                patch("expense.api.server.Ocr", return_value=ocr),
                patch(
                    "expense.api.server.get_latest_screenshot",
                    return_value="/screenshots/receipt.jpg",
                ),
                patch("builtins.open", mock_open()) as open_file,
            ):
                response, clear_cache = self.post("/ocr", {}, tools)

            self.assertEqual(response.status_code, 303)
            self.assertIn("status=False", response.headers["location"])
            tools.expense_handler.store_expense.assert_not_called()
            open_file.assert_not_called()
            clear_cache.assert_called_once_with()

    def test_ocr_skips_a_screenshot_already_registered(self) -> None:
        tools = self.make_server_tools()
        tools.expense_handler.get_ocr_expense.return_value = {
            "screenshot_name": "receipt.jpg",
            "expense_type": "食費",
            "expense_amount": 1234,
            "expense_memo": "昼食",
            "expense_date": "2026-04-01",
        }
        ocr = Mock()
        with (
            patch("expense.api.server.Ocr", return_value=ocr),
            patch(
                "expense.api.server.get_latest_screenshot",
                return_value="/screenshots/receipt.jpg",
            ),
        ):
            response, clear_cache = self.post("/ocr", {}, tools)

        self.assertEqual(response.status_code, 303)
        self.assertIn("status=False", response.headers["location"])
        ocr.main.assert_not_called()
        tools.gspread_handler.register_expense.assert_not_called()
        tools.expense_handler.store_expense.assert_not_called()
        clear_cache.assert_not_called()


class TestLatestScreenshotData(unittest.TestCase):
    def test_returns_screenshot_and_registration_state(self) -> None:
        server_tools = ServerTools.__new__(ServerTools)
        server_tools.expense_handler = Mock(
            get_ocr_expense=Mock(return_value={})
        )
        with (
            patch(
                "expense.api.server_tools.get_latest_screenshot",
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
            "expense.api.server_tools.get_latest_screenshot",
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
        with patch("expense.api.server_tools.dt.datetime") as datetime_mock:
            datetime_mock.today.return_value = fixed_now
            result = server_tools.generate_report_summary(df)

        self.assertEqual(result["today_total"], 500)
        self.assertEqual(result["monthly_total"], 600)
        self.assertEqual(result["prev_monthly_total"], 400)


class TestSimulationAverages(unittest.TestCase):
    def test_uses_regular_and_investment_income_only(self) -> None:
        records = [
            {
                "date": "2026-07-10",
                "expense_type": "給与",
                "expense_amount": 300_000,
            },
            {
                "date": "2026-07-15",
                "expense_type": "配当",
                "expense_amount": 50_000,
            },
            {
                "date": "2026-07-20",
                "expense_type": "賞与",
                "expense_amount": 1_000_000,
            },
            {
                "date": "2026-07-25",
                "expense_type": "譲渡益",
                "expense_amount": 2_000_000,
            },
            {
                "date": "2026-07-25",
                "expense_type": "生活防衛資金",
                "expense_amount": 100_000,
            },
        ]

        result = get_simulation_averages(
            records,
            ["給与", "配当"],
            ["生活防衛資金", "賞与", "譲渡益"],
            dt.date(2026, 8, 25),
            1,
        )

        self.assertEqual(result, (35, 0, 35))


class TestLocalOnlyExpenseTypes(unittest.TestCase):
    def test_salary_is_not_local_only(self) -> None:
        server_tools = Mock(
            irregular_income_types=["賞与"],
            investment_income_types=["配当"],
            capital_gain_types=["譲渡益"],
        )

        self.assertFalse(_is_local_only_type(server_tools, "給与"))
        self.assertFalse(_is_local_only_type(server_tools, "雑所得"))
        self.assertTrue(_is_local_only_type(server_tools, "賞与"))


if __name__ == "__main__":
    unittest.main()
