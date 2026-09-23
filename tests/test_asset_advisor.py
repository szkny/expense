import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.expense.api.asset_advisor import (
    AssetAdviceConfigurationError,
    AssetAdviceRequestError,
    get_daily_asset_advice,
    render_asset_advice,
)
from src.expense.api import server


class TestDailyAssetAdvice(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name)
        self.today = dt.date(2026, 9, 23)
        self.payload = {"holdings": [{"ticker": "TEST", "valuation": 1000}]}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_requests_and_caches_markdown_for_the_day(self) -> None:
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "## 今日の状況\n長期推移",
                        }
                    ],
                }
            ]
        }
        with patch(
            "src.expense.api.asset_advisor.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(response_body).encode()),
        ) as urlopen:
            advice, cached = get_daily_asset_advice(
                self.payload,
                self.cache_path,
                "test-key",
                today=self.today,
            )
            second_advice, second_cached = get_daily_asset_advice(
                self.payload,
                self.cache_path,
                "test-key",
                today=self.today,
            )

        self.assertEqual(advice, "## 今日の状況\n長期推移")
        self.assertFalse(cached)
        self.assertEqual(second_advice, advice)
        self.assertTrue(second_cached)
        urlopen.assert_called_once()
        request_body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(request_body["model"], "gpt-5-nano")
        self.assertEqual(request_body["max_output_tokens"], 2000)
        self.assertEqual(request_body["reasoning"], {"effort": "low"})
        self.assertEqual(request_body["store"], False)
        cached_data = json.loads(
            (self.cache_path / "asset_advice.json").read_text(encoding="utf-8")
        )
        self.assertEqual(cached_data["date"], self.today.isoformat())
        self.assertEqual(cached_data["model"], "gpt-5-nano")
        self.assertNotIn("holdings", cached_data)

    def test_requests_a_new_comment_on_a_new_day(self) -> None:
        self.cache_path.joinpath("asset_advice.json").write_text(
            json.dumps({"date": "2026-09-22", "advice": "昨日"}),
            encoding="utf-8",
        )
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "今日"}],
                }
            ]
        }
        with patch(
            "src.expense.api.asset_advisor.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(response_body).encode()),
        ) as urlopen:
            advice, cached = get_daily_asset_advice(
                self.payload,
                self.cache_path,
                "test-key",
                today=self.today,
            )

        self.assertEqual(advice, "今日")
        self.assertFalse(cached)
        urlopen.assert_called_once()

    def test_requests_a_new_comment_when_model_changes(self) -> None:
        self.cache_path.joinpath("asset_advice.json").write_text(
            json.dumps(
                {
                    "date": self.today.isoformat(),
                    "model": "gpt-4.1-mini",
                    "advice": "別モデルの結果",
                }
            ),
            encoding="utf-8",
        )
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "GPT-5の助言"}],
                }
            ]
        }
        with patch(
            "src.expense.api.asset_advisor.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(response_body).encode()),
        ) as urlopen:
            advice, cached = get_daily_asset_advice(
                self.payload,
                self.cache_path,
                "test-key",
                today=self.today,
                model="gpt-5-nano",
            )

        self.assertEqual(advice, "GPT-5の助言")
        self.assertFalse(cached)
        urlopen.assert_called_once()

    def test_force_requests_a_new_comment_when_daily_cache_exists(self) -> None:
        self.cache_path.joinpath("asset_advice.json").write_text(
            json.dumps(
                {
                    "date": self.today.isoformat(),
                    "model": "gpt-5-nano",
                    "advice": "キャッシュ済み",
                }
            ),
            encoding="utf-8",
        )
        response_body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "再生成結果"}],
                }
            ]
        }
        with patch(
            "src.expense.api.asset_advisor.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(response_body).encode()),
        ) as urlopen:
            advice, cached = get_daily_asset_advice(
                self.payload,
                self.cache_path,
                "test-key",
                today=self.today,
                force=True,
            )

        self.assertEqual(advice, "再生成結果")
        self.assertFalse(cached)
        urlopen.assert_called_once()
        cached_data = json.loads(
            (self.cache_path / "asset_advice.json").read_text(encoding="utf-8")
        )
        self.assertEqual(cached_data["advice"], "再生成結果")

    def test_incomplete_response_reports_the_reason_without_caching(
        self,
    ) -> None:
        response_body = {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "reasoning"}],
        }
        with patch(
            "src.expense.api.asset_advisor.urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(response_body).encode()),
        ):
            with self.assertRaisesRegex(
                AssetAdviceRequestError, r"incomplete \(max_output_tokens\)"
            ):
                get_daily_asset_advice(
                    self.payload,
                    self.cache_path,
                    "test-key",
                    today=self.today,
                )

        self.assertFalse((self.cache_path / "asset_advice.json").exists())

    def test_renders_markdown_and_sanitizes_unsafe_content(self) -> None:
        rendered = render_asset_advice(
            "## Summary\n\n**Bold** and [unsafe](javascript:alert(1))."
            "\n\n<script>alert(1)</script>\n\n"
            "![tracking pixel](https://example.test/pixel.png)"
        )

        self.assertIn("<h2>Summary</h2>", rendered)
        self.assertIn("<strong>Bold</strong>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn('<a href="javascript:', rendered)

    def test_requires_an_api_key_when_no_daily_cache_exists(self) -> None:
        with self.assertRaises(AssetAdviceConfigurationError):
            get_daily_asset_advice(
                self.payload,
                self.cache_path,
                None,
                today=self.today,
            )


class TestAssetAdviceEndpoint(unittest.TestCase):
    def test_includes_monthly_history_and_current_asset_data(self) -> None:
        df_summary = pd.DataFrame([{"total": 1200.0, "drawdown": -3.0}])
        df_items = pd.DataFrame([{"ticker": "TEST", "valuation": 1200.0}])
        df_history = pd.DataFrame(
            [
                {
                    "date": "2026-08-31",
                    "invest_amount": 1000.0,
                    "valuation": 1200.0,
                    "profit": 200.0,
                    "roi": 20.0,
                }
            ]
        )
        df_market = pd.DataFrame(
            [{"ticker": "TEST", "change_pct_monthly": 2.0}]
        )
        with (
            patch(
                "src.expense.api.server.asset_manager.config",
                {
                    "asset_management": {
                        "allocation": {"target_weights": {}},
                        "ai_advisor": {"model": "gpt-5-nano"},
                    }
                },
            ),
            patch(
                "src.expense.api.server.get_cached_asset_table",
                return_value=(df_summary, df_items, df_history, df_market),
            ),
            patch(
                "src.expense.api.server.asset_manager.build_asset_allocation",
                return_value=[],
            ),
            patch(
                "src.expense.api.server.get_daily_asset_advice",
                return_value=("今日の助言", False),
            ) as get_advice,
            patch("src.expense.api.server.os.getenv", return_value="test-key"),
        ):
            response = server.get_asset_advice()

        payload = get_advice.call_args.args[0]
        self.assertEqual(payload["holdings"][0]["ticker"], "TEST")
        self.assertEqual(
            payload["monthly_asset_history"][0]["date"], "2026-08-31"
        )
        self.assertEqual(
            payload["market_indicators"][0]["change_pct_monthly"], 2.0
        )
        self.assertEqual(get_advice.call_args.kwargs["model"], "gpt-5-nano")
        self.assertIn("今日の助言", json.loads(response.body)["advice_html"])
