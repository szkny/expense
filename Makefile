.PHONY: build install test coverage ocr-test

# Unit coverage excludes external integrations and the OCR diagnostic module.
UNIT_COVERAGE_OMIT = src/expense/__main__.py,src/expense/api/*,src/expense/core/expr_analyzer.py,src/expense/core/gspread_wrapper.py,src/expense/core/graph_generator.py,src/expense/core/ocr.py,src/expense/core/termux_api.py

build: clean
	@echo "Building the project..."
	python -m build
	@echo

install: build
	@echo "Installing the package..."
	pip install .
	@echo

editable-install: build
	@echo "Editable-installing the package..."
	pip install -e .
	@echo

serve:
	@echo "Starting the service..."
	uvicorn src.expense.api.server:app --host 0.0.0.0 --port 8000 --log-config uvicorn_log.json --reload
	@echo

webui:
	@echo "Opening the web UI..."
	am start -a android.intent.action.VIEW -d "http://127.0.0.1:8000"
	@echo

test:
	@echo "Running tests..."
	LOG_LEVEL=DEBUG python -m unittest tests/test_*.py
	@echo

coverage:
	@echo "Running tests with coverage..."
	coverage erase
	LOG_LEVEL=DEBUG coverage run --source=src/expense --omit="$(UNIT_COVERAGE_OMIT)" -m unittest discover -s tests -p "test_*.py"
	coverage report -m --fail-under=70
	coverage html
	@echo

ocr-test:
	@echo "Running OCR diagnostic test..."
	LOG_LEVEL=DEBUG python -m unittest tests/ocr_diagnostic.py
	@echo

clean:
	@echo "Cleaning up build artifacts..."
	rm -rf build dist *.egg-info
	@echo
