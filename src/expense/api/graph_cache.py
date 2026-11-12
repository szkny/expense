from concurrent.futures import Future
import threading
from typing import Any, Callable


def get_cached_graph(
    cache: dict,
    lock: threading.Lock,
    key: tuple[Any, ...],
    generator: Callable[[], Any],
) -> Any:
    """同じデータスナップショットから生成したグラフHTMLを再利用する。"""
    with lock:
        graph_html = cache.setdefault("graph_html", {})
        if key in graph_html:
            return graph_html[key]

        if cache.get("_graph_inflight_graph_html") is not graph_html:
            cache["_graph_inflight_graph_html"] = graph_html
            cache["_graph_inflight"] = {}
        inflight: dict[tuple[Any, ...], Future[Any]] = cache["_graph_inflight"]
        future = inflight.get(key)
        is_generator = future is None
        if future is None:
            future = Future()
            inflight[key] = future

    if not is_generator:
        return future.result()

    try:
        generated_html = generator()
    except BaseException as error:
        with lock:
            current_inflight = cache.get("_graph_inflight", {})
            if current_inflight.get(key) is future:
                current_inflight.pop(key)
        future.set_exception(error)
        raise

    with lock:
        if cache.get("graph_html") is graph_html:
            result = graph_html.setdefault(key, generated_html)
        else:
            # データ更新後に古いスナップショットの結果を保存しない。
            result = generated_html
        current_inflight = cache.get("_graph_inflight", {})
        if current_inflight.get(key) is future:
            current_inflight.pop(key)

    future.set_result(result)
    return result
