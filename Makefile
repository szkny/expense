.PHONY: build install

build:
	@echo "Building the project..."
	python -m build
	@echo "Build complete.\n"

install: build
	@echo "Installing the package..."
	pip install .
	@echo "Installation complete.\n"
