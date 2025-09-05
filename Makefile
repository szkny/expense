.PHONY: build install

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
	uvicorn src.expense.api.server:app --reload
	@echo

webui:
	@echo "Opening the web UI..."
	am start -a android.intent.action.VIEW -d "http://127.0.0.1:8000"
	@echo

test:
	@echo "Running tests..."
	LOG_LEVEL=DEBUG python -m unittest tests/test_*.py
	@echo

clean:
	@echo "Cleaning up build artifacts..."
	rm -rf build dist *.egg-info
	@echo
