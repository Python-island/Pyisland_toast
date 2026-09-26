"""开发目录、PyInstaller 和 Nuitka 目录包里的资源路径。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """PyInstaller 设置 sys.frozen。Nuitka 编译后的模块带有 __compiled__。"""
    if getattr(sys, "frozen", False):
        return True
    return "__compiled__" in globals()


def bundle_root() -> Path:
    """只读资源根目录。开发时是仓库根；目录包则在 exe 旁边。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return PACKAGE_DIR.parent


def project_root() -> Path:
    return bundle_root()


def frontend_dir() -> Path:
    return bundle_root() / "toast_frontend" / "frontend"


def dist_index() -> Path:
    return frontend_dir() / "dist" / "index.html"


def icon_path() -> Path:
    bundled = bundle_root() / "pyisland_toast" / "ico" / "PyislandLogo.ico"
    if bundled.is_file():
        return bundled
    return PACKAGE_DIR / "ico" / "PyislandLogo.ico"


def config_path() -> Path:
    """用户配置。冻结后放在 exe 旁边，避免写进临时目录或带走开发机密钥。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent / "ai_config.json"
    return PACKAGE_DIR / "ai_config.json"


def config_example_path() -> Path:
    bundled = bundle_root() / "pyisland_toast" / "ai_config.example.json"
    if bundled.is_file():
        return bundled
    return PACKAGE_DIR / "ai_config.example.json"


def log_path() -> Path | None:
    if is_frozen():
        return Path(sys.executable).resolve().parent / "pyisland.log"
    return None


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    target = log_path()
    handler = logging.FileHandler(target, encoding="utf-8") if target else logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.setLevel(logging.INFO)
    root.addHandler(handler)