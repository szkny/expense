import os
import re
import glob
import json
import pathlib
import pytesseract
import unicodedata
import pandas as pd
import logging as log
from PIL import Image
from janome.tokenizer import Tokenizer
from platformdirs import user_cache_dir, user_config_dir

from .termux_api import exec_command, toast

APP_NAME = "expense"
CACHE_PATH = pathlib.Path(user_cache_dir(APP_NAME))
CONFIG_PATH = pathlib.Path(user_config_dir(APP_NAME))
CACHE_PATH.mkdir(parents=True, exist_ok=True)
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

EXPENSE_HISTORY = CACHE_PATH / f"{APP_NAME}_history.log"

HOME = pathlib.Path(os.getenv("HOME") or "~")


def ocr_main(offset: int = 0, enable_toast: bool = True) -> dict:
    """main method for OCR processing"""
    log.info("start 'ocr_main' method")
    if enable_toast:
        toast("画像解析中..")
    screenshot_name = get_latest_screenshot(offset)
    ocr_text = ocr_image(screenshot_name)
    expense_data = parse_ocr_text(ocr_text)
    expense_amount = expense_data.get("amount", "")
    expense_memo = expense_data.get("memo", "")
    if enable_toast:
        toast("支出項目解析中..")
    try:
        res = exec_command(
            [
                "expense_type_classifier",
                "--json",
                f'{{"amount": {expense_amount}, "memo": "{expense_memo}"}}',
            ]
        )
    except json.decoder.JSONDecodeError as e:
        log.error(f"JSON decode error: {e}")
        res = {}
    expense_type = res.get("predicted_type", "")
    log.info("end 'ocr_main' method")
    return {
        "expense_type": expense_type,
        "expense_amount": expense_amount,
        "expense_memo": expense_memo,
        "screenshot_name": os.path.basename(screenshot_name),
    }


def get_latest_screenshot(offset: int = 0) -> str:
    """
    get the latest screenshot file name
    """
    log.info("start 'get_latest_screenshot' method")
    screenshot_list = glob.glob(
        (HOME / "storage/dcim/Screenshots/Screenshot_*Pay.jpg").as_posix()
    )
    if len(screenshot_list) == 0:
        raise FileNotFoundError("スクリーンショットが見つかりませんでした。")
    screenshot_name = sorted(screenshot_list)[-1 - offset]
    log.debug(f"Latest screenshot: {screenshot_name}")
    log.info("end 'get_latest_screenshot' method")
    return screenshot_name


def normalize_capture_text(text: str) -> str:
    """
    normalize capture text
    """
    log.info("start 'normalized_text' method")
    normalized_text = text
    normalized_text = re.sub(
        r"[①-⑳]", lambda m: str(ord(m.group()) - ord("①") + 1), normalized_text
    )
    normalized_text = unicodedata.normalize("NFKC", normalized_text)
    normalized_text = re.sub(r"^[ -/:-@[-´{-~]", "", normalized_text)
    normalized_text = re.sub(
        r"(?<=[^A-Za-z]) (?=[^A-Za-z])",
        "",
        normalized_text,
    )
    normalized_text = re.sub(r" +([A-Za-z]) +", r"\1", normalized_text)
    pattern_nonalpha = r"[^A-Za-z]"  # non-alphabets
    pattern_alpha = r"[A-Za-z]"  # alphabets
    normalized_text = re.sub(
        f"(?<={pattern_alpha}) (?={pattern_nonalpha})", "", normalized_text
    )
    normalized_text = re.sub(
        f"(?<={pattern_nonalpha}) (?={pattern_alpha})", "", normalized_text
    )
    log.info("end 'normalized_text' method")
    return normalized_text


def ocr_image(screenshot_name: str) -> str:
    """
    perform OCR on the image
    """
    log.info("start 'ocr_image' method")
    img = Image.open(screenshot_name)

    # Define OCR regions for different payment apps
    try:
        with open(CONFIG_PATH / "ocr_regions.json", "r") as f:
            ocr_regions: dict[str, list] = json.load(f)
    except FileNotFoundError:
        ocr_regions = {}

    # Determine which regions to process based on screenshot name
    regions_to_process = {}
    for app_name, regions in ocr_regions.items():
        if app_name in screenshot_name:
            regions_to_process = {app_name: regions}
            break

    # Process regions if found, otherwise process entire image
    if regions_to_process:
        results = []
        for app_name, regions in regions_to_process.items():
            log.debug(f"Processing OCR for {app_name}")
            for i, region in enumerate(regions):
                cropped = img.crop(region)
                text = str(pytesseract.image_to_string(cropped, lang="jpn"))
                log.debug(f"\t[{i}] region: {region}, ocr text: {text}")
                results.append(text)
        text = "\n".join(results)
    else:
        text = str(pytesseract.image_to_string(img, lang="jpn"))

    log.debug(f"Raw OCR text:\n{text}")
    text = normalize_capture_text(text)
    log.debug(f"OCR text:\n{text}")
    log.info("end 'ocr_image' method")
    return text


def parse_ocr_text(ocr_text: str) -> dict:
    """
    Extract expense data (amount and memo) from OCR text
    """
    log.info("start 'parse_ocr_text' method")

    date_pattern = re.compile(
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(日)?|\d{1,2}[:時]\d{1,2}(分)?)"
    )
    text_rows = ocr_text.split("\n")

    expense_data = {
        "amount": extract_amount(text_rows, date_pattern),
        "memo": extract_memo(text_rows, date_pattern),
    }

    if expense_data["amount"]:
        log.debug(f"Extracted Expense Amount: {expense_data['amount']}")
    if expense_data["memo"]:
        log.debug(f"Extracted Expense Memo: {expense_data['memo']}")

    log.info("end 'parse_ocr_text' method")
    return expense_data


def extract_amount(
    text_rows: list[str], date_pattern: re.Pattern
) -> int | None:
    """
    Extract amount from text rows
    """
    log.info("start 'extract_amount' method")
    amount_pattern = re.compile(r"([1-9]\d{0,2}[,\.]*\d{0,3})")
    amounts = []
    for i, row in enumerate(text_rows):
        row = row.replace(" ", "")

        # Skip first two rows and empty rows
        if i < 2 or not row.strip():
            continue

        # Skip rows containing date patterns
        if date_pattern.search(row):
            continue

        # Extract amounts
        if match := amount_pattern.search(row):
            log.debug(f"Processing row {i} for amount: {row}")
            amounts.append(int(re.sub("[,.]", "", match.group(1))))

    if not amounts:
        log.debug("金額の抽出に失敗しました。")
        toast("金額の抽出に失敗しました。")
        return None

    # Filter out amounts less than or equal to 30
    amounts = list(filter(lambda x: x > 30, amounts))
    log.info("end 'extract_amount' method")
    return amounts[0]


def extract_memo(text_rows: list[str], date_pattern: re.Pattern) -> str | None:
    """
    Extract memo from text rows
    """
    log.info("start 'extract_memo' method")
    exclude_pattern = re.compile(r".*お支払い完了.*")
    memos = []
    for i, row in enumerate(text_rows):
        row = row.strip()

        # Skip empty rows
        if not row:
            continue
        # Skip rows containing date patterns
        if date_pattern.search(row):
            break
        if exclude_pattern.search(row):
            continue

        # Extract memos
        log.debug(f"Processing row {i} for memo: {row}")
        memos.append(row)

    if not memos:
        log.debug("メモの抽出に失敗しました。")
        toast("メモの抽出に失敗しました。")
        return None

    log.debug(f"Extracted memos: {memos}")
    memo = memos[0]
    # Combine first two memos
    if len(memos) > 1:
        if len(memos[0] + memos[1]) <= 30 and not (
            memos[0] in memos[1] or memos[1] in memos[0]
        ):
            memo += " " + memos[1]
        elif len(memos[0]) < len(memos[1]):
            memo = memos[1]

    memo = correct_expense_memo(memo, use_similar_word_correct=False)
    log.info("end 'extract_memo' method")
    return memo


def levenshtein(a: str, b: str) -> int:
    """
    calculate the Levenshtein distance between two strings
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    if la < lb:
        a, b = b, a
        la, lb = lb, la
    prev = list(range(lb + 1))
    cur = [0] * (lb + 1)
    for i in range(1, la + 1):
        cur[0] = i
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ai == b[j - 1] else 1
            insertion = cur[j - 1] + 1
            deletion = prev[j] + 1
            substitution = prev[j - 1] + cost
            cur[j] = min(insertion, deletion, substitution)
        prev, cur = cur, prev
    return prev[lb]


def similarity(a: str, b: str) -> float:
    """
    calculate the similarity between two strings
    """
    if len(a) == 0 and len(b) == 0:
        return 1.0
    return 1.0 - levenshtein(a, b) / max(len(a), len(b))


def get_most_similar_memo(
    target: str, memos: list[str], threshold: float = 0.9
) -> str:
    """
    get the most similar memo from a list of memos
    """
    log.info("start 'get_most_similar_memo' method")
    log.debug(f"Target memo:\t\t{target}")
    if target in memos:
        log.debug("Exact match found.")
        log.info("end 'get_most_similar_memo' method")
        return target
    most_similar_memo = ""
    highest_similarity = 0.0
    for memo in memos:
        sim = similarity(target, memo)
        if sim > highest_similarity:
            highest_similarity = sim
            most_similar_memo = memo
    log.debug(
        f"Most similar memo:\t{most_similar_memo} (similarity: {highest_similarity: .2f})"
    )
    if highest_similarity < threshold:
        most_similar_memo = ""
        log.debug(
            f"Similar memo not found above the threshold={threshold: .2f}"
        )
    else:
        log.debug(f"Similar memo found above the threshold={threshold: .2f}")
    log.info("end 'get_most_similar_memo' method")
    return most_similar_memo


def get_most_similar_word(
    target: str, words: list[str], threshold: int = 1
) -> str:
    """
    get the most similar word from a list of words
    """
    log.info("start 'get_most_similar_word' method")
    log.debug(f"Target word:\t\t{target}")
    if target in words:
        log.debug("Exact match found.")
        log.info("end 'get_most_similar_word' method")
        return target
    most_similar_word = ""
    lowest_dist = 0
    for word in words:
        leven_dist = levenshtein(target, word)
        if lowest_dist == 0 or leven_dist < lowest_dist:
            lowest_dist = leven_dist
            most_similar_word = word
    log.debug(
        f"Most similar word:\t{most_similar_word} (distance: {lowest_dist})"
    )
    if lowest_dist > threshold:
        most_similar_word = ""
        log.debug(f"Similar word not found within the threshold={threshold}")
    else:
        log.debug(f"Similar word found within the threshold={threshold}")
    log.info("end 'get_most_similar_word' method")
    return most_similar_word


def get_expense_history() -> pd.DataFrame:
    """
    get expense history as a pandas DataFrame
    """
    log.info("start 'get_expense_history' method")
    df = pd.DataFrame()
    try:
        df = pd.read_csv(EXPENSE_HISTORY, index_col=None)
    except FileNotFoundError:
        pass
    except pd.errors.EmptyDataError:
        pass
    if df.empty:
        return df
    df = df.T.reset_index().T
    df.columns = pd.Index(["date", "type", "memo", "amount"])
    df.index = pd.Index(range(len(df)))
    log.info("end 'get_expense_history' method")
    return df


def tokenize_text(text: str, tokenizer: Tokenizer) -> list[str]:
    """
    tokenize text using janome tokenizer
    """
    if not isinstance(text, str) or text.strip() == "":
        return []
    processed_text = list(tokenizer.tokenize(text, wakati=True))
    return processed_text


def get_memo_words(memos: list[str], min_len: int = 3) -> list[str]:
    """
    get unique words from memos
    """
    log.info("start 'get_memo_words' method")
    df_wakati = pd.Series(
        list(map(lambda s: tokenize_text(s, Tokenizer()), memos))
    )
    words: list[str] = df_wakati.explode().unique().tolist()
    words = [w for w in words if len(w) >= min_len]
    log.info("end 'get_memo_words' method")
    return words


def correct_expense_memo(
    expense_memo: str, use_similar_word_correct: bool = True
) -> str:
    """
    correct expense memo using expense history
    """
    log.info("start 'correct_expense_memo' method")
    if not expense_memo:
        return ""
    log.debug(f"Target expense_memo:\n{expense_memo}")
    corrected_memo = expense_memo
    df = get_expense_history()
    if df.empty or "memo" not in df.columns:
        log.info("end 'correct_expense_memo' method")
        return corrected_memo
    memos = df["memo"].dropna().unique().tolist()

    # correct memo using similar words and memos
    if use_similar_word_correct:
        vocabs = get_memo_words(memos, min_len=3)
        memo_words = tokenize_text(expense_memo, Tokenizer())
        log.debug(f"Target memo_words:\n{memo_words}")
        corrected_words = []
        for word in memo_words:
            if len(word) < 3:
                corrected_words.append(word)
                continue
            corrected_word = get_most_similar_word(word, vocabs, threshold=1)
            if corrected_word:
                corrected_words.append(corrected_word)
            else:
                corrected_words.append(word)
        corrected_memo = "".join(corrected_words)
        log.debug(f"Corrected memo after word correction:\n{corrected_memo}")

    # correct memo using similar memos
    corrected_memo2 = get_most_similar_memo(corrected_memo, memos)
    if corrected_memo2:
        corrected_memo = corrected_memo2
    log.debug(f"Corrected memo after memo correction:\n{corrected_memo}")
    log.info("end 'correct_expense_memo' method")
    return corrected_memo
