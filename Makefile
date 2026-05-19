.PHONY: all test build format check lint clean frontend frontend-dev \
	frontend-test app linux docker-run docs docs-serve

all: frontend test lint

# Build the TS/Vite frontend into src/terminux/web/static (committed).
frontend:
	cd frontend && npm ci && npm run build

# Frontend unit tests (vitest, pure logic — no browser).
frontend-test:
	cd frontend && npm run test

# Live frontend dev server (proxy API/WS to a running `terminux --no-window`).
frontend-dev:
	cd frontend && npm run dev

# Package a macOS .app bundle into dist/terminux.app (PyInstaller).
app: frontend
	uv run --active pyinstaller --noconfirm --clean terminux.spec

# Package a Linux onedir bundle via Docker -> dist/linux/terminux.
linux:
	docker build --target bundle -t terminux:bundle .
	rm -rf dist/linux && mkdir -p dist/linux
	docker create --name terminux_extract terminux:bundle >/dev/null
	docker cp terminux_extract:/app/dist/terminux dist/linux/terminux
	docker rm terminux_extract >/dev/null
	@echo "Linux bundle: dist/linux/terminux/terminux"

# Run the app in container web mode (browse to http://localhost:8000/?t=...).
docker-run:
	docker build --target bundle -t terminux:bundle .
	docker run --rm -p 8000:8000 terminux:bundle

# Build the documentation site (Zensical) -> site/.
docs:
	uv run zensical build

# Live docs preview with rebuild-on-save (http://127.0.0.1:8000).
docs-serve:
	uv run zensical serve

check: lint

lint:
	uv run --active ruff check
	uv run --active ruff format --check
	uv run --active ty check src
	uv run --active pyrefly check src
	uv run --active mypy src

format:
	uv run --active ruff format src tests
	uv run --active ruff check src tests --fix
	uv run --active ruff format src tests
	cd frontend && npm run format

# Runs the frontend (vitest) tests first, then the Python suite.
test: frontend-test
	uv run pytest

test-cov:
	uv run pytest --cov=terminux --cov-report=html --cov-report=term tests

clean:
	rm -rf .pytest_cache .ruff_cache dist build __pycache__ .mypy_cache \
		.coverage htmlcov .coverage.* *.egg-info
	adt clean

build: clean frontend
	uv build

publish: build
	uv publish
