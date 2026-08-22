import unittest
from unittest.mock import Mock, patch

from src.expense.api.server import _LazyGspreadHandler


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


if __name__ == '__main__':
    unittest.main()
