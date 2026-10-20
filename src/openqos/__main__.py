"""Allow running the command-line interface with ``python -m openqos``."""

from __future__ import annotations

import sys

from openqos.cli import main

if __name__ == "__main__":
    sys.exit(main())
