import json
import pathlib
import subprocess
import logging as log
from typing import Any
from platformdirs import user_config_dir

APP_NAME: str = "expense"

CONFIG_PATH: pathlib.Path = pathlib.Path(user_config_dir(APP_NAME))
CONFIG_PATH.mkdir(parents=True, exist_ok=True)

try:
    with open(CONFIG_PATH / "config.json", "r") as f:
        CONFIG: dict[str, Any] = json.load(f)
except Exception:
    log.debug(
        f"Error occurred when loading config file. ({CONFIG_PATH / 'config.json'})"
    )
    CONFIG = {}
EXPENSE_TYPES_ALL: dict[str, list] = CONFIG.get("expense_types", {})
INCOME_TYPES: list[str] = EXPENSE_TYPES_ALL.get("income", [])
FIXED_TYPES: list[str] = EXPENSE_TYPES_ALL.get("fixed", [])
VARIABLE_TYPES: list[str] = EXPENSE_TYPES_ALL.get("variable", [])
EXPENSE_TYPES: list[str] = VARIABLE_TYPES + FIXED_TYPES + INCOME_TYPES


def exec_command(command: list, timeout: int = 60, env: dict = {}) -> Any:
    """
    utility method for shell command execution
    """
    # funcname = inspect.currentframe()
    log.info("start 'exec_command' method")
    log.debug(f"execute command: {command}")
    res = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=env if env else None,
    )
    json_str = res.stdout.decode("utf-8")
    log.debug(f"command output: {json_str}")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise e
    if data.get("code", 0) == -2:
        log.debug(f"data: {data}")
        raise Exception("入力がキャンセルされました。")
    elif ("-n" in command) and data.get("text", "yes") in (
        "",
        "no",
    ):
        log.debug(f"data: {data}")
        raise Exception("入力がキャンセルされました。")
    log.info("end 'exec_command' method")
    return data


def select_expense_type(
    item_list: list[dict[str, Any]] = [],
) -> str:
    """
    select expense type
    """
    log.info("start 'select_expense_type' method")
    items_list_str = ",".join(EXPENSE_TYPES)
    additional_items = ""
    for item_data in item_list:
        items: list[dict] = item_data.get("items", [])
        icon: str = item_data.get("icon", "")
        if len(items):
            items_str = ",".join(
                [
                    f'{icon} {i["expense_type"]}/{i["expense_memo"]}/¥{i["expense_amount"]}'
                    for i in items
                ]
            )
            if len(additional_items):
                items_str = "," + items_str
            additional_items += items_str
    if additional_items:
        additional_items = additional_items.replace("//", "/")
        items_list_str = additional_items + "," + items_list_str
    data = exec_command(
        [
            "termux-dialog",
            "sheet",
            "-t",
            APP_NAME,
            "-v",
            items_list_str,
        ]
    )
    expense_type = str(data["text"])
    log.debug(f"expense_type: {expense_type}")
    log.info("end 'select_expense_type' method")
    return expense_type


def enter_expense_amount(expense_type: str) -> int:
    """
    enter expense amount
    """
    log.info("start 'enter_expense_amount' method")
    data = exec_command(
        [
            "termux-dialog",
            "text",
            "-t",
            APP_NAME,
            "-i",
            f"{expense_type}の金額を入力",
            "-n",
        ]
    )
    expense_amount = int(data["text"])
    log.debug(f"expense_amount: {expense_amount}")
    log.info("end 'enter_expense_amount' method")
    return expense_amount


def enter_expense_memo(expense_type: str) -> str:
    """
    enter expense memo
    """
    log.info("start 'enter_expense_memo' method")
    data = exec_command(
        [
            "termux-dialog",
            "text",
            "-t",
            APP_NAME,
            "-i",
            f"{expense_type}のメモを入力",
        ]
    )
    expense_memo = str(data["text"])
    log.debug(f"expense_memo: {expense_memo}")
    log.info("end 'enter_expense_memo' method")
    return expense_memo


def confirmation(content: str) -> bool:
    """
    confirmation
    """
    log.info("start 'confirmation' method")
    data = exec_command(
        [
            "termux-dialog",
            "confirm",
            "-t",
            APP_NAME,
            "-i",
            content,
        ]
    )
    choice = str(data["text"])
    log.debug("choice: " + choice)
    log.info("end 'confirmation' method")
    return choice == "yes"


def toast(content: str, timeout: int = 5) -> None:
    """
    toast popup message
    """
    log.info("start 'toast' method")
    notify_command = [
        "termux-toast",
        "-b",
        "black",
        "-g",
        "top",
        content,
    ]
    log.debug(f"execute command: {notify_command}")
    subprocess.run(
        notify_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    log.info("end 'toast' method")


def notify(title: str, content: str, timeout: int = 30) -> None:
    """
    notification
    """
    log.info("start 'notify' method")
    notify_command = [
        "termux-notification",
        "--title",
        title,
        "--content",
        content,
    ]
    log.debug(f"execute command: {notify_command}")
    subprocess.run(
        notify_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    log.info("end 'notify' method")
