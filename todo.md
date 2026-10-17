# TODO List

- [x] logger
- [x] error dialog
- [x] retry logic
- [x] show today's expenses
- [x] stop process when cancel button was pressed
- [x] show budget left when check mode
- [x] remove income from summation in check mode
- [x] add feature of frequently registred item
- [x] add feature of favorite item
- [x] drop duplicates of favorite/frequent/recent items list
- [x] scan screenshot of receipt
- [x] scan memo from 2 lines in ocr mode
- [x] implement web app (Django, Flask, FastAPI, Jinja2, etc.)
- [x] add config file
- [x] add a feature to aggregate/analyse/report past expenses
- [x] add a feature for fuzzy search of expense history
- [x] register past record with datetime
- [x] recognize date text in ocr mode
- [x] add feature to edit records
- [x] upgrade config file
- [x] add a feature to change monthes on daily chart
- [x] ~~desynchronization of loading graph~~
- [x] ~~change web UI to SPA~~
- [x] ~~add feature of undo~~
- [x] ~~adapt to deficiencies of amount for instant registeration item~~
- [x] ~~cardanalyse/improve processing time~~
  - [x] ~~desynchronization of toast and notification~~
- [x] add a feature of asset management
- [x] add a README.md
- [x] data migration from spreadsheet records
- [x] make selected target month on pie chart switchable
- [x] desynchronize of loading graph html
- [x] add past trend chart to asset management page
- [x] annual fiscal report
- [x] monthly summary report of total expenses including fixed expenses
- [x] button of reloading individual charts
- [x] add a feature of navigating asset allocation
- [x] add a feature of sorting cards in the Web UI
- [ ] add a feature of setting target budget of expenses
- [ ] button of switching between usd/jpy in asset heatmap
- [x] add drawdown history chart
- [ ] fallback to yahoo_finance when error occurred in google_finance
- [ ] manage monthly subscription
- [ ] assist user input of expense's memo using device GPS
- [ ] personalized analysis and insight / prediction report by LLM
- [ ] add a feature of validation for usage history of credit card
- [ ] optimize performance time
- [ ] add test scripts

## Developer Efficiency Roadmap

Implement these items in order. Keep each item in its own commit; do not mix
unrelated refactoring or documentation changes into the same commit. Tests must
use temporary files, fixed data, and mocks rather than real user data, Google
Sheets, Termux, or OCR device access.

- [x] Isolate test filesystem side effects. Route `Base` data, cache, config,
  and log paths to temporary directories in tests. Done when the test suite
  leaves user config and data directories untouched and still passes.
- [x] Add Web write-endpoint tests. Cover register, edit, delete, and relevant
  OCR request behavior with Sheets, history files, and Termux mocked. Cover
  success, invalid input, external failures, and cache invalidation. Done when
  these paths can be regression-tested without external writes.
- [ ] Add Google Sheets/history transformation tests. Cover fixed worksheet
  data, empty inputs, duplicate history, amount and memo edits, and conversion
  between sheet records and history records. Preserve the existing sheet
  layout and history column order.
- [ ] Stabilize Plotly chart tests. Prefer assertions against figure data and
  layout or other semantic output over serialized HTML escaping and incidental
  whitespace. Keep a small number of HTML integration checks where needed.
- [ ] Separate `ServerTools` application setup from request-time work. Mount
  static files and register app-level resources once, not on each request.
  Verify repeated requests do not add duplicate mounts or alter responses.
- [ ] Split a narrow set of responsibilities out of `server.py`. Start with
  one cohesive area (for example, write-endpoint processing or graph response
  helpers), preserving routes, response formats, and cache behavior. Add or
  retain tests before moving code.
- [ ] Share expense suggestion preparation across CLI and Web. First lock
  down favorite/frequent/recent precedence, de-duplication, and limits with
  tests; then extract shared data preparation while keeping UI formatting at
  the relevant boundary.
- [ ] Standardize source imports on the installed `expense` package. Update
  tests, patch targets, and development entry points consistently, then run
  the full suite to catch module-identity and mock-path issues.
- [ ] Reconcile README configuration documentation with
  `src/expense/config/config.json` and runtime behavior. Correct missing or
  stale names and defaults without changing configuration semantics.
- [ ] Add a standard Makefile quality-check target for the existing test,
  type, lint, Python formatting, and JavaScript formatting checks. Document
  prerequisites and commands; do not add dependencies without a demonstrated
  need.
- [ ] Document development-command side effects and coverage scope. Explain
  that OCR diagnostics require device access, identify coverage exclusions,
  and make clear that the build target cleans generated artifacts.
