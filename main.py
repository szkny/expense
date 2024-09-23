import json
from json import JSONDecodeError
import subprocess

if __name__ == "__main__":
    command = [
        "termux-dialog",
        "radio",
        "-t 'form' -v 'a,b,c'",
    ]
    command = ["termux-dialog"]
    res = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    json_str = res.stdout.decode("utf-8")
    # print(json_str)

    try:
        data = json.loads(json_str)
    except JSONDecodeError as e:
        raise e

    print("code:", data["code"])
    print("text:", data["text"])
    print("index:", data["index"])
