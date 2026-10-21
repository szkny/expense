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
_INVESTMENT_QUOTES = (
    "卵を一つの籠に盛るな。",
    "強気相場は悲観の中に生まれ、懐疑の中で育つ。",
    "市場は短期では投票機、長期では計量機。",
    "分散は投資の唯一のただ飯。",
    "時間は市場にいる人の味方である。",
    "価格は支払うもの、価値は受け取るもの。",
    "大きな利益は、売買ではなく待つことから生まれる。",
    "最も危険な言葉は、今回は違う、である。",
    "複利は時間を味方につける。",
    "投資の成功は、予測よりも継続にかかっている。",
    "良い投資は、退屈に見えることが多い。",
    "長く持てないものを、短く持ってもいけない。",
    "市場に居続けることが、長期投資の基本である。",
    "価値ある資産を、十分な時間持ち続ける。",
    "今日の値動きより、明日の価値を見る。",
    "積み立ては、相場を予測しない投資である。",
    "投資の時間軸が長いほど、日々の雑音は小さくなる。",
)


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


def _daily_investment_quote(payload: dict[str, Any]) -> str:
    """Return a deterministic quote for the date used by the advice request."""
    as_of = payload.get("as_of")
    try:
        day = dt.date.fromisoformat(str(as_of))
    except (TypeError, ValueError):
        day = dt.date.today()
    return _INVESTMENT_QUOTES[day.toordinal() % len(_INVESTMENT_QUOTES)]


def _generated_at() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _cached_generated_at(
    cache_file: pathlib.Path, cached: dict[str, Any]
) -> str | None:
    generated_at = cached.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        return generated_at
    try:
        return dt.datetime.fromtimestamp(
            cache_file.stat().st_mtime, tz=dt.timezone.utc
        ).isoformat(timespec="seconds")
    except OSError:
        return None


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
    if isinstance(data, dict):
        data["daily_investment_quote"] = _daily_investment_quote(payload)
    body: dict[str, Any] = {
        "model": model,
        "instructions": (
            "あなたはプロフェッショナルな資産管理アドバイザーです。"
            "入力された資産データだけを根拠に、日本語、Markdownで簡潔にアドバイスしてください。"
            "MarkdownはトピックごとにH2タグの見出しを設け、太字、箇条書き、表などを使った分かりやすい表現を心がけてください。"
            "\n\n"
            "holdingsのnumは保有数量、acquisition/price/valuation/profit/"
            "invest_amountは円、price_dollarは米ドル、weight/roiはパーセントです。"
            "monthly_asset_historyは月次の資産推移、"
            "recent_daily_asset_historyは直近の日次資産推移です。"
            "\n\n"
            "出力は次の5つのH2見出しをこの順番で必ず含めてください。"
            "「今日のアドバイス」「今週の振り返り」「過去データからの小さな発見」"
            "「投資の格言」「今日の問い」。"
            "各セクションは1〜3個の短い段落または箇条書きにしてください。"
            "\n\n"
            "資産総額や純利益、ドローダウン、資産配分など、与えられたデータは、"
            "あなたのアドバイスを掲載するアプリ上にすでに整理されているため、"
            "資産概況や要点を整理しなおしたり、出力しないでください。"
            "今日のアドバイスでは、数値の再掲ではなく、データから読み取れる意味や"
            "具体的な心構えを中心に書いてください。"
            "今週の振り返りでは、利用可能な直近データrecent_daily_asset_historyから最近の傾向を要約してください。"
            "週次データがない場合は、週次の数値を推測せず、その制約を短く明記してください。"
            "過去データからの小さな発見では、monthly_asset_historyまたは"
            "recent_daily_asset_historyの実在する推移だけを使い、"
            "過去最高・変化・回復などの具体的な特徴を1つだけ取り上げてください。"
            "投資の格言では、daily_investment_quoteに与えた格言を改変せず、"
            "Markdownの引用ブロック（>）でそのまま引用してください。"
            "出典や人物名を推測して付け加えないでください。"
            "今日の問いでは、ユーザーが自分の投資方針を考えられる問いを1つだけ提示してください。"
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
                {
                    "date": advice_date,
                    "model": model,
                    "advice": advice,
                    "generated_at": _generated_at(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary_file.replace(cache_file)
        return advice, False


def _iter_response_deltas(response: Any) -> Iterator[str]:
    """Yield text deltas from an OpenAI Responses API SSE stream."""
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
                yield delta
        elif event.get("type") == "response.incomplete":
            reason = (
                (event.get("response") or {})
                .get("incomplete_details", {})
                .get("reason", "unknown")
            )
            raise AssetAdviceRequestError(
                f"OpenAI response incomplete ({reason})."
            )


def stream_daily_asset_advice(
    payload: dict[str, Any],
    cache_path: pathlib.Path,
    api_key: str | None,
    today: dt.date | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
) -> Iterator[tuple[str, bool, bool, str | None]]:
    """Yield rendered advice, completion status, cache status, and generation time."""
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
                yield (
                    render_asset_advice(cached["advice"]),
                    True,
                    True,
                    _cached_generated_at(cache_file, cached),
                )
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
                for delta in _iter_response_deltas(response):
                    advice_parts.append(delta)
                    yield render_asset_advice(
                        "".join(advice_parts)
                    ), False, False, None
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
        generated_at = _generated_at()
        cache_path.mkdir(parents=True, exist_ok=True)
        temporary_file = cache_file.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps(
                {
                    "date": advice_date,
                    "model": model,
                    "advice": advice,
                    "generated_at": generated_at,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary_file.replace(cache_file)
        yield render_asset_advice(advice), True, False, generated_at
