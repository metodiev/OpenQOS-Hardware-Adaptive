#!/usr/bin/env python3
"""Regenerate the sample documents in ``docs/samples``.

The samples are produced from the synthetic Intel hybrid laptop fixture, in
privacy mode, so they contain no real hardware identifiers.

Usage:
    python scripts/generate_sample_inventory.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "hardware-fixtures"))

import builders  # noqa: E402

from openqos.hardware.scanner import scan  # noqa: E402
from openqos.optimizer.engine import build_plan  # noqa: E402
from openqos.profiles.model import build_profile  # noqa: E402

SAMPLES = PROJECT_ROOT / "docs" / "samples"


def _write(name: str, document: dict[str, Any]) -> None:
    target = SAMPLES / name
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = builders.intel_laptop(Path(directory) / "intel-laptop")
        inventory = scan(root, privacy=True)

    profile = build_profile(inventory)
    plan = build_plan(profile, policy="balanced")

    SAMPLES.mkdir(parents=True, exist_ok=True)
    _write("hardware-profile.json", inventory)
    _write("normalized-profile.json", profile)
    _write("optimization-plan.json", plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
