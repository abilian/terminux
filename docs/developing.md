# Developing

## Setup

```sh
uv sync
make frontend        # build TS/Vite UI → src/terminux/web/static
```

## Common tasks

```sh
make frontend        # build the frontend (committed to src/terminux/web/static)
make frontend-dev    # live Vite dev server, proxying to a running backend
make frontend-test   # vitest unit tests (pure TS logic, no browser)
make test            # vitest, then pytest: unit, integration, e2e
make lint            # ruff + ty + pyrefly + mypy
make format          # ruff (Python) + prettier (frontend)
make test-cov        # pytest with HTML coverage report
```

For a live frontend loop: run `uv run terminux --no-window` in one terminal,
`make frontend-dev` in another — the Vite dev server proxies API/WS calls to the
running backend.

## Testing tiers

The pytest suite has three tiers, selectable by marker:

- **`unit`** — fast, isolated.
- **`integration`** — component interaction.
- **`e2e`** — drives the served UI with a real browser (Playwright, no
  pywebview).

The e2e tier needs the Playwright browser once:

```sh
uv run playwright install chromium
```

Frontend logic is covered separately by vitest (`make frontend-test`), which
`make test` runs first.

## Type checking

`make lint` runs **four** type checkers (`ty`, `pyrefly`, `mypy`) plus `ruff`.
mypy is in `strict` mode. The frontend has its own check:

```sh
cd frontend && npm run typecheck   # tsc
```

## Documentation

Docs are written in Markdown under `docs/` and built with
[Zensical](https://zensical.org/). Configuration lives in `zensical.toml`.

```sh
uv run zensical serve    # live preview with rebuild-on-save (http://127.0.0.1:8000)
uv run zensical build    # static site → site/
```

To add a page, create `docs/<name>.md` and add it to the `nav` array in
`zensical.toml`.
