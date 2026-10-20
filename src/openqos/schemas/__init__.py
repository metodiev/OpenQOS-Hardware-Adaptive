"""Locate and describe the bundled JSON schemas."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from openqos import HARDWARE_SCHEMA_VERSION
from openqos.errors import SchemaError


def hardware_schema_path(version: str | None = None) -> Path:
    """Return the filesystem path of the bundled hardware inventory schema."""
    version = version or HARDWARE_SCHEMA_VERSION
    resource = resources.files("openqos.schemas").joinpath(f"hardware-inventory-{version}.json")
    path = Path(str(resource))
    if not path.is_file():
        raise SchemaError(f"no bundled hardware schema for version {version!r}")
    return path


def available_hardware_schema_versions() -> list[str]:
    versions = []
    for entry in resources.files("openqos.schemas").iterdir():
        name = entry.name
        if name.startswith("hardware-inventory-") and name.endswith(".json"):
            versions.append(name[len("hardware-inventory-") : -len(".json")])
    return sorted(versions)
