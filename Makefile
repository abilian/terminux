.PHONY: all help run test test-cov lint check format build publish clean \
	frontend frontend-dev frontend-test frontend-cov \
	build-macos build-linux docker-run docs docs-serve

all: frontend test lint  ## Build the frontend, then run every test and linter

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Run & develop

run:  ## Launch the desktop app from source
	uv run terminux

# The build output is committed to src/terminux/web/static; rebuild and
# commit it alongside any frontend source change.
frontend:  ## Build the web UI into the Python package (after frontend changes)
	cd frontend && npm ci && npm run build

frontend-dev:  ## Live-reload UI dev server; pair with `uv run terminux --no-window`
	cd frontend && npm run dev

##@ Test & check

test: frontend-test  ## Run every test: frontend unit, then Python unit/integration/e2e
	uv run pytest

frontend-test:  ## Frontend unit tests only (vitest; fast, no browser)
	cd frontend && npm run test

frontend-cov:  ## Frontend test coverage (HTML report in frontend/coverage/)
	cd frontend && npm run test:cov

test-cov:  ## Python test coverage (HTML report in htmlcov/)
	uv run pytest --cov=terminux --cov-report=html --cov-report=term tests

lint:  ## All linters and type checkers (ruff, ty, pyrefly, strict mypy)
	uv run --active ruff check
	uv run --active ruff format --check
	uv run --active ty check src
	uv run --active pyrefly check src
	uv run --active mypy src

check: lint  ## Alias for lint

format:  ## Auto-format all Python and frontend code
	uv run --active ruff format src tests
	uv run --active ruff check src tests --fix
	uv run --active ruff format src tests
	cd frontend && npm run format

##@ Package & ship

build-macos: frontend  ## macOS .app bundle -> dist/terminux.app
	uv run --active pyinstaller --noconfirm --clean terminux.spec

build-linux:  ## Linux bundle, built in Docker -> dist/linux/terminux/
	docker build --target bundle -t terminux:bundle .
	rm -rf dist/linux && mkdir -p dist/linux
	docker create --name terminux_extract terminux:bundle >/dev/null
	docker cp terminux_extract:/app/dist/terminux dist/linux/terminux
	docker rm terminux_extract >/dev/null
	@echo "Linux bundle: dist/linux/terminux/terminux"

docker-run:  ## Try terminux in a container (web mode on http://localhost:8000)
	docker build --target bundle -t terminux:bundle .
	docker run --rm -p 8000:8000 terminux:bundle

build: clean frontend  ## Python package (wheel + sdist) -> dist/
	uv build

publish: build  ## Publish the Python package
	uv publish

##@ Documentation

docs:  ## Build the documentation site -> docs/site/
	uv run zensical build -f docs/zensical.toml

docs-serve:  ## Preview the docs with live reload at http://127.0.0.1:8000
	uv run zensical serve -f docs/zensical.toml

##@ Housekeeping

clean:  ## Delete caches and build artifacts
	rm -rf .pytest_cache .ruff_cache dist build __pycache__ .mypy_cache \
		.coverage htmlcov .coverage.* *.egg-info
	adt clean
