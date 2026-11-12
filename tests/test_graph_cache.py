from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock

from expense.api.graph_cache import get_cached_graph


class TestCachedGraph(unittest.TestCase):
    def test_reuses_graph_for_the_same_key(self) -> None:
        cache: dict = {}
        generator = Mock(return_value="<div>graph</div>")

        first = get_cached_graph(cache, threading.Lock(), ("bar",), generator)
        second = get_cached_graph(cache, threading.Lock(), ("bar",), generator)

        self.assertEqual(first, "<div>graph</div>")
        self.assertEqual(second, first)
        generator.assert_called_once_with()

    def test_generates_separate_graphs_for_different_keys(self) -> None:
        cache: dict = {}
        generator = Mock(side_effect=["light", "dark"])

        light = get_cached_graph(
            cache, threading.Lock(), ("bar", "light"), generator
        )
        dark = get_cached_graph(
            cache, threading.Lock(), ("bar", "dark"), generator
        )

        self.assertEqual((light, dark), ("light", "dark"))
        self.assertEqual(generator.call_count, 2)

    def test_generates_different_keys_concurrently(self) -> None:
        cache: dict = {}
        lock = threading.Lock()
        barrier = threading.Barrier(2, timeout=2)

        def generate(value: str) -> str:
            barrier.wait()
            return value

        with ThreadPoolExecutor(max_workers=2) as executor:
            light = executor.submit(
                get_cached_graph,
                cache,
                lock,
                ("bar", "light"),
                lambda: generate("light"),
            )
            dark = executor.submit(
                get_cached_graph,
                cache,
                lock,
                ("bar", "dark"),
                lambda: generate("dark"),
            )

            self.assertEqual((light.result(), dark.result()), ("light", "dark"))

    def test_same_key_uses_one_in_flight_generation(self) -> None:
        cache: dict = {}
        lock = threading.Lock()
        started = threading.Event()
        release = threading.Event()

        def generate() -> str:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test generation was not released")
            return "<div>graph</div>"

        generator = Mock(side_effect=generate)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                get_cached_graph, cache, lock, ("bar",), generator
            )
            self.assertTrue(started.wait(timeout=1))
            second = executor.submit(
                get_cached_graph, cache, lock, ("bar",), generator
            )
            release.set()

            self.assertEqual(first.result(), "<div>graph</div>")
            self.assertEqual(second.result(), "<div>graph</div>")

        generator.assert_called_once_with()

    def test_invalidation_does_not_reuse_or_store_old_generation(self) -> None:
        cache: dict = {}
        lock = threading.Lock()
        started = threading.Event()
        release = threading.Event()

        def generate_old() -> str:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test generation was not released")
            return "old"

        with ThreadPoolExecutor(max_workers=2) as executor:
            old_graph = executor.submit(
                get_cached_graph,
                cache,
                lock,
                ("bar",),
                generate_old,
            )
            self.assertTrue(started.wait(timeout=1))
            with lock:
                cache["graph_html"] = {}

            new_graph = executor.submit(
                get_cached_graph,
                cache,
                lock,
                ("bar",),
                lambda: "new",
            )
            self.assertEqual(new_graph.result(timeout=1), "new")
            release.set()
            self.assertEqual(old_graph.result(), "old")

        self.assertEqual(cache["graph_html"], {("bar",): "new"})


if __name__ == "__main__":
    unittest.main()
