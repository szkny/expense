.PHONY: build install

install: build
	@echo "Installing the package..."
	pip install .
	@echo "Installation complete.\n"

build:
	@echo "Building the project..."
	python -m build
	@echo "Build complete.\n"
