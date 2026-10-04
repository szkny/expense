import datetime as dt
import json
import math
import pathlib
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
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


def _request_body(
    payload: dict[str, Any], model: str, stream: bool = False
) -> dict[str, Any]:
    data = _to_json_value(payload)
    body: dict[str, Any] = {
        "model": model,
        "instructions": (
            "あなたはプロフェッショナルな資産管理アドバイザーです。"
            "入力された資産データだけを根拠に、日本語、Markdownで簡潔にアドバイスしてください。"
            "MarkdownはトピックごとにH2タグの見出しを設け、太字、箇条書き、表などを使った分かりやすい表現を心がけてください。"
            "\n\n"
            "holdingsのnumは保有数量、acquisition/price/valuation/profit/"
            "invest_amountは円、price_dollarは米ドル、weight/roiはパーセントです。"
            "monthly_asset_historyは月次の資産推移です。"
            "\n\n"
            "資産総額や純利益、ドローダウン、資産配分など、与えられたデータは、"
            "あなたのアドバイスを掲載するアプリ上にすでに整理されているため、"
            "資産概況や要点を整理しなおしたり、出力しないでください。"
            "インサイトやアドバイスを中心に出力してください。"
            "\n\n"
            "直近の評価額変動が順調であれば、その調子を維持しましょう、のような感じで後押しし、"
            "下落局面ではコーチとして狼狽売りしないようにメンタルケアのコメントをしてください。"
            "\n\n"
            "データにない市場ニュースやユーザー属性を推測せず、将来の利益を保証せず、"
            "断定的な売買指示を避けてください。"
            "重要な偏りや推移が確認された場合はアラートとしてユーザーに報告してください。"
            "最後に投資判断はユーザー自身が行う旨を短く添えてください。"
        ),
        "input": json.dumps(data, ensure_ascii=False, allow_nan=False),
        "max_output_tokens": _MAX_OUTPUT_TOKENS,
        "store": False,
    }
    if model.startswith("gpt-5"):
        body["reasoning"] = {"effort": "low"}
    if stream:
        body["stream"] = True
    return body


def _make_request(
    payload: dict[str, Any], api_key: str, model: str, stream: bool = False
) -> urllib.request.Request:
    return urllib.request.Request(
        _OPENAI_RESPONSES_URL,
        data=json.dumps(
            _request_body(payload, model, stream), ensure_ascii=False
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )


def get_daily_asset_advice(
    payload: dict[str, Any],
    cache_path: pathlib.Path,
    api_key: str | None,
    today: dt.date | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
) -> tuple[str, bool]:
    """Return today's cached advice or request a new response from OpenAI."""
    advice_date = (today or dt.date.today()).isoformat()
    cache_file = cache_path / "asset_advice.json"

    with _cache_lock:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if not force and (
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

        request = _make_request(payload, api_key, model)

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


def stream_daily_asset_advice(
    payload: dict[str, Any],
    cache_path: pathlib.Path,
    api_key: str | None,
    today: dt.date | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
) -> Iterator[tuple[str, bool, bool]]:
    """Yield rendered advice as OpenAI output deltas arrive."""
    advice_date = (today or dt.date.today()).isoformat()
    cache_file = cache_path / "asset_advice.json"

    with _cache_lock:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if not force and (
                cached.get("date") == advice_date
                and cached.get("model") == model
                and isinstance(cached.get("advice"), str)
            ):
                yield render_asset_advice(cached["advice"]), True, True
                return
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            pass

        if not api_key:
            raise AssetAdviceConfigurationError(
                "OPENAI_API_KEYが設定されていません。"
            )

        advice_parts: list[str] = []
        request = _make_request(payload, api_key, model, stream=True)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                for raw_line in iter(response.readline, b""):
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    event_data = line[5:].strip()
                    if event_data == "[DONE]":
                        break
                    try:
                        event = json.loads(event_data)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if isinstance(delta, str) and delta:
                            advice_parts.append(delta)
                            yield render_asset_advice(
                                "".join(advice_parts)
                            ), False, False
                    elif event.get("type") == "response.incomplete":
                        reason = (
                            (event.get("response") or {})
                            .get("incomplete_details", {})
                            .get("reason", "unknown")
                        )
                        raise AssetAdviceRequestError(
                            f"OpenAI response incomplete ({reason})."
                        )
        except AssetAdviceRequestError:
            raise
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            TypeError,
            ValueError,
        ):
            raise AssetAdviceRequestError(
                "Could not get advice from OpenAI."
            ) from None

        advice = "".join(advice_parts).strip()
        if not advice:
            raise AssetAdviceRequestError("OpenAI returned no advice text.")
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
        yield render_asset_advice(advice), True, False
