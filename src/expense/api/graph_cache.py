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
        if key not in graph_html:
            graph_html[key] = generator()
        return graph_html[key]
