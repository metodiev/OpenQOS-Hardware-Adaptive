"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FIXTURE_DIRECTORY = Path(__file__).parent / "hardware-fixtures"
sys.path.insert(0, str(_FIXTURE_DIRECTORY))

import builders  # noqa: E402


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if sys.platform == "linux":
        return
    skip = pytest.mark.skip(reason="requires Linux sysfs directory names")
    for item in items:
        if "linux_only" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def intel_laptop_tree(tmp_path: Path) -> Path:
    return builders.intel_laptop(tmp_path / "intel")


@pytest.fixture
def amd_desktop_tree(tmp_path: Path) -> Path:
    return builders.amd_desktop(tmp_path / "amd")


@pytest.fixture
def minimal_tree(tmp_path: Path) -> Path:
    return builders.minimal_unknown(tmp_path / "minimal")
