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

<table>
  <thead>
    <tr>
      <th>Category</th>
      <th>Setting</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>(General)</td>
      <td><code>log_level</code></td>
      <td>Sets the logging level (e.g., "DEBUG", "INFO").</td>
    </tr>
    <tr>
      <td rowspan="2"><code>termux_api</code></td>
      <td><code>toast</code></td>
      <td>Enable/disable Toast notifications on Termux.</td>
    </tr>
    <tr>
      <td><code>notify</code></td>
      <td>Enable/disable system notifications on Termux.</td>
    </tr>
    <tr>
      <td rowspan="3"><code>web_ui</code></td>
      <td><code>icons</code></td>
      <td>Emojis used for various UI elements.</td>
    </tr>
    <tr>
      <td><code>graph.color</code></td>
      <td>Colors for each expense category in the graphs.</td>
    </tr>
    <tr>
      <td><code>record_table.n_records</code></td>
      <td>Number of records to display in the history table.</td>
    </tr>
    <tr>
      <td rowspan="4"><code>expense</code></td>
      <td><code>icons</code></td>
      <td>Emojis for "Favorite," "Frequent," and "Recent" items.</td>
    </tr>
    <tr>
      <td><code>expense_types</code></td>
      <td>Categorization of income, fixed costs, and variable costs.</td>
    </tr>
    <tr>
      <td><code>exclude_types</code></td>
      <td>Expense types to exclude from summaries.</td>
    </tr>
    <tr>
      <td><code>favorites</code></td>
      <td>Pre-defined templates for frequently registered expenses.</td>
    </tr>
    <tr>
      <td rowspan="3"><code>ocr</code></td>
      <td><code>tesseract_config</code></td>
      <td>Command-line options for Tesseract OCR.</td>
    </tr>
    <tr>
      <td><code>regions</code></td>
      <td>Pre-defined cropping areas for screenshots from specific apps (e.g., "PayPay").</td>
    </tr>
    <tr>
      <td><code>normalize</code></td>
      <td>Settings for correcting OCR results, such as similarity thresholds.</td>
    </tr>
  </tbody>
</table>
