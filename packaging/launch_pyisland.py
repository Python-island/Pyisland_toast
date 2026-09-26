"""Nuitka entry point. Same startup path as python -m pyisland_toast."""

import sys

if "__compiled__" in globals() and not getattr(sys, "frozen", False):
    sys.frozen = True

from pyisland_toast.app import main

if __name__ == "__main__":
    main()