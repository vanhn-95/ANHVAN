"""Cho phép mở app bằng `python -m desktop`."""

from desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
