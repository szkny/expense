# Expense 開発ガイド

この文書は、Expense リポジトリでコードを変更する開発者・エージェント向けのルールです。実装を始める前に README.md と変更対象の既存コードを確認し、既存の挙動を理解してから最小限の変更を行ってください。

## 1. 絶対に守るルール

- `src/expense/config/credentials.json`、`~/.config/expense/credentials.json`、ログ、OCRキャッシュなどの認証情報・個人データを、表示・出力・テストデータ・コミットに含めない。
- 認証情報やユーザーの家計履歴を実データでテストしない。Google Sheets、Termux、Tesseract、端末のスクリーンショットはモックまたはローカルの固定データで置き換える。
- 設定の意味、Google Sheetsのシート構造、CSV履歴の列順、APIのレスポンス形式を変更する場合は、影響範囲を確認し、必要なテストとドキュメントも同時に更新する。
- 金額・日付・年度集計の仕様を推測で変更しない。特に年度は4月始まりである。
- 外部サービスへの書き込み、履歴ファイルへの追記、OCRによる端末アクセスを、テストや開発用コマンドの実行で意図せず発生させない。
- `dist/`、`build/`、`__pycache__/`、`.mypy_cache/`、`frontend/node_modules/` などの生成物を手作業で編集・コミットしない。
- 既存の変更を破棄しない。変更前に `git status` と `git diff` を確認し、自分の変更だけを扱う。
- セキュリティ修正では、テンプレートへの値の渡し方、HTMLエスケープ、ファイルパス、外部入力の検証を優先して確認する。

## 2. アーキテクチャ

### ディレクトリ

- `src/expense/__main__.py`: `expense` CLI のエントリーポイント。引数を解析して `Expense.expense_main()` を起動する。
- `src/expense/core/`: 業務ロジックと外部連携。
  - `base.py`: `platformdirs` によるデータ・キャッシュ・設定ディレクトリ、設定読み込み、ロギングを共通化する基底クラス。
  - `expense.py`: 支出登録、履歴の読み書き、頻出・最近・お気に入り項目、年度処理。
  - `ocr.py`: スクリーンショット取得、Tesseract OCR、テキスト正規化・日付/金額抽出。
  - `gspread_wrapper.py`: Google Sheets の読み書きとリトライ。
  - `asset_manager.py`、`graph_generator.py`、`fitting.py`、`expr_analyzer.py`: 資産管理、グラフ、推定・式解析。
  - `termux_api.py`: Termux通知、入力、コマンド実行との境界。
- `src/expense/api/`: FastAPI のHTTP層。
  - `server.py`: ルート、フォーム/API処理、DataFrameキャッシュ、テンプレートレスポンス。
  - `server_tools.py`: 設定からUI用データを組み立て、静的ファイル・Jinja2テンプレートをFastAPIへ接続する。
- `src/expense/templates/`: Jinja2テンプレート。ページは `index.j2`、`asset_management.j2`、`simulator.j2` など。
- `src/expense/static/`: CSS、Vanilla JavaScript、Plotly、PWA用マニフェスト・Service Worker。
- `src/expense/config/config.json`: 配布する既定設定。実行時には `~/.config/expense/config.json` が優先される。
- `tests/`: Python標準 `unittest` によるテスト。

### データフロー

- CLIの支出登録は、入力方式（通常入力、JSON、OCR）を選択し、必要に応じて `GspreadHandler` でGoogle Sheetsへ登録した後、ローカル履歴へ保存する。
- Webリクエストは FastAPI が受け、`ServerTools` と `core` のサービスでデータを取得・集計し、Jinja2へ渡す。重い一覧データは `server.py` の約30秒キャッシュを利用する。
- Web UIの動的操作は `src/expense/static/js/` が担当し、バックエンドの既存エンドポイントとテンプレート上のデータ形式を前提とする。

## 3. 技術スタック

- Python `>=3.10,<3.14`
- setuptools と `pyproject.toml` によるパッケージング、`src` レイアウト
- FastAPI、Uvicorn、Jinja2、pandas、Plotly
- Google Sheets: gspread、google-auth、tenacity
- OCR: Tesseract、pytesseract、Pillow、Janome
- Termux連携: Termux API コマンド、Androidブラウザ起動
- フロントエンド: Jinja2で配信するHTML、CSS、Vanilla JavaScript、PWA
- テスト: Python `unittest`、モックは `unittest.mock`
- 品質管理: mypy、Ruff、Black互換のフォーマット設定

## 4. コーディング規約

- Pythonは4スペースインデント、1行80文字を基本とする。文字列は既存設定に合わせてシングルクォートを優先し、Ruff/Blackの設定を手動で上書きしない。
- 新しい関数・メソッドには戻り値と引数の型注釈を付ける。`pyproject.toml` の mypy 設定（未型付け定義の禁止など）を満たす。
- importは標準ライブラリ、外部ライブラリ、ローカルモジュールの順にまとめる。既存コードの相対import構成を維持する。
- 既存のロガー `logging.getLogger("expense")` を使い、機密情報・アクセストークン・家計の実データをログへ出さない。例外は握りつぶさず、必要な境界でログとユーザー向け通知を分ける。
- 設定値はハードコードせず `Base.config` から取得する。設定に新しい項目を追加する場合は既定値を `src/expense/config/config.json` と README.md に反映する。
- Google Sheets、ファイル、Termux、Tesseractなどの外部境界はcoreの対応モジュールに閉じ込め、集計や表示ロジックへ直接散らさない。
- DataFrameは列名・型・日付の正規化を明示し、空のDataFrameやファイル未存在時の挙動を扱う。
- HTMLへ値を埋め込むときはJinja2の自動エスケープを維持し、`Markup`を使う場合は `server_tools.py` のように入力を先にエスケープする。
- JavaScript・CSS・テンプレートを変更するときは、既存のDOM id/class、APIパラメータ、レスポンシブ表示、PWA動作を壊さない。不要なフレームワークや依存を追加しない。
- コメントはコードから読み取れない判断や外部仕様だけを書く。既存の日本語UI・ログ文言は、仕様変更がない限り不用意に英訳・改変しない。

## 5. テスト方法

### 基本コマンド

```bash
make test
```

これは `LOG_LEVEL=DEBUG python -m unittest tests/test_*.py` を実行する。個別に確認する場合は次を使う。

```bash
python -m unittest tests/test_main.py
python -m mypy src tests
ruff check .
ruff format --check .
```

### テスト方針

- 新しい業務ロジックには、正常系、空データ、ファイル未存在、境界値、例外時のテストを追加する。
- 日付・年度、金額、重複除去、OCR正規化、CSV/DataFrame変換は回帰しやすいため、入力と期待値を固定した単体テストを優先する。
- 外部依存は `unittest.mock.patch` で差し替える。Google SheetsやTermuxを使う結合確認は通常の単体テストに混ぜない。
- OCR画像を扱うテストでは端末のスクリーンショットを前提にしない。現状の `test_ocr_main` のように外部環境依存の診断処理を追加・変更する場合は、失敗を見逃さないテストとの役割を分ける。
- CSSやグラフの色、線、余白、ラベル位置など、動作や計算結果を変えない見た目のみの変更ではテストを実施しなくてよい。差分確認と必要に応じた構文・静的チェックのみ行う。
- Web層を変更したら、少なくとも対象のDataFrame/レスポンス生成関数をテストし、可能ならローカルサーバーを起動して主要ページ（`/`、`/asset_management`、`/simulator`）を手動確認する。
- サーバーの動作確認は別ターミナルで実行する。

```bash
make serve
```

Termuxでブラウザを開く場合は `make webui` を使う。実データへ接続する前に認証先と対象スプレッドシートを確認する。

## 6. Git操作のルール

- 作業開始時と終了時に `git status --short` を確認し、変更対象を明確にする。差分は `git diff` と `git diff --check` で確認する。
- コミット前にテスト・必要な静的解析を実行し、意図しない認証情報、生成物、ログ、ローカル設定が含まれていないことを確認する。
- コミットは目的ごとに小さく分ける。無関係なリファクタリングや自動整形を同じコミットへ混ぜない。
- 既存のコミット形式に合わせ、短い命令形のメッセージを使う。履歴では `feat:`、`fix:`、`refactor:`、`style:`、`docs:` などの分類と絵文字が使われているため、既存ブランチの慣例を優先する。
- `git add` は意図したファイルだけを明示し、`git add -A` で認証情報や生成物を誤って含めない。
- `git commit`、`git push`、ブランチ作成、マージ、リベース、タグ付けは依頼がある場合だけ行う。履歴の書き換えやforce pushは行わない。
- 他の作業者の変更を `reset --hard`、`checkout`、削除などで破棄しない。競合する場合は作業を止め、影響を確認してから相談する。
