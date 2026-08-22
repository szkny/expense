import unittest
import threading
from unittest.mock import Mock, patch

from src.expense.api.server import (
    _RECORD_CACHE_TTL,
    _LazyGspreadHandler,
    _clear_record_cache,
    _df_cache_record,
    _get_cached_graph,
)


class TestLazyGspreadHandler(unittest.TestCase):
    def test_connects_on_first_use_and_retries(self) -> None:
        handler = Mock()
        handler.get_spreadsheet_url.return_value = 'https://example.test'
        with (
            patch(
                'src.expense.api.server.GspreadHandler',
                side_effect=[RuntimeError('temporary'), handler],
            ) as constructor,
            patch('src.expense.api.server.time.sleep') as sleep,
        ):
            lazy_handler = _LazyGspreadHandler('book')

            self.assertEqual(
                lazy_handler.get_spreadsheet_url(), 'https://example.test'
            )
            self.assertEqual(constructor.call_count, 2)
            sleep.assert_called_once_with(1)

    def test_does_not_fail_when_sheets_are_unavailable(self) -> None:
        with (
            patch(
                'src.expense.api.server.GspreadHandler',
                side_effect=RuntimeError('unavailable'),
            ),
            patch('src.expense.api.server.time.sleep'),
        ):
            lazy_handler = _LazyGspreadHandler('book')

            self.assertEqual(lazy_handler.get_spreadsheet_url(), '')


class TestCachedGraph(unittest.TestCase):
    def test_record_cache_can_be_cleared(self) -> None:
        _df_cache_record['graph_html'] = {('bar',): '<div>graph</div>'}
        _df_cache_record['timestamp'] = 'not-a-real-timestamp'

        _clear_record_cache()

        self.assertEqual(_df_cache_record, {})

    def test_reuses_graph_for_the_same_key(self) -> None:
        cache: dict = {}
        generator = Mock(return_value="<div>graph</div>")

        first = _get_cached_graph(cache, threading.Lock(), ("bar",), generator)
        second = _get_cached_graph(cache, threading.Lock(), ("bar",), generator)

        self.assertEqual(first, "<div>graph</div>")
        self.assertEqual(second, first)
        generator.assert_called_once_with()

    def test_generates_separate_graphs_for_different_keys(self) -> None:
        cache: dict = {}
        generator = Mock(side_effect=["light", "dark"])

        light = _get_cached_graph(
            cache, threading.Lock(), ("bar", "light"), generator
        )
        dark = _get_cached_graph(
            cache, threading.Lock(), ("bar", "dark"), generator
        )

        self.assertEqual((light, dark), ("light", "dark"))
        self.assertEqual(generator.call_count, 2)

    def test_record_cache_ttl_is_five_minutes(self) -> None:
        self.assertEqual(_RECORD_CACHE_TTL, 300)


if __name__ == '__main__':
    unittest.main()
