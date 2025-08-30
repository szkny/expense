import asyncio
import argparse

from .core.expense import expense_main


def main() -> None:
    """
    main process
    """
    parser = argparse.ArgumentParser(
        description="家計簿スプレッドシートに自動で書き込みを行うバッチプログラム"
    )
    parser.add_argument(
        "-c",
        "--check",
        dest="check_todays_expenses",
        default=False,
        action="store_true",
        help="check today's expenses",
    )
    parser.add_argument(
        "-j",
        "--json",
        dest="json_data",
        type=str,
        default=None,
        help="expense data in JSON format",
    )
    parser.add_argument(
        "--ocr",
        dest="ocr_image",
        default=False,
        action="store_true",
        help="ocr image of the latest screenshot",
    )
    args = parser.parse_args()
    asyncio.run(expense_main(args))


if __name__ == "__main__":
    main()
