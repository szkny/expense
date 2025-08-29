.PHONY: build install

build:
	@echo "Building the project..."
	python -m build
	@echo

install: build
	@echo "Installing the package..."
	pip install .
	@echo

serve:
	@echo "Starting the service..."
	uvicorn src.expense.api.server:app --reload
	@echo
