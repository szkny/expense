import logging
import os
import unittest

import pandas as pd

from src.expense.core.ocr import Ocr, get_latest_screenshot


log: logging.Logger = logging.getLogger("expense")


class OcrDiagnosticTest(unittest.TestCase):
    def test_ocr_main(self, n: int = 3, offset: int = 0) -> None:
        ocr = Ocr()
        ocr.toast_enabled = False
        ocr.notify_enabled = False
        result = []
        for i in range(n):
            try:
                screenshot_name = get_latest_screenshot(offset + i)
                expense_data = ocr.main(offset + i)
                log.info(f"OCR result (No.{i}): {expense_data}")
                expense_amount = expense_data.get("expense_amount", "")
                expense_memo = expense_data.get("expense_memo", "")
                expense_type = expense_data.get("expense_type", "")
                expense_date = expense_data.get("expense_date", "")
                result.append(
                    {
                        "screenshot_name": os.path.basename(screenshot_name),
                        "expense_date": expense_date,
                        "expense_type": expense_type,
                        "expense_amount": expense_amount,
                        "expense_memo": expense_memo,
                    }
                )
            except Exception:
                log.exception(f"Error processing screenshot (No.{i})")
        df_result = pd.DataFrame(result)
        log.info(f"OCR results:\n{df_result}")


if __name__ == "__main__":
    unittest.main()
