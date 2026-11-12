from concurrent.futures import Future
import threading
from typing import Any, Callable


def get_cached_value(
    cache: dict,
    lock: threading.Lock,
    namespace: str,
    key: tuple[Any, ...],
    generator: Callable[[], Any],
    value_cache: dict | None = None,
) -> Any:
    """同じキャッシュスナップショットの値生成を一度にまとめる。"""
    with lock:
        values = (
            value_cache
            if value_cache is not None
            else cache.setdefault(namespace, {})
        )
        if key in values:
            return values[key]

        inflight_by_namespace = cache.setdefault("_singleflight", {})
        state_key = (namespace, id(values))
        state = inflight_by_namespace.get(state_key)
        if state is None or state["values"] is not values:
            state = {"values": values, "futures": {}}
            inflight_by_namespace[state_key] = state
        inflight: dict[tuple[Any, ...], Future[Any]] = state["futures"]
        future = inflight.get(key)
        is_generator = future is None
        if future is None:
            future = Future()
            inflight[key] = future

    if not is_generator:
        return future.result()

    try:
        generated_value = generator()
    except BaseException as error:
        with lock:
            current_state = cache.get("_singleflight", {}).get(state_key)
            if current_state is state and inflight.get(key) is future:
                inflight.pop(key)
                if not inflight:
                    cache["_singleflight"].pop(state_key)
        future.set_exception(error)
        raise

    with lock:
        if cache.get(namespace) is values:
            result = values.setdefault(key, generated_value)
        else:
            # データ更新後に古いスナップショットの結果を保存しない。
            result = generated_value
        current_state = cache.get("_singleflight", {}).get(state_key)
        if current_state is state and inflight.get(key) is future:
            inflight.pop(key)
            if not inflight:
                cache["_singleflight"].pop(state_key)

    future.set_result(result)
    return result


def get_cached_graph(
    cache: dict,
    lock: threading.Lock,
    key: tuple[Any, ...],
    generator: Callable[[], Any],
) -> Any:
    """同じデータスナップショットから生成したグラフHTMLを再利用する。"""
    return get_cached_value(cache, lock, "graph_html", key, generator)
