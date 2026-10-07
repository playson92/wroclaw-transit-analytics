"""Run only when invoked as a module."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
