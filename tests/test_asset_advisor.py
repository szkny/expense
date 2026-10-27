import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from expense.api.asset_advisor import (
    AssetAdviceConfigurationError,
    AssetAdviceRequestError,
    _request_body,
    get_daily_asset_advice,
    render_asset_advice,
    stream_asset_advice_chat_reply,
)
from expense.api import server


class TestDailyAssetAdvice(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name)
        self.today = dt.date(2026, 9, 23)
        self.payload = {
            "as_of": self.today.isoformat(),
            "holdings": [{"ticker": "TEST", "valuation": 1000}],
        }

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
            "expense.api.asset_advisor.urllib.request.urlopen",
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
        request_input = json.loads(request_body["input"])
        self.assertIn("daily_investment_quote", request_input)
        self.assertIn("daily_advice_angle", request_input)
        self.assertIn("今日のアドバイス", request_body["instructions"])
        self.assertIn("今週の振り返り", request_body["instructions"])
        self.assertIn(
            "過去データからの小さな発見", request_body["instructions"]
        )
        self.assertIn("投資の格言", request_body["instructions"])
        self.assertIn("今日の問い", request_body["instructions"])
        self.assertIn("機知ある一言", request_body["instructions"])
        self.assertIn(
            "ユーザーや損失を笑いの対象にしない",
            request_body["instructions"],
        )
        self.assertIn(
            "daily_advice_angleを今日の主な切り口",
            request_body["instructions"],
        )
        self.assertIn(
            "裏付けるデータがなければ事実のように扱わず",
            request_body["instructions"],
        )
        cached_data = json.loads(
            (self.cache_path / "asset_advice.json").read_text(encoding="utf-8")
        )
        self.assertEqual(cached_data["date"], self.today.isoformat())
        self.assertEqual(cached_data["model"], "gpt-5-nano")
        self.assertNotIn("holdings", cached_data)

    def test_daily_advice_angle_changes_with_the_date(self) -> None:
        today = json.loads(
            _request_body({"as_of": "2026-09-23"}, "gpt-5-nano")["input"]
        )["daily_advice_angle"]
        tomorrow = json.loads(
            _request_body({"as_of": "2026-09-24"}, "gpt-5-nano")["input"]
        )["daily_advice_angle"]

        self.assertNotEqual(today, tomorrow)

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
            "expense.api.asset_advisor.urllib.request.urlopen",
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
            "expense.api.asset_advisor.urllib.request.urlopen",
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
            "expense.api.asset_advisor.urllib.request.urlopen",
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
            "expense.api.asset_advisor.urllib.request.urlopen",
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

    def test_chat_request_includes_advice_assets_and_conversation(self) -> None:
        response_events = [
            {
                "type": "response.output_text.delta",
                "delta": "比率の",
            },
            {
                "type": "response.output_text.delta",
                "delta": "見方です。",
            },
            {
                "type": "response.output_text.annotation.added",
                "annotation": {
                    "type": "url_citation",
                    "url": "https://www.fsa.go.jp/",
                    "title": "金融庁",
                },
            },
        ]
        response_stream = (
            "".join(
                "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                for event in response_events
            )
            + "data: [DONE]\n\n"
        )
        messages = [{"role": "user", "content": "このアドバイスを説明して"}]
        with patch(
            "expense.api.asset_advisor.urllib.request.urlopen",
            return_value=io.BytesIO(response_stream.encode()),
        ) as urlopen:
            reply = list(
                stream_asset_advice_chat_reply(
                    self.payload,
                    "## 今日のアドバイス\n配分を確認しましょう。",
                    messages,
                    "test-key",
                )
            )

        self.assertEqual(
            reply,
            [
                ("delta", "比率の"),
                ("delta", "見方です。"),
                (
                    "citation",
                    {
                        "type": "url_citation",
                        "url": "https://www.fsa.go.jp/",
                        "title": "金融庁",
                    },
                ),
            ],
        )
        request_body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(request_body["store"], False)
        self.assertEqual(request_body["stream"], True)
        self.assertEqual(request_body["max_output_tokens"], 3000)
        self.assertEqual(
            request_body["tools"],
            [{"type": "web_search", "search_context_size": "low"}],
        )
        self.assertEqual(request_body["tool_choice"], "auto")
        self.assertIn(
            "回答に必要なデータが不足していても",
            request_body["instructions"],
        )
        self.assertIn(
            "最新の公開情報が必要な場合",
            request_body["instructions"],
        )
        self.assertIn(
            "今日の日付はasset_data.as_ofを基準",
            request_body["instructions"],
        )
        self.assertIn(
            "モデル自身の現在日付やUTCの日付で上書きしない",
            request_body["instructions"],
        )
        self.assertIn(
            "最初に『〇〇のデータがないため",
            request_body["instructions"],
        )
        chat_input = json.loads(request_body["input"])
        self.assertEqual(chat_input["asset_data"], self.payload)
        self.assertEqual(
            chat_input["daily_advice"],
            "## 今日のアドバイス\n配分を確認しましょう。",
        )
        self.assertEqual(chat_input["conversation"], messages)

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
        df_daily_history = pd.DataFrame(
            [
                {
                    "date": "2026-09-22",
                    "invest_amount": 1000.0,
                    "valuation": 1210.0,
                    "profit": 210.0,
                }
            ]
        )
        df_market = pd.DataFrame(
            [{"ticker": "TEST", "change_pct_monthly": 2.0}]
        )
        with (
            patch(
                "expense.api.server.asset_manager.config",
                {
                    "asset_management": {
                        "allocation": {"target_weights": {}},
                        "ai_advisor": {"model": "gpt-5-nano"},
                    }
                },
            ),
            patch(
                "expense.api.server.get_cached_asset_table",
                return_value=(df_summary, df_items, df_history, df_market),
            ),
            patch(
                "expense.api.server.get_cached_asset_history_records",
                return_value=df_daily_history,
            ),
            patch(
                "expense.api.server.asset_manager.build_asset_allocation",
                return_value=[],
            ),
            patch(
                "expense.api.server.get_daily_asset_advice",
                return_value=("今日の助言", False),
            ) as get_advice,
            patch("expense.api.server.os.getenv", return_value="test-key"),
        ):
            response = server.get_asset_advice()

        payload = get_advice.call_args.args[0]
        self.assertEqual(payload["holdings"][0]["ticker"], "TEST")
        self.assertEqual(
            payload["monthly_asset_history"][0]["date"], "2026-08-31"
        )
        self.assertEqual(
            payload["recent_daily_asset_history"][0]["date"], "2026-09-22"
        )
        self.assertEqual(
            payload["market_indicators"][0]["change_pct_monthly"], 2.0
        )
        self.assertEqual(get_advice.call_args.kwargs["model"], "gpt-5-nano")
        self.assertIn("今日の助言", json.loads(response.body)["advice_html"])


class TestAssetAdviceChatEndpoint(unittest.TestCase):
    def test_returns_a_sanitized_reply_with_current_asset_context(self) -> None:
        payload = {"holdings": [{"ticker": "TEST"}]}
        messages = [
            {"role": "assistant", "content": "過去の回答" * 200},
            {"role": "user", "content": "この配分を説明して"},
        ]
        with (
            patch(
                "expense.api.server._get_asset_advice_payload",
                return_value=(payload, "gpt-5-nano"),
            ),
            patch("expense.api.server.os.getenv", return_value="test-key"),
            patch(
                "expense.api.server.stream_asset_advice_chat_reply",
                return_value=iter(
                    [
                        ("delta", "**説明**\n\n"),
                        ("delta", "<script>alert(1)</script>"),
                        (
                            "citation",
                            {
                                "url": "https://www.fsa.go.jp/",
                                "title": "金融庁",
                            },
                        ),
                        (
                            "citation",
                            {
                                "url": "javascript:alert(1)",
                                "title": "不正URL",
                            },
                        ),
                    ]
                ),
            ) as get_reply,
        ):
            response = TestClient(server.app).post(
                "/api/asset_advice/chat",
                json={
                    "advice": "今日のアドバイス",
                    "messages": messages,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(len(events), 3)
        self.assertFalse(events[0]["done"])
        self.assertTrue(events[-1]["done"])
        self.assertIn("<strong>説明</strong>", events[-1]["reply_html"])
        self.assertNotIn("<script>", events[-1]["reply_html"])
        self.assertEqual(
            events[-1]["reply_markdown"].splitlines()[0], "**説明**"
        )
        self.assertEqual(
            events[-1]["sources"],
            [{"title": "金融庁", "url": "https://www.fsa.go.jp/"}],
        )
        self.assertEqual(
            get_reply.call_args.args[:3],
            (payload, "今日のアドバイス", messages),
        )
        self.assertEqual(get_reply.call_args.kwargs["model"], "gpt-5-nano")

    def test_rejects_invalid_chat_messages_before_requesting_openai(
        self,
    ) -> None:
        with patch(
            "expense.api.server.stream_asset_advice_chat_reply"
        ) as get_reply:
            for role in ("system", []):
                with self.subTest(role=role):
                    response = TestClient(server.app).post(
                        "/api/asset_advice/chat",
                        json={
                            "advice": "今日のアドバイス",
                            "messages": [
                                {"role": role, "content": "不正なロール"}
                            ],
                        },
                    )
                    self.assertEqual(response.status_code, 400)

        get_reply.assert_not_called()
