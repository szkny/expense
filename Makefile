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

test:
	@echo "Running tests..."
	python -m unittest tests/test_*.py
	@echo

clean:
	@echo "Cleaning up build artifacts..."
	rm -rf build dist *.egg-info
	@echo
