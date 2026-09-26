"""Resource paths for the repo and a frozen executable."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyisland_toast import paths


class PathTests(unittest.TestCase):
    def test_dev_paths_stay_in_the_repo(self):
        self.assertTrue((paths.bundle_root() / "pyproject.toml").is_file())
        self.assertEqual(paths.config_path(), paths.PACKAGE_DIR / "ai_config.json")
        self.assertTrue(paths.icon_path().is_file())
        self.assertIsNone(paths.log_path())

    def test_frozen_config_stays_beside_the_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "Pyisland_toast.exe"
            exe.write_bytes(b"")
            bundle = root / "bundle"
            icon = bundle / "pyisland_toast" / "ico" / "PyislandLogo.ico"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"ico")
            dist = bundle / "toast_frontend" / "frontend" / "dist"
            dist.mkdir(parents=True)
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(exe)),
                patch.object(sys, "_MEIPASS", str(bundle), create=True),
            ):
                self.assertEqual(paths.config_path(), exe.resolve().parent / "ai_config.json")
                self.assertEqual(paths.icon_path().resolve(), icon.resolve())
                self.assertEqual(paths.dist_index(), dist / "index.html")
                self.assertEqual(paths.log_path(), exe.resolve().parent / "pyisland.log")

    def test_nuitka_folder_has_no_meipass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "Pyisland_toast.exe"
            exe.write_bytes(b"")
            icon = root / "pyisland_toast" / "ico" / "PyislandLogo.ico"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"ico")
            page = root / "toast_frontend" / "frontend" / "dist"
            page.mkdir(parents=True)
            with (
                patch.dict(paths.__dict__, {"__compiled__": object()}),
                patch.object(sys, "frozen", False, create=True),
                patch.object(sys, "executable", str(exe)),
            ):
                self.assertTrue(paths.is_frozen())
                self.assertEqual(paths.bundle_root(), exe.resolve().parent)
                self.assertEqual(paths.config_path(), exe.resolve().parent / "ai_config.json")
                self.assertEqual(paths.icon_path().resolve(), icon.resolve())
                self.assertEqual(paths.dist_index().resolve(), (page / "index.html").resolve())
                self.assertEqual(paths.log_path(), exe.resolve().parent / "pyisland.log")


if __name__ == "__main__":
    unittest.main()
