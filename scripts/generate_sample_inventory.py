#!/usr/bin/env python3
"""Regenerate docs/samples/hardware-profile.json from the synthetic laptop fixture.

Usage:
    python scripts/generate_sample_inventory.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "hardware-fixtures"))

import builders  # noqa: E402

from openqos.hardware.scanner import scan  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = builders.intel_laptop(Path(directory) / "intel-laptop")
        document = scan(root, privacy=True)

    target = PROJECT_ROOT / "docs" / "samples" / "hardware-profile.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
