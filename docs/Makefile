# Documentation, built with Zensical (https://pypi.org/project/zensical/).
#
# Zensical is a dev dependency of turbodesk itself, so `--project ..` runs it from the
# repository's venv rather than needing one in here.

.PHONY: all build serve check clean publish deploy

ZENSICAL = uv run --project .. zensical

all: build

# Build to docs/site/.
build:
	$(ZENSICAL) build

# Live-reloading preview.
serve:
	$(ZENSICAL) serve

# Fail on warnings — a broken cross-reference is a broken build.
check:
	$(ZENSICAL) build --strict

# Publish
publish: clean build
	hop3  deploy --context prod -y

# Alias for publish
deploy: publish

clean:
	rm -rf site .cache
