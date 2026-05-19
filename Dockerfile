# Linux packaging for terminux.
#
#   make linux        -> builds the bundle image and copies the PyInstaller
#                        onedir to dist/linux/terminux
#   make docker-run   -> runs that image in web mode (terminux --no-window)
#
# The frozen onedir is the Linux desktop deliverable (GTK/WebKit2GTK GUI).
# The same image also runs headless web mode, which is the container-native
# use (no X11/Wayland needed).

# ---- 1. Build the TS/Vite frontend ----------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* frontend/tsconfig.json frontend/vite.config.ts ./frontend/
RUN cd frontend && npm install
COPY frontend/ ./frontend/
# Vite outDir is ../src/terminux/web/static (relative to frontend/).
RUN mkdir -p src/terminux/web && cd frontend && npm run build

# ---- 2. Build the PyInstaller Linux bundle --------------------------------
FROM ubuntu:24.04 AS bundle
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev python3-pip \
        python3-gi python3-gi-cairo gobject-introspection \
        gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
        libgtk-3-0 libwebkit2gtk-4.1-0 libgirepository-1.0-dev libcairo2 \
        build-essential binutils patchelf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# --system-site-packages so PyInstaller can collect the apt-installed `gi`.
RUN python3 -m venv --system-site-packages /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY --from=frontend /app/src/terminux/web/static ./src/terminux/web/static
COPY packaging/ ./packaging/
COPY terminux.spec ./
RUN pip install --no-cache-dir . pyinstaller>=6.0 \
    && pyinstaller --noconfirm --clean terminux.spec

# The onedir bundle is at /app/dist/terminux.
EXPOSE 8000
# Default: container-native web mode (no display required).
CMD ["/app/dist/terminux/terminux", "--no-window", "--host", "0.0.0.0", "--port", "8000"]
