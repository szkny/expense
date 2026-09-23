import datetime as dt
import json
import math
import pathlib
import threading
import urllib.error
import urllib.request
from typing import Any

from markdown_it import MarkdownIt


_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5-nano"
_MAX_OUTPUT_TOKENS = 2000
_cache_lock = threading.Lock()
_ADVICE_MARKDOWN = MarkdownIt("js-default", {"html": False}).disable("image")


class AssetAdviceConfigurationError(Exception):
    pass


class AssetAdviceRequestError(Exception):
    pass


def render_asset_advice(markdown: str) -> str:
    """Render Markdown with raw HTML and images disabled."""
    return _ADVICE_MARKDOWN.render(markdown)


def _to_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if hasattr(value, "item"):
        return _to_json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _extract_response_text(response: dict[str, Any]) -> str:
    if response.get("status") == "incomplete":
        details = response.get("incomplete_details") or {}
        reason = details.get("reason", "unknown")
        raise AssetAdviceRequestError(f"OpenAI response incomplete ({reason}).")

    text = "\n".join(
        content.get("text", "")
        for item in response.get("output", [])
        if item.get("type") == "message"
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    ).strip()
    if not text:
        status = str(response.get("status", "unknown"))[:40]
        output_types = [
            str(item.get("type", "unknown"))[:40]
            for item in response.get("output", [])
            if isinstance(item, dict)
        ]
        raise AssetAdviceRequestError(
            f"OpenAI returned no advice text (status={status}, "
            f"output_types={output_types})."
        )
    return text


def get_daily_asset_advice(
    payload: dict[str, Any],
    cache_path: pathlib.Path,
    api_key: str | None,
    today: dt.date | None = None,
    model: str = DEFAULT_MODEL,
) -> tuple[str, bool]:
    """Return today's cached advice or request a new response from OpenAI."""
    advice_date = (today or dt.date.today()).isoformat()
    cache_file = cache_path / "asset_advice.json"

    with _cache_lock:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if (
                cached.get("date") == advice_date
                and cached.get("model") == model
                and isinstance(cached.get("advice"), str)
            ):
                return cached["advice"], True
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass

        if not api_key:
            raise AssetAdviceConfigurationError(
                "OPENAI_API_KEYが設定されていません。"
            )

        data = _to_json_value(payload)
        request_body = {
            "model": model,
            "instructions": (
                "あなたは日本語で回答する資産管理アシスタントです。"
                "入力された資産データだけを根拠に、Markdownで簡潔に助言してください。"
                "holdingsのnumは保有数量、acquisition/price/valuation/profit/"
                "invest_amountは円、price_dollarは米ドル、weight/roiはパーセントです。"
                "monthly_asset_historyは月次の資産推移です。"
                "直近の評価額変動が順調であれば「その調子を維持しましょう」のような感じで後押しし、"
                "下落局面ではコーチとして狼狽売りしないようにメンタルケアのコメントをしてください。"
                "データにない市場ニュースやユーザー属性を推測せず、将来の利益を保証せず、"
                "断定的な売買指示を避けてください。重要な偏りや推移を具体的な数値で示し、"
                "最後に投資判断はユーザー自身が行う旨を短く添えてください。"
            ),
            "input": json.dumps(data, ensure_ascii=False, allow_nan=False),
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "store": False,
        }
        if model.startswith("gpt-5"):
            request_body["reasoning"] = {"effort": "low"}
        request = urllib.request.Request(
            _OPENAI_RESPONSES_URL,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            advice = _extract_response_text(response_data)
        except AssetAdviceRequestError:
            raise
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            raise AssetAdviceRequestError(
                "Could not get advice from OpenAI."
            ) from None

        cache_path.mkdir(parents=True, exist_ok=True)
        temporary_file = cache_file.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps(
                {"date": advice_date, "model": model, "advice": advice},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary_file.replace(cache_file)
        return advice, False
