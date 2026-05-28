# PyInstaller spec — OS-aware.
#   macOS  : `make app`   -> dist/terminux.app
#   Linux  : `make linux` -> dist/terminux/ (onedir, built in Docker)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

IS_MAC = sys.platform == "darwin"

project = Path(SPECPATH)
static_dir = project / "src" / "terminux" / "web" / "static"
assets_dir = project / "src" / "terminux" / "assets"
icon_icns = assets_dir / "icon.icns"
if not (static_dir / "index.html").exists():
    raise SystemExit("Frontend bundle missing — run `make frontend` before packaging.")

# Ship the built web UI and bundled icons next to the package so the
# package-relative Path(__file__) lookups still resolve inside PyInstaller.
datas = [
    (str(static_dir), "terminux/web/static"),
    (str(assets_dir), "terminux/assets"),
]
binaries = []
hiddenimports = ["terminux", "terminux.app"]

# pywebview plus the GUI toolkit its backend needs: pyobjc on macOS,
# PyGObject (GTK/WebKit2 via gobject-introspection) on Linux.
if IS_MAC:
    gui_pkgs = ("webview", "objc", "Foundation", "AppKit", "WebKit", "Quartz", "Security")
else:
    gui_pkgs = ("webview", "gi")

for pkg in gui_pkgs:
    try:
        d, b, h = collect_all(pkg)
    except Exception:  # noqa: BLE001 — optional toolkit piece, skip if absent
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="terminux",
    console=False,  # GUI app — no terminal window
    disable_windowed_traceback=False,
    argv_emulation=IS_MAC,  # macOS: deliver file-open / drag events
    target_arch=None,  # host arch
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="terminux",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="terminux.app",
        icon=str(icon_icns) if icon_icns.exists() else None,
        bundle_identifier="org.terminux.app",
        info_plist={
            "CFBundleName": "terminux",
            "CFBundleDisplayName": "terminux",
            "CFBundleShortVersionString": "0.1.0",
            "LSMinimumSystemVersion": "10.15.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
