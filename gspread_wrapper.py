import gspread
from oauth2client.service_account import ServiceAccountCredentials

# 認証情報の設定
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    "credentials.json", scope
)
client = gspread.authorize(creds)

# スプレッドシートにアクセス
spreadsheet = client.open("hoge")
worksheet = spreadsheet.sheet1  # 最初のシートを選択

# シートの内容を読み取る
data = worksheet.get_all_records()
print(data)
