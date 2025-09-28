# Expense

A household expense tracking application that runs on Termux.
It features receipt scanning via OCR, a web-based user interface, and integration with Google Sheets.

## Key Features

- **Web UI:** An intuitive web interface for adding, editing, and viewing expense records.
  - It can be installed as PWA.
- **OCR Functionality:** Automatically extracts dates and amounts from receipt images captured with your smartphone's camera.
- **Data Visualization:** Displays daily and monthly expenditures in graphs for a visual overview of your finances.
- **Asset Management:** Track the status of your assets.
- **Google Sheets Integration:** Records all data in a Google Sheet for flexible data management.

## Screenshot

<img src="images/screenshot.jpg" width="50%">

## Requirements

- Python 3.10 ~ 3.13
- Tesseract OCR
- Google Cloud Platform credentials (`credentials.json`)
- (Optional) Termux (Terminal emulator for Android)

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/szkny/expense.git
    cd expense
    ```
2.  Install the required Python packages:
    ```bash
    make install
    ```
3.  Place your Google Cloud Platform credentials file at:
    - `src/expense/config/credentials.json`

## Usage

1.  Start the web server:
    ```bash
    make serve
    ```
2.  Open `http://localhost:8000` in your web browser.
3.  (If using Termux) You can also open the web UI directly with the following command:
    ```bash
    make webui
    ```

## Configuration

The application's behavior can be customized through the `~/.config/expense/config.json` file.

| Category     | Setting                  | Description                                                                     |
| ------------ | ------------------------ | ------------------------------------------------------------------------------- |
|              | `log_level`              | Sets the logging level (e.g., "DEBUG", "INFO").                                 |
| `termux_api` | `toast`                  | Enable/disable Toast notifications on Termux.                                   |
|              | `notify`                 | Enable/disable system notifications on Termux.                                  |
| `web_ui`     | `icons`                  | Emojis used for various UI elements.                                            |
|              | `graph.color`            | Colors for each expense category in the graphs.                                 |
|              | `record_table.n_records` | Number of records to display in the history table.                              |
| `expense`    | `icons`                  | Emojis for "Favorite," "Frequent," and "Recent" items.                          |
|              | `expense_types`          | Categorization of income, fixed costs, and variable costs.                      |
|              | `exclude_types`          | Expense types to exclude from summaries.                                        |
|              | `favorites`              | Pre-defined templates for frequently registered expenses.                       |
| `ocr`        | `tesseract_config`       | Command-line options for Tesseract OCR.                                         |
|              | `regions`                | Pre-defined cropping areas for screenshots from specific apps (e.g., "PayPay"). |
|              | `normalize`              | Settings for correcting OCR results, such as similarity thresholds.             |
