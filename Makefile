.PHONY: build install test coverage ocr-test

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
	LOG_LEVEL=DEBUG coverage run --source=src/expense -m unittest discover -s tests -p "test_*.py"
	coverage report -m
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
