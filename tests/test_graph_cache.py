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


if __name__ == "__main__":
    unittest.main()
